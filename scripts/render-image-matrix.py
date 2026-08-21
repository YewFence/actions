#!/usr/bin/env python3

import argparse
import json
import os
import re
import secrets
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import tomllib

DEFAULT_CONTEXT = "."
DEFAULT_DOCKERFILE = "Dockerfile"
DEFAULT_PLATFORMS = ["linux/amd64"]
SUPPORTED_PLATFORMS = frozenset({"linux/amd64", "linux/arm64"})
IMAGE_FIELDS = frozenset(
    {
        "name",
        "repository",
        "ref",
        "context",
        "dockerfile",
        "platforms",
        "username",
        "password",
    }
)
AUTH_FIELDS = frozenset({"username", "password"})
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


def _validate_authentication(image_name: str, image: dict[str, Any]) -> None:
    present = AUTH_FIELDS & image.keys()
    if present and present != AUTH_FIELDS:
        raise ConfigError(
            f"image {image_name!r}: username and password must be provided together"
        )
    for field in sorted(present):
        _require_string(image_name, field, image[field])


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
    _validate_authentication(name, raw_image)

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


def _load_toml(config_path: Path) -> dict[str, Any]:
    try:
        with config_path.open("rb") as config_file:
            return tomllib.load(config_file)
    except OSError as error:
        raise ConfigError(f"unable to read {config_path}: {error}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"invalid TOML in {config_path}: {error}") from error


def _parse_supplemental_toml(content: str) -> dict[str, Any]:
    try:
        return tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"invalid TOML in IMAGES_TOML: {error}") from error


def _validate_top_level(config: dict[str, Any], source: str) -> list[Any]:
    unknown_top_level_fields = sorted(set(config) - {"images"})
    if unknown_top_level_fields:
        raise ConfigError(
            f"{source} contains unknown field {unknown_top_level_fields[0]!r}"
        )

    raw_images = config.get("images", [])
    if not isinstance(raw_images, list):
        raise ConfigError(f"{source} must contain an images array")
    return raw_images


def _image_name(raw_image: Any, index: int, source: str) -> str:
    if not isinstance(raw_image, dict):
        raise ConfigError(f"{source} images[{index}] must be a table")
    if "name" not in raw_image:
        raise ConfigError(f"{source} images[{index}] is missing required field 'name'")
    return _require_string(f"at index {index}", "name", raw_image["name"])


def _merge_images(config: dict[str, Any], supplemental: dict[str, Any] | None) -> list[Any]:
    base_images = _validate_top_level(config, "configuration")
    if supplemental is None:
        return base_images

    supplemental_images = _validate_top_level(supplemental, "IMAGES_TOML")
    merged = [dict(image) if isinstance(image, dict) else image for image in base_images]
    indexes: dict[str, int] = {}
    for index, image in enumerate(merged):
        name = _image_name(image, index, "configuration")
        if name in indexes:
            raise ConfigError(f"duplicate image name {name!r}")
        indexes[name] = index

    supplemental_names: set[str] = set()
    for index, image in enumerate(supplemental_images):
        name = _image_name(image, index, "IMAGES_TOML")
        if name in supplemental_names:
            raise ConfigError(f"duplicate image name {name!r} in IMAGES_TOML")
        supplemental_names.add(name)
        if name in indexes:
            merged[indexes[name]] = {**merged[indexes[name]], **image}
        else:
            merged.append(image)
    return merged


def _load_merged_images(config_path: Path, images_toml: str | None = None) -> list[Any]:
    config = _load_toml(config_path)
    if images_toml is None:
        images_toml = os.environ.get("IMAGES_TOML")
    supplemental = None
    if images_toml and images_toml.strip():
        supplemental = _parse_supplemental_toml(images_toml)
    return _merge_images(config, supplemental)


def _normalized_images(config_path: Path, images_toml: str | None = None) -> list[dict[str, str]]:
    raw_images = _load_merged_images(config_path, images_toml)
    if not raw_images:
        raise ConfigError("configuration must contain at least one [[images]] table")
    images = [_normalize_image(raw_image, index) for index, raw_image in enumerate(raw_images)]
    names = [image["name"] for image in images]
    duplicate_names = sorted({name for name in names if names.count(name) > 1})
    if duplicate_names:
        raise ConfigError(f"duplicate image name {duplicate_names[0]!r}")
    return images


def _raw_image_by_name(config_path: Path, image_name: str, images_toml: str | None = None) -> dict[str, Any]:
    raw_images = _load_merged_images(config_path, images_toml)
    for index, raw_image in enumerate(raw_images):
        if _image_name(raw_image, index, "configuration") == image_name:
            _normalize_image(raw_image, index)
            return raw_image
    raise ConfigError(f"unknown image selection {image_name!r}")


def write_credentials_env(
    config_path: Path,
    image_name: str,
    env_path: Path,
    images_toml: str | None = None,
) -> None:
    image = _raw_image_by_name(config_path, image_name, images_toml)
    delimiter = f"IMAGES_TOML_{secrets.token_hex(16)}"
    values = {
        "SOURCE_USERNAME": image.get("username", ""),
        "SOURCE_PASSWORD": image.get("password", ""),
    }
    with env_path.open("a", encoding="utf-8") as environment:
        for key, value in values.items():
            environment.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def render_image_matrix(
    config_path: Path,
    selected_name: str | None = None,
    images_toml: str | None = None,
) -> str:
    images = _normalized_images(config_path, images_toml)

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
    parser.add_argument(
        "--credentials-env-file",
        type=Path,
        help="append selected image credentials to a GitHub Actions environment file",
    )
    arguments = parser.parse_args()

    try:
        if arguments.credentials_env_file is not None:
            if not arguments.name:
                raise ConfigError("--credentials-env-file requires --name")
            write_credentials_env(
                arguments.config, arguments.name, arguments.credentials_env_file
            )
        else:
            print(render_image_matrix(arguments.config, arguments.name))
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
