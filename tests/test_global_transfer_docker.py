"""Run with IRISTOOL_DOCKER_TESTS=1 and a local IRIS Community Docker image."""

import asyncio
import json
import os
import sys
from unittest.mock import patch
from contextlib import ExitStack, contextmanager
from pathlib import Path
import subprocess
import time
import uuid
import unittest
from tempfile import TemporaryDirectory


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], check=True, capture_output=True, **kwargs).stdout


def session(container, namespace, commands):
    # IRIS Terminal can return exit code zero after an ObjectScript error.
    script = 'try { ' + commands + ' write !,"TEST-PASS",! } catch e { write !,e.DisplayString(),! }\nhalt\n'
    output = docker("exec", "-i", container, "iris", "session", "IRIS", "-U", namespace,
                    input=script.encode()).decode(errors="replace")
    assert "TEST-PASS" in output.splitlines(), output


def status(container, namespace, expression, setup=""):
    session(container, namespace, f'{setup} set sc={expression} if sc\'=1 {{ throw ##class(%Exception.StatusException).CreateFromStatus(sc) }}')


@contextmanager
def instance():
    name = "iristool-gof-" + uuid.uuid4().hex
    image = os.getenv("IRISTOOL_DOCKER_IMAGE", "intersystems/iris-community:latest-em")
    docker("run", "-d", "--name", name, "-p", "127.0.0.1::1972", image)
    try:
        for _ in range(90):
            try:
                session(name, "USER", "")
                break
            except (AssertionError, subprocess.CalledProcessError):
                time.sleep(1)
        else:
            raise AssertionError("IRIS failed to start")
        yield name
    finally:
        docker("rm", "-fv", name)


