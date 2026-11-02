#!/usr/bin/env -S uv run python
# USAGE arg "<directory>" help="Directory containing release.json and platform digest files"
# USAGE flag "--dry-run" help="Print the manifest command without contacting the registry"

"""Publish all release tags on the same multi-platform image manifest."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def manifest_command(directory: Path) -> list[str]:
    """Build a manifest command from the exact metadata shared by platform builds."""
    metadata = json.loads((directory / "release.json").read_text(encoding="utf-8"))
    image = f"ghcr.io/yewfence/{metadata['target']}"
    digests = sorted(
        path.name for path in (directory / "digests").iterdir() if path.is_file()
    )
    if not digests:
        raise ValueError(f"no platform digests found for {metadata['target']}")
    if any(not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in digests):
        raise ValueError("invalid platform digest filename")
    command = ["docker", "buildx", "imagetools", "create"]
    for tag in metadata["tags"]:
        command.extend(["--tag", tag])
    for key in (
        "org.opencontainers.image.version",
        "org.opencontainers.image.revision",
    ):
        if metadata["labels"].get(key):
            command.extend(["--annotation", f"index:{key}={metadata['labels'][key]}"])
    command.extend(f"{image}@sha256:{digest}" for digest in digests)
    return command


def main() -> int:
    try:
        command = manifest_command(Path(os.environ["usage_directory"]))
        if os.environ.get("usage_dry_run") == "true":
            print(json.dumps(command))
        else:
            subprocess.run(command, check=True)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
