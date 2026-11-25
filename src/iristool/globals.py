"""Transfer global files using the system classes supplied with IRIS."""

from contextlib import closing, contextmanager
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

import iris


FORMATS = {"auto": 0, "dtm": 1, "vaxdsm": 3, "dsm11": 4, "ism": 5, "msm": 6, "block": 7}
CHUNK = 32768
BLOCK_HEADER = b"\x06\x00\x00\x00~%GOF~"


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r"\^?[A-Za-z%][A-Za-z0-9.]*", value):
        raise ValueError("Expected a single unsubscripted global name")
    return value.removeprefix("^")


def _names(names):
    if not isinstance(names, (list, tuple)) or not names:
        raise ValueError("Provide at least one global name")
    return [_name(name) for name in names]


def _check(native, status):
    if status != "1":
        message = native.classMethodString("%SYSTEM.Status", "GetErrorText", status)
        raise RuntimeError(message or "IRIS operation failed")


def resolve_global(db, name, subscript=""):
    native = iris.createIRIS(db.conn)
    name = _name(name)
    ns = db.namespace
    destination = native.classMethodString("%SYS.Namespace", "GetGlobalDest", ns, name, subscript)
    default = native.classMethodString("%SYS.Namespace", "GetGlobalDest", ns)
    mappings = []
    exists = mapped = False
    with closing(native.classMethodObject("%ResultSet", "%New", "%SYS.GlobalQuery:NameSpaceList")) as rows:
        _check(native, rows.invokeString("Execute", ns, name, 1))
        status = iris.IRISReference(None)
        while rows.invokeBoolean("Next", status):
            key = rows.invokeString("Get", "Name")
            mappings.append({"name": key, "location": rows.invokeString("Get", "Location")})
            exists |= rows.invokeBoolean("Get", "HasData")
            mapped |= rows.invokeBoolean("Get", "HasSubscripts") or "(" in key
        _check(native, status.getString())
    return {"namespace": ns, "global": name, "destination": destination,
            "defaultDestination": default, "mappings": mappings,
            "exists": exists, "subscriptMapped": mapped}


@contextmanager
def _temporary(native):
    path = native.classMethodString("%File", "TempFilename", "gof")
    if not path:
        raise OSError("Could not allocate IRIS staging file")
    try:
        yield path
    finally:
        native.classMethodBoolean("%File", "Delete", path)


@contextmanager
def _stream(native, remote):
    with closing(native.classMethodObject("%Stream.FileBinary", "%New")) as stream:
        _check(native, stream.invokeString("LinkToFile", remote))
        yield stream


def _download(native, remote, path):
    local = None
    try:
        with _stream(native, remote) as stream, NamedTemporaryFile(dir=path.parent, delete=False) as output:
            local = Path(output.name)
            remaining = stream.getInteger("Size")
            while remaining:
                chunk = stream.invokeBytes("Read", min(CHUNK, remaining))
                if not chunk:
                    raise OSError("Incomplete IRIS download")
                output.write(chunk)
                remaining -= len(chunk)
        os.link(local, path)
    finally:
        if local is not None:
            local.unlink(missing_ok=True)


def export_globals(db, names, path, *, output_format="auto", records="V",
                   translation="", server_file=False):
    native = iris.createIRIS(db.conn)
    selected = _names(names)
    if records not in ("V", "S"):
        raise ValueError("Expected record format V or S")
    used = FORMATS[output_format]
    for name in selected:
        info = resolve_global(db, name)
        if not info["exists"]:
            raise RuntimeError(f"Missing or inaccessible global: {name}")
        if info["subscriptMapped"] or info["destination"] != info["defaultDestination"]:
            if used == 7:
                raise RuntimeError(f"Block format cannot export mapped global: {name}")
            if used == 0:
                used = 5
    used = used or 7
    exists = native.classMethodBoolean("%File", "Exists", str(path)) if server_file else Path(path).exists()
    if exists:
        raise FileExistsError(path)
    with _temporary(native) as remote:
        skipped = iris.IRISReference(None)
        status = native.classMethodString(
            "%Library.Global", "Export", db.namespace, ",".join(selected),
            remote, used, records, "-d", translation, skipped,
        )
        _check(native, status)
        if skipped.getValue() not in (None, "", 0, "0"):
            raise RuntimeError(f"IRIS skipped globals during export: {skipped.getValue()!r}")
        if server_file:
            if not native.classMethodBoolean("%File", "CopyFile", remote, str(path), 0):
                raise OSError("Could not create IRIS output file")
        else:
            _download(native, remote, Path(path))
    return {"path": str(path), "format": used, "globals": list(names), "namespace": db.namespace}


def import_globals(db, path, *, names=None, input_format="ism", records="V", server_file=False):
    native = iris.createIRIS(db.conn)
    selection = "*" if names is None else ",".join(_names(names))
    if records not in ("V", "S") or input_format == "auto":
        raise ValueError("Invalid import format or record format")
    fmt = FORMATS[input_format]

    def load(remote):
        file_format = fmt
        if selection != "*":
            with _stream(native, remote) as stream:
                if stream.invokeBytes("Read", len(BLOCK_HEADER)) != BLOCK_HEADER:
                    raise ValueError("Selective import requires a native block file")
                _check(native, stream.invokeString("Rewind"))
                file_format = FORMATS["block"]
        status = native.classMethodString(
            "%Library.Global", "Import", db.namespace, selection, remote, file_format, int(records == "V"),
        )
        _check(native, status)

    if server_file:
        load(str(path))
    else:
        with Path(path).open("rb") as source, _temporary(native) as remote:
            with _stream(native, remote) as stream:
                while chunk := source.read(CHUNK):
                    _check(native, stream.invokeString("Write", chunk))
                _check(native, stream.invokeString("%Save"))
            load(remote)
    return {"path": str(path), "globals": names if names is not None else "*", "namespace": db.namespace}
