"""Workspace and fleet configuration for the optional MCP server."""

from dataclasses import dataclass, field
import os
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


@dataclass(frozen=True)
class Connection:
    host: str
    port: int
    namespace: str
    username: str
    password: str = field(repr=False)
    read_only: bool = False

    def arguments(self):
        return {key: getattr(self, key) for key in
                ("host", "port", "namespace", "username", "password")}


@dataclass(frozen=True)
class Config:
    workspace: Path
    path: Path
    default_server: str
    connections: dict[str, Connection]
    huggingface_token: str | None = field(default=None, repr=False)
    kaggle_token: str | None = field(default=None, repr=False)

    def local_path(self, value: str) -> Path:
        path = (self.workspace / value).resolve()
        if not path.is_relative_to(self.workspace):
            raise ValueError("File paths must stay inside the configured workspace.")
        if path == self.path or path.suffix.lower() == ".toml":
            raise ValueError("Configuration files cannot be used as data files.")
        return path


def load_config(workspace=".", filename=None) -> Config:
    workspace = Path(workspace).expanduser().resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError("workspace must be a directory.")
    if filename is not None:
        path = Path(filename).expanduser()
        path = path if path.is_absolute() else workspace / path
    else:
        path = workspace / ".iristool.toml"
        if not path.exists():
            path = Path.home() / ".iristool.toml"
    path = path.resolve(strict=True)
    with path.open("rb") as source:
        data = tomllib.load(source)
    if set(data) - {"default_server", "instance", "providers"}:
        raise ValueError("Unknown configuration keys; use default_server, [instance.NAME] and [providers.NAME].")
    providers = data.get("providers", {})
    if not isinstance(providers, dict) or set(providers) - {"huggingface", "kaggle"}:
        raise ValueError("Only providers.huggingface and providers.kaggle are supported.")
    tokens = {}
    for name, settings in providers.items():
        if (not isinstance(settings, dict) or set(settings) not in ({"token"}, {"token_env"})):
            raise ValueError(f"provider {name!r} requires exactly one of token or token_env.")
        value = settings.get("token")
        if "token_env" in settings:
            variable = settings["token_env"]
            if not isinstance(variable, str) or not variable:
                raise ValueError(f"Invalid token_env for provider {name!r}.")
            value = os.environ.get(variable)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"A non-empty token is required for provider {name!r}.")
        tokens[name] = value
    instances = data.get("instance")
    if not isinstance(instances, dict) or not instances:
        raise ValueError("Configure at least one [instance.NAME].")
    connections = {}
    allowed = {"host", "port", "namespace", "username", "password", "password_env", "read_only"}
    for name, settings in instances.items():
        if not isinstance(settings, dict) or set(settings) - allowed:
            raise ValueError(f"Invalid settings for instance {name!r}.")
        for key in ("host", "namespace", "username"):
            if not isinstance(settings.get(key), str) or not settings[key].strip():
                raise ValueError(f"instance {name!r} requires a non-empty {key}.")
        port = settings.get("port", 1972)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError(f"Invalid SQL port for instance {name!r}.")
        read_only = settings.get("read_only", False)
        if type(read_only) is not bool:
            raise ValueError(f"read_only must be a boolean for instance {name!r}.")
        if ("password" in settings) == ("password_env" in settings):
            raise ValueError(f"instance {name!r} requires exactly one of password or password_env.")
        if "password_env" in settings:
            variable = settings["password_env"]
            if not isinstance(variable, str) or not variable or variable not in os.environ:
                raise ValueError(f"Password environment variable is missing for instance {name!r}.")
            password = os.environ[variable]
        else:
            password = settings["password"]
        if not isinstance(password, str) or not password:
            raise ValueError(f"A non-empty password is required for instance {name!r}.")
        connections[name] = Connection(settings["host"], port, settings["namespace"],
                                       settings["username"], password, read_only)
    default = data.get("default_server")
    if default is None and len(connections) == 1:
        default = next(iter(connections))
    if not isinstance(default, str) or default not in connections:
        raise ValueError("default_server must name a configured instance when using a fleet.")
    return Config(workspace, path, default, connections,
                  tokens.get("huggingface"), tokens.get("kaggle"))
