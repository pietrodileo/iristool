"""Transport native ObjectScript exports without interpreting the global data."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import iris


CLASS = "iristool.GlobalTransfer"
FORMATS = {"auto": 0, "dtm": 1, "vaxdsm": 3, "dsm11": 4, "ism": 5, "msm": 6, "block": 7}
CHUNK = 32768


def _names(names):
    if not isinstance(names, (list, tuple)) or not names:
        raise ValueError("Provide at least one global name")
    if any(not isinstance(name, str) or "," in name or name == "*" for name in names):
        raise ValueError("Pass individual global names")
    return ",".join(names)


def resolve_global(db, name, subscript=""):
    native = iris.createIRIS(db.conn)
    return json.loads(native.classMethodString(CLASS, "ResolveGlobal", name, subscript))


def _stream(native, remote):
    stream = native.classMethodObject("%Stream.FileBinary", "%New")
    if stream.invokeInteger("LinkToFile", remote) != 1:
        stream.close()
        raise OSError("Could not open IRIS staging file")
    return stream


def export_globals(db, names, path, *, output_format="auto", records="V",
                   translation="", server_file=False):
    native = iris.createIRIS(db.conn)
    selection = _names(names)
    options = (FORMATS[output_format], records, translation)
    if server_file:
        used = native.classMethodInteger(CLASS, "ExportGlobals", selection, str(path), *options)
    else:
        path = Path(path)
        if path.exists():
            raise FileExistsError(path)
        staged = json.loads(native.classMethodString(CLASS, "ExportTemp", selection, *options))
        used = staged["format"]
        local = None
        try:
            stream = _stream(native, staged["path"])
            try:
                with NamedTemporaryFile(dir=path.parent, delete=False) as output:
                    local = Path(output.name)
                    remaining = stream.getInteger("Size")
                    while remaining:
                        chunk = stream.invokeBytes("Read", min(CHUNK, remaining))
                        if not chunk:
                            raise OSError("Incomplete IRIS download")
                        output.write(chunk)
                        remaining -= len(chunk)
                os.link(local, path)  # Publish complete output only if destination is new.
            finally:
                stream.close()
        finally:
            if local is not None:
                local.unlink(missing_ok=True)
            native.classMethodBoolean("%File", "Delete", staged["path"])
    return {"path": str(path), "format": used, "globals": list(names), "namespace": db.namespace}


def import_globals(db, path, *, names=None, input_format="ism", records="V", server_file=False):
    native = iris.createIRIS(db.conn)
    selection = "*" if names is None else _names(names)
    options = (selection, FORMATS[input_format], records)
    if server_file:
        native.classMethodInteger(CLASS, "ImportGlobals", str(path), *options)
    else:
        with Path(path).open("rb") as source:
            remote = native.classMethodString("%File", "TempFilename", "gof")
            try:
                stream = _stream(native, remote)
                try:
                    while chunk := source.read(CHUNK):
                        if stream.invokeInteger("Write", chunk) != 1:
                            raise OSError("Failed writing IRIS staging file")
                    if stream.invokeInteger("%Save") != 1:
                        raise OSError("Failed saving IRIS staging file")
                finally:
                    stream.close()
                native.classMethodInteger(CLASS, "ImportGlobals", remote, *options)
            finally:
                native.classMethodBoolean("%File", "Delete", remote)
    return {"path": str(path), "globals": names if names is not None else "*", "namespace": db.namespace}
