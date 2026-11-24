"""Run with IRISTOOL_DOCKER_TESTS=1 and a local IRIS Community Docker image."""

import os
from contextlib import ExitStack, contextmanager
from pathlib import Path
import subprocess
import time
import uuid
import unittest
from tempfile import TemporaryDirectory


SOURCE = Path(__file__).resolve().parents[1] / "iris/iristool/GlobalTransfer.cls"


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
        docker("cp", str(SOURCE), name + ":/tmp/GlobalTransfer.cls")
        status(name, "USER", '$system.OBJ.Load("/tmp/GlobalTransfer.cls","ck")')
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
            native = "##class(iristool.GlobalTransfer)"

            def check(container, ns, expression):
                session(container, ns, f'if \'({expression}) {{ throw ##class(%Exception.General).%New("Assertion failed") }}')

            def transfer(filename):
                local = tmp_path / filename
                docker("cp", source + ":/tmp/" + filename, str(local))
                docker("cp", str(local), target + ":/tmp/" + filename)
                return local

            check(source, "USER", f'{native}.ExportGlobals("GofOne,GofTwo","/tmp/multiple.gof")=7')
            status(source, "%SYS", '##class(Config.Namespaces).Create("GOFLOCAL",.p)',
                   'set p("Globals")="IRISTEMP",p("Routines")="USER"')
            check(source, "GOFLOCAL", '$data(^GofOne)=0')
            check(source, "GOFLOCAL", f'{native}.ImportGlobals("/tmp/multiple.gof","GofOne")')
            check(source, "GOFLOCAL", '(^GofOne(1)=$char(0,255,9731))&&($data(^GofTwo)=0)')
            assert transfer("multiple.gof").read_bytes()[4:10] == b"~%GOF~"
            check(target, "GOFDEST", f'{native}.ImportGlobals("/tmp/multiple.gof","GofTwo")')
            check(target, "GOFDEST", '($data(^GofOne)=0)&&(^GofTwo("key")=$listbuild(1,"two"))')
            check(target, "GOFDEST", f'{native}.ImportGlobals("/tmp/multiple.gof")')
            check(target, "GOFDEST", '(^GofOne="root")&&(^GofOne(1)=$char(0,255,9731))')
            check(source, "USER", f'{native}.ExportGlobals("GofSplit","/tmp/mapped.gof",0,"S")=5')
            transfer("mapped.gof")
            session(target, "USER", f'set rejected=0 try {{ do {native}.ImportGlobals("/tmp/mapped.gof","GofSplit") }} catch err {{ set rejected=1 }} if (\'rejected)||($data(^GofSplit)) {{ throw ##class(%Exception.General).%New("Unexpected selective import") }}')
            check(target, "USER", f'{native}.ImportGlobals("/tmp/mapped.gof")')
            check(target, "USER", '(^GofSplit(1)="mapped")&&(^GofSplit(2)="default")')

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
