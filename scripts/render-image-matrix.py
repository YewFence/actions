#!/usr/bin/env python3

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any


DEFAULT_CONTEXT = "."
DEFAULT_DOCKERFILE = "Dockerfile"
DEFAULT_PLATFORMS = ["linux/amd64"]
SUPPORTED_PLATFORMS = frozenset({"linux/amd64", "linux/arm64"})
IMAGE_FIELDS = frozenset(
    {"name", "repository", "ref", "context", "dockerfile", "platforms"}
)
REQUIRED_IMAGE_FIELDS = frozenset({"name", "repository", "ref"})
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
REPOSITORY_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]+$"
)


class ConfigError(ValueError):
    pass


def _require_string(image_name: str, field: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"image {image_name!r}: {field} must be a non-empty string")
    if value != value.strip():
        raise ConfigError(f"image {image_name!r}: {field} must not have surrounding whitespace")
    return value


def _validate_repository(image_name: str, value: Any) -> str:
    repository = _require_string(image_name, "repository", value)
    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise ConfigError(
            f"image {image_name!r}: repository must use the owner/repository format"
        )
    return repository


def _validate_path(image_name: str, field: str, value: Any) -> str:
    path_value = _require_string(image_name, field, value)
    if "\\" in path_value:
        raise ConfigError(f"image {image_name!r}: {field} must be a POSIX path")

    path = PurePosixPath(path_value)
    if path.is_absolute() or ".." in path.parts:
        raise ConfigError(
            f"image {image_name!r}: {field} must be a repository-relative path without '..'"
        )
    return path_value


def _validate_platforms(image_name: str, value: Any) -> str:
    if not isinstance(value, list) or not value:
        raise ConfigError(f"image {image_name!r}: platforms must be a non-empty array")
    if any(not isinstance(platform, str) for platform in value):
        raise ConfigError(f"image {image_name!r}: every platform must be a string")
    if len(value) != len(set(value)):
        raise ConfigError(f"image {image_name!r}: platforms must not contain duplicates")

    unsupported = sorted(set(value) - SUPPORTED_PLATFORMS)
    if unsupported:
        supported = ", ".join(sorted(SUPPORTED_PLATFORMS))
        raise ConfigError(
            f"image {image_name!r}: unsupported platform {unsupported[0]!r}; "
            f"supported platforms: {supported}"
        )
    return ",".join(value)


def _normalize_image(raw_image: Any, index: int) -> dict[str, str]:
    if not isinstance(raw_image, dict):
        raise ConfigError(f"images[{index}] must be a table")

    unknown_fields = sorted(set(raw_image) - IMAGE_FIELDS)
    if unknown_fields:
        raise ConfigError(
            f"images[{index}] contains unknown field {unknown_fields[0]!r}"
        )

    missing_fields = sorted(REQUIRED_IMAGE_FIELDS - set(raw_image))
    if missing_fields:
        raise ConfigError(
            f"images[{index}] is missing required field {missing_fields[0]!r}"
        )

    name = _require_string(f"at index {index}", "name", raw_image["name"])
    if not NAME_PATTERN.fullmatch(name):
        raise ConfigError(
            f"image {name!r}: name must be lowercase and contain only letters, "
            "numbers, dots, underscores, or hyphens"
        )

    return {
        "name": name,
        "repository": _validate_repository(name, raw_image["repository"]),
        "ref": _require_string(name, "ref", raw_image["ref"]),
        "context": _validate_path(
            name, "context", raw_image.get("context", DEFAULT_CONTEXT)
        ),
        "dockerfile": _validate_path(
            name, "dockerfile", raw_image.get("dockerfile", DEFAULT_DOCKERFILE)
        ),
        "platforms": _validate_platforms(
            name, raw_image.get("platforms", DEFAULT_PLATFORMS)
        ),
    }


def render_image_matrix(config_path: Path, selected_name: str | None = None) -> str:
    try:
        with config_path.open("rb") as config_file:
            config = tomllib.load(config_file)
    except OSError as error:
        raise ConfigError(f"unable to read {config_path}: {error}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"invalid TOML in {config_path}: {error}") from error

    unknown_top_level_fields = sorted(set(config) - {"images"})
    if unknown_top_level_fields:
        raise ConfigError(
            f"configuration contains unknown field {unknown_top_level_fields[0]!r}"
        )

    raw_images = config.get("images")
    if not isinstance(raw_images, list) or not raw_images:
        raise ConfigError("configuration must contain at least one [[images]] table")

    images = [_normalize_image(raw_image, index) for index, raw_image in enumerate(raw_images)]
    names = [image["name"] for image in images]
    duplicate_names = sorted({name for name in names if names.count(name) > 1})
    if duplicate_names:
        raise ConfigError(f"duplicate image name {duplicate_names[0]!r}")

    if selected_name:
        images = [image for image in images if image["name"] == selected_name]
        if not images:
            raise ConfigError(f"unknown image selection {selected_name!r}")

    return json.dumps({"include": images}, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate images.toml and render a GitHub Actions matrix"
    )
    parser.add_argument(
        "--config", type=Path, default=Path("images.toml"), help="TOML configuration path"
    )
    parser.add_argument("--name", help="render only the image with this name")
    arguments = parser.parse_args()

    try:
        print(render_image_matrix(arguments.config, arguments.name))
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
