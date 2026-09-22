#!/usr/bin/env python3
"""List the plaintext paths YewSeal manages in this repository.

Runs `yews plan --json` and prints one registered plaintext path per line,
sorted and deduplicated. Run it from the repository root, or from any
directory containing `.yewseal.toml`, since plan resolves the current
directory scope. The names are safe to see; the file contents are not —
never read, print, search, or excerpt these files.
"""

import json
import subprocess
import sys


def main() -> int:
    proc = subprocess.run(
        ["yews", "plan", "--json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stderr.strip(), file=sys.stderr)
        return proc.returncode
    pairs = json.loads(proc.stdout).get("file_pairs", [])
    for path in sorted({pair["plaintext"]["display"] for pair in pairs}):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
