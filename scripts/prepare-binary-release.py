#!/usr/bin/env -S uv run python
# USAGE arg "<name>" help="Tool in binaries.toml"
# USAGE arg "<directory>" help="Release plan output directory"
# USAGE flag "--recipe-revision <revision>" help="Commit of the distribution recipes"

"""Prepare a binary release from the repository's pinned source configuration."""

import json
import os
import re
import tomllib
from pathlib import Path


def prepare(name: str, directory: Path, recipe_revision: str | None = None) -> dict:
    """Write the version, platform matrix, and source identity used by every job."""
    config = tomllib.loads(Path("binaries.toml").read_text())["tools"][name]
    match = re.fullmatch(config["version_pattern"], config["tag"])
    if match is None:
        raise ValueError("source tag does not match version_pattern")
    version = ".".join(str(int(match[key])) for key in ("major", "minor", "patch"))
    if re.fullmatch(r"[0-9a-f]{40}", config["revision"]) is None:
        raise ValueError("revision must be a full commit SHA")
    commands = ", ".join(f"`{command}`" for command in config["commands"])
    notes = config["notes"].format(
        source_tag=config["tag"], revision=config["revision"], commands=commands
    )
    if recipe_revision:
        notes += f"\n\nDistribution recipe commit: `{recipe_revision}`\n"
    plan = {
        "name": name,
        "source": config["source"],
        "source_tag": config["tag"],
        "revision": config["revision"],
        "recipe_revision": recipe_revision,
        "version": version,
        "tag": f"{name}-v{version}",
        "commands": config["commands"],
        "notes": notes,
        "matrix": {"include": config["platforms"]},
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "release.json").write_text(json.dumps(plan, indent=2) + "\n")
    (directory / "notes.md").write_text(plan["notes"] + "\n")
    return plan


if __name__ == "__main__":
    print(json.dumps(prepare(
        os.environ["usage_name"],
        Path(os.environ["usage_directory"]),
        os.environ.get("usage_recipe_revision"),
    )))
