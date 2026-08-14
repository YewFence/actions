#!/usr/bin/env python3

import argparse
import json
import sys
from typing import Any


def render_image_plan(matrix: dict[str, Any]) -> str:
    lines = ["## Image build plan", ""]
    for image in matrix["include"]:
        lines.append(
            f"- `{image['name']}` from `{image['repository']}@{image['ref']}` "
            f"for `{image['platforms']}`"
        )
    return "\n".join(lines)


def render_mirror_plan(matrix: dict[str, Any]) -> str:
    lines = ["## Repository mirror plan", ""]
    for mirror in matrix["include"]:
        lines.append(f"- `{mirror['name']}` from `{mirror['repository']}`")
    return "\n".join(lines)


def render_mirror_result(
    result: dict[str, Any], mirror_name: str, source_repository: str
) -> str:
    lines = [
        "## Repository mirror result",
        "",
        f"- Mirror: `{mirror_name}`",
        f"- Source: `{source_repository}`",
        f"- Operation: `{result['operation']}`",
        f"- Default branch: `{result['source_branch']}`",
        f"- Old commit: `{result['old_sha'] or 'none'}`",
        f"- New commit: `{result['new_sha']}`",
    ]
    lines.extend(
        f"- Archive: `{archive_ref}`" for archive_ref in result["archive_refs"]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render portable workflow summaries")
    subparsers = parser.add_subparsers(dest="summary", required=True)
    subparsers.add_parser("image-plan", help="render an image build plan")
    subparsers.add_parser("mirror-plan", help="render a repository mirror plan")
    mirror_result_parser = subparsers.add_parser(
        "mirror-result", help="render a repository mirror result"
    )
    mirror_result_parser.add_argument("--name", required=True, help="mirror name")
    mirror_result_parser.add_argument(
        "--source", required=True, help="source repository URL"
    )
    arguments = parser.parse_args()
    payload = json.load(sys.stdin)

    if arguments.summary == "image-plan":
        summary = render_image_plan(payload)
    elif arguments.summary == "mirror-plan":
        summary = render_mirror_plan(payload)
    else:
        summary = render_mirror_result(payload, arguments.name, arguments.source)

    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
