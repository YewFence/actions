#!/usr/bin/env -S uv run python
# USAGE arg "<directory>" help="Prepared release plan directory"
# USAGE arg "<target>" help="Target triple from the release matrix"
# USAGE flag "--gha-cache" help="Use the GitHub Actions BuildKit cache"
# USAGE flag "--host-proxy <url>" help="Use a local host proxy for container build steps"

"""Build one pinned source revision and package its commands and provenance."""

import json
import os
import subprocess
import tarfile
from pathlib import Path
from urllib.parse import urlencode


def build(
    directory: Path, target: str, gha_cache: bool = False, host_proxy: str | None = None
) -> Path:
    """Export a native container build and archive exactly the declared files."""
    directory = directory.resolve()
    plan = json.loads((directory / "release.json").read_text())
    platform = next(item for item in plan["matrix"]["include"] if item["target"] == target)
    output = directory / target
    query = urlencode({"tag": plan["source_tag"], "checksum": plan["revision"]})
    command = [
        "docker", "buildx", "build",
        "--file", str(Path(f"binaries/{plan['name']}/Dockerfile").resolve()),
        "--platform", platform["platform"],
        "--build-arg", f"VERSION={plan['source_tag']}",
        "--output", f"type=local,dest={output}",
        "--progress", "plain",
    ]
    if host_proxy:
        command += ["--network", "host"]
        for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            command += ["--build-arg", f"{variable}={host_proxy}"]
    if gha_cache:
        scope = f"binary-{plan['name']}-{target}"
        command += [
            "--cache-from", f"type=gha,scope={scope}",
            "--cache-to", f"type=gha,mode=max,scope={scope}",
        ]
    command.append(f"{plan['source']}?{query}")
    subprocess.run(command, check=True)
    (output / "BUILD.json").write_text(json.dumps(plan, indent=2) + "\n")
    archive = directory / f"{plan['name']}-{plan['version']}-{target}.tar.gz"
    with tarfile.open(archive, "w:gz") as package:
        for name in [*plan["commands"], "LICENSE", "BUILD.json"]:
            path = output / name
            if name in plan["commands"] and not os.access(path, os.X_OK):
                raise ValueError(f"built command is not executable: {path}")
            package.add(path, arcname=name, recursive=False)
    return archive


if __name__ == "__main__":
    print(build(
        Path(os.environ["usage_directory"]),
        os.environ["usage_target"],
        os.environ.get("usage_gha_cache") == "true",
        os.environ.get("usage_host_proxy"),
    ))
