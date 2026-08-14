#!/usr/bin/env python3

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


MIRROR_FIELDS = frozenset({"repository", "name", "private"})
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ConfigError(ValueError):
    pass


def _require_string(field: str, value: Any, index: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"mirrors[{index}]: {field} must be a non-empty string")
    if value != value.strip():
        raise ConfigError(f"mirrors[{index}]: {field} must not have surrounding whitespace")
    return value


def _normalize_mirror(raw_mirror: Any, index: int) -> dict[str, str | bool]:
    if not isinstance(raw_mirror, dict):
        raise ConfigError(f"mirrors[{index}] must be a table")

    unknown_fields = sorted(set(raw_mirror) - MIRROR_FIELDS)
    if unknown_fields:
        raise ConfigError(f"mirrors[{index}] contains unknown field {unknown_fields[0]!r}")
    if "repository" not in raw_mirror:
        raise ConfigError(f"mirrors[{index}] is missing required field 'repository'")

    repository = _require_string("repository", raw_mirror["repository"], index)
    parsed = urlsplit(repository)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ConfigError(f"mirrors[{index}]: repository must be an HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConfigError(
            f"mirrors[{index}]: repository must not contain credentials, a query, or a fragment"
        )

    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        raise ConfigError(f"mirrors[{index}]: repository must include a repository path")
    derived_name = path_parts[-1]
    if derived_name.endswith(".git"):
        derived_name = derived_name[:-4]

    name = _require_string("name", raw_mirror.get("name", derived_name), index)
    if not NAME_PATTERN.fullmatch(name):
        raise ConfigError(
            f"mirror {name!r}: name must start with a letter or number and contain only "
            "letters, numbers, dots, underscores, or hyphens"
        )

    private = raw_mirror.get("private", False)
    if not isinstance(private, bool):
        raise ConfigError(f"mirror {name!r}: private must be a boolean")

    return {"name": name, "repository": repository, "private": private}


def render_mirror_matrix(config_path: Path, selected_name: str | None = None) -> str:
    try:
        with config_path.open("rb") as config_file:
            config = tomllib.load(config_file)
    except OSError as error:
        raise ConfigError(f"unable to read {config_path}: {error}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"invalid TOML in {config_path}: {error}") from error

    unknown_fields = sorted(set(config) - {"mirrors"})
    if unknown_fields:
        raise ConfigError(f"configuration contains unknown field {unknown_fields[0]!r}")

    raw_mirrors = config.get("mirrors")
    if not isinstance(raw_mirrors, list) or not raw_mirrors:
        raise ConfigError("configuration must contain at least one [[mirrors]] table")

    mirrors = [_normalize_mirror(mirror, index) for index, mirror in enumerate(raw_mirrors)]
    names = [mirror["name"] for mirror in mirrors]
    duplicate_names = sorted({name for name in names if names.count(name) > 1})
    if duplicate_names:
        raise ConfigError(f"duplicate mirror name {duplicate_names[0]!r}")

    if selected_name:
        mirrors = [mirror for mirror in mirrors if mirror["name"] == selected_name]
        if not mirrors:
            raise ConfigError(f"unknown mirror selection {selected_name!r}")

    return json.dumps({"include": mirrors}, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate mirrors.toml and render a GitHub Actions matrix"
    )
    parser.add_argument(
        "--config", type=Path, default=Path("mirrors.toml"), help="TOML configuration path"
    )
    parser.add_argument("--name", help="render only the mirror with this name")
    arguments = parser.parse_args()

    try:
        print(render_mirror_matrix(arguments.config, arguments.name))
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