@unittest.skipUnless(os.getenv("IRISTOOL_DOCKER_TESTS") == "1", "Docker opt-in")
class GlobalTransferTests(unittest.TestCase):
    def test_cross_instance_global_files(self):
        with ExitStack() as resources:
            source = resources.enter_context(instance())
            target = resources.enter_context(instance())
            tmp_path = Path(resources.enter_context(TemporaryDirectory()))
            status(target, "%SYS", '##class(Config.Namespaces).Create("GOFDEST",.p)', 'set p("Globals")="USER"')
            for container in (source, target):
                status(container, "%SYS", '##class(Config.MapGlobals).Create("USER","GofSplit",.p)', 'set p("Database")="USER"')
                status(container, "%SYS", '##class(Config.MapGlobals).Create("USER","GofSplit(1)",.p)', 'set p("Database")="IRISTEMP"')
            session(source, "USER", 'set ^GofOne="root",^GofOne(1)=$char(0,255,9731),^GofTwo("key")=$listbuild(1,"two"),^GofSplit(1)="mapped",^GofSplit(2)="default"')
            session(source, "USER", 'for i=1:1:1200 { set ^GofTwo(i)=$system.Util.CreateGUID() }')
            for container in (source, target):
                session(container, "USER", 'if ##class(%Dictionary.CompiledClass).%ExistsId("iristool.GlobalTransfer") { throw ##class(%Exception.General).%New("Unexpected custom class") }')

            def check(container, ns, expression):
                session(container, ns, f'if \'({expression}) {{ throw ##class(%Exception.General).%New("Assertion failed") }}')

            # Exercise the same native-driver path as the CLI and MCP with a separate
            # non-admin account scoped to each disposable instance.
            from iristool import IRIStool
            from iristool.globals import export_globals, import_globals, resolve_global
            with ExitStack() as stack:
                clients = []
                for container, ns in ((source, "USER"), (target, "GOFDEST")):
                    password = uuid.uuid4().hex
                    status(container, "%SYS", '##class(Security.Roles).Create("GofTestRole","","%Native_ClassExecution:U","%DB_USER")')
                    status(container, "%SYS", f'##class(Security.Users).Create("GofTest","GofTestRole","{password}")')
                    port = docker("port", container, "1972/tcp").decode().strip().split(":")[-1]
                    clients.append(stack.enter_context(IRIStool(port=port, namespace=ns, username="GofTest", password=password)))
                origin, destination = clients
                assert resolve_global(origin, "GofOne")["exists"]
                assert resolve_global(origin, "GofSplit", "1")["destination"] != resolve_global(origin, "GofSplit", "2")["destination"]
                for names in (["GofOne", "GofSplit"], ["GofOne", "GofMissing"]):
                    with self.assertRaises(RuntimeError):
                        export_globals(origin, names, tmp_path / "partial.gof", output_format="block")
                    assert not (tmp_path / "partial.gof").exists()
                path = tmp_path / "workspace.gof"
                assert export_globals(origin, ["GofOne", "GofTwo"], path)["format"] == 7
                assert path.stat().st_size > 32768
                with self.assertRaises(FileExistsError):
                    export_globals(origin, ["GofTwo"], path)
                session(target, "GOFDEST", 'kill ^GofOne,^GofTwo')
                import_globals(destination, path)
                check(target, "GOFDEST", '(^GofOne(1)=$char(0,255,9731))&&(^GofTwo("key")=$listbuild(1,"two"))')
                check(target, "GOFDEST", '$length(^GofTwo(1200))>30')

                server_path = "/tmp/native-multiple.gof"
                assert export_globals(origin, ["GofOne", "GofTwo"], server_path, server_file=True)["format"] == 7
                server_copy = tmp_path / "server.gof"
                docker("cp", source + ":" + server_path, str(server_copy))
                self.assertEqual(server_copy.read_bytes()[4:10], b"~%GOF~")
                status(source, "%SYS", '##class(Config.Namespaces).Create("GOFLOCAL",.p)',
                       'set p("Globals")="IRISTEMP",p("Routines")="USER"')
                with IRIStool(port=origin.port, namespace="GOFLOCAL", username="GofTest",
                              password=origin.password) as local:
                    import_globals(local, server_path, names=["GofOne"], server_file=True)
                check(source, "GOFLOCAL", '(^GofOne(1)=$char(0,255,9731))&&($data(^GofTwo)=0)')
                session(target, "GOFDEST", 'kill ^GofOne,^GofTwo')
                import_globals(destination, path, names=["GofTwo"])
                check(target, "GOFDEST", '($data(^GofOne)=0)&&(^GofTwo("key")=$listbuild(1,"two"))')
                mapped = tmp_path / "mapped.gof"
                assert export_globals(origin, ["GofSplit", "GofOne"], mapped, records="S")["format"] == 5
                with self.assertRaisesRegex(ValueError, "Selective import"):
                    import_globals(destination, mapped, names=["GofOne"], records="S")
                check(target, "GOFDEST", '$data(^GofOne)=0')
                import_globals(destination, mapped, records="S")
                check(target, "GOFDEST", '(^GofSplit(1)="mapped")&&(^GofSplit(2)="default")&&(^GofOne="root")')

                # Exercise the real CLI entry point against the source instance.
                cli_file = tmp_path / "cli.gof"
                env = dict(os.environ, IRIS_HOST="127.0.0.1", IRIS_PORT=str(origin.port),
                           IRIS_NAMESPACE="USER", IRIS_USER="GofTest", IRIS_PASSWORD=origin.password)
                output = subprocess.check_output(
                    [sys.executable, "-c", "from iristool.cli import main_globals; main_globals()",
                     "export", str(cli_file), "GofOne", "GofTwo"], env=env)
                self.assertEqual(json.loads(output)["format"], 7)

                # A mapping can change after the preflight. Let IRIS itself skip a
                # global and verify the native output parameter prevents publication.
                with patch("iristool.globals.resolve_global", return_value={
                    "exists": True, "subscriptMapped": False,
                    "destination": "USER", "defaultDestination": "USER",
                }), self.assertRaisesRegex(RuntimeError, "skipped"):
                    export_globals(origin, ["GofOne", "GofSplit"], tmp_path / "skipped.gof")
                self.assertFalse((tmp_path / "skipped.gof").exists())

                if os.getenv("IRISTOOL_DOCKER_MCP") == "1":
                    from fastmcp import Client
                    from iristool.mcp_server import create_server
                    config = tmp_path / ".iristool.toml"
                    config.write_text(f'[instance.target]\nhost="127.0.0.1"\nport={destination.port}\n'
                                      f'namespace="GOFDEST"\nusername="GofTest"\npassword="{destination.password}"\n')
                    session(target, "GOFDEST", 'kill ^GofOne,^GofTwo')

                    async def exercise_mcp():
                        async with Client(create_server(workspace=tmp_path)) as client:
                            await client.call_tool("iris_import_globals", {"server": "target", "path": "cli.gof",
                                                                          "names": ["GofTwo"]})
                            info = await client.call_tool("iris_resolve_global", {"name": "GofTwo"})
                            self.assertTrue(info.data["exists"])
                            await client.call_tool("iris_export_globals", {"names": ["GofTwo"], "path": "mcp.gof"})

                    asyncio.run(exercise_mcp())
                    check(target, "GOFDEST", '($data(^GofOne)=0)&&(^GofTwo("key")=$listbuild(1,"two"))')
                    self.assertEqual((tmp_path / "mcp.gof").read_bytes()[4:10], b"~%GOF~")
