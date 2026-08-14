#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable


class MirrorError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteHead:
    branch: str
    sha: str

    @property
    def ref(self) -> str:
        return f"refs/heads/{self.branch}"


@dataclass
class SyncResult:
    operation: str
    source_branch: str
    old_branch: str | None
    old_sha: str | None
    new_sha: str
    archive_refs: list[str]
    history_changed: bool


def _run(
    arguments: list[str], *, check: bool = True, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        arguments,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise MirrorError(f"{arguments[0]} failed: {detail}")
    return result


def _validate_ref(ref: str) -> None:
    _run(["git", "check-ref-format", ref])


def read_remote_head(remote: str, *, allow_empty: bool = False) -> RemoteHead | None:
    result = _run(["git", "ls-remote", "--symref", remote, "HEAD"])
    symbolic_ref = None
    sha = None
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or fields[1] != "HEAD":
            continue
        if fields[0].startswith("ref: "):
            symbolic_ref = fields[0][5:]
        else:
            sha = fields[0]

    if symbolic_ref is None and sha is None and allow_empty:
        return None
    if symbolic_ref is None or sha is None or not symbolic_ref.startswith("refs/heads/"):
        raise MirrorError(f"remote {remote!r} does not advertise a valid default branch")
    _validate_ref(symbolic_ref)
    return RemoteHead(symbolic_ref.removeprefix("refs/heads/"), sha)


def _read_remote_ref(remote: str, ref: str) -> str | None:
    _validate_ref(ref)
    result = _run(["git", "ls-remote", remote, ref])
    lines = [line for line in result.stdout.splitlines() if line]
    if not lines:
        return None
    if len(lines) != 1:
        raise MirrorError(f"remote {remote!r} returned multiple values for {ref}")
    sha, returned_ref = lines[0].split("\t", 1)
    if returned_ref != ref:
        raise MirrorError(f"remote {remote!r} returned an unexpected ref for {ref}")
    return sha


def _fetch(repository: Path, remote: str, remote_ref: str, local_ref: str) -> str:
    _validate_ref(remote_ref)
    _validate_ref(local_ref)
    _run(
        [
            "git",
            "fetch",
            "--no-tags",
            "--no-write-fetch-head",
            remote,
            f"+{remote_ref}:{local_ref}",
        ],
        cwd=repository,
    )
    return _run(["git", "rev-parse", local_ref], cwd=repository).stdout.strip()


def _is_ancestor(repository: Path, old_sha: str, new_sha: str) -> bool:
    result = _run(
        ["git", "merge-base", "--is-ancestor", old_sha, new_sha],
        check=False,
        cwd=repository,
    )
    if result.returncode not in (0, 1):
        raise MirrorError(result.stderr.strip() or "git merge-base failed")
    return result.returncode == 0


def _archive(
    repository: Path, target: str, branch: str, sha: str, timestamp: str
) -> str:
    archive_ref = f"refs/heads/archive/heads/{branch}/{timestamp}-{sha}"
    _validate_ref(archive_ref)
    _run(["git", "push", target, f"{sha}:{archive_ref}"], cwd=repository)
    return archive_ref


def _push_current(
    repository: Path,
    target: str,
    branch: str,
    new_sha: str,
    expected_sha: str | None,
) -> None:
    ref = f"refs/heads/{branch}"
    expected = expected_sha or ""
    arguments = [
        "git",
        "push",
        target,
        f"{new_sha}:{ref}",
        f"--force-with-lease={ref}:{expected}",
    ]
    _run(arguments, cwd=repository)


def sync_repository(
    source: str,
    target: str,
    set_default_branch: Callable[[str], None],
    *,
    now: datetime | None = None,
) -> SyncResult:
    source_head = read_remote_head(source)
    assert source_head is not None
    target_head = read_remote_head(target, allow_empty=True)
    timestamp = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H-%M-%SZ")
    archive_refs: list[str] = []

    with tempfile.TemporaryDirectory(prefix="mirror-default-branch-") as directory:
        repository = Path(directory)
        _run(["git", "init", "--bare", str(repository)])
        fetched_source_sha = _fetch(
            repository, source, source_head.ref, "refs/sync/source"
        )
        if fetched_source_sha != source_head.sha:
            raise MirrorError("source default branch changed while it was being fetched")
        if read_remote_head(source) != source_head:
            raise MirrorError("source default branch changed while it was being fetched")

        confirmed_target_head = read_remote_head(target, allow_empty=True)
        if confirmed_target_head != target_head:
            raise MirrorError("target default branch changed while it was being inspected")

        if target_head is None:
            _push_current(repository, target, source_head.branch, source_head.sha, None)
            set_default_branch(source_head.branch)
            return SyncResult(
                "created",
                source_head.branch,
                None,
                None,
                source_head.sha,
                archive_refs,
                False,
            )

        fetched_target_sha = _fetch(
            repository, target, target_head.ref, "refs/sync/target"
        )
        if fetched_target_sha != target_head.sha:
            raise MirrorError("target default branch changed while it was being fetched")

        if source_head.branch == target_head.branch:
            if source_head.sha == target_head.sha:
                return SyncResult(
                    "unchanged",
                    source_head.branch,
                    target_head.branch,
                    target_head.sha,
                    source_head.sha,
                    archive_refs,
                    False,
                )
            if _is_ancestor(repository, target_head.sha, source_head.sha):
                _run(
                    [
                        "git",
                        "push",
                        target,
                        f"{source_head.sha}:{source_head.ref}",
                    ],
                    cwd=repository,
                )
                operation = "fast_forward"
                history_changed = False
            else:
                archive_refs.append(
                    _archive(
                        repository,
                        target,
                        target_head.branch,
                        target_head.sha,
                        timestamp,
                    )
                )
                _push_current(
                    repository,
                    target,
                    source_head.branch,
                    source_head.sha,
                    target_head.sha,
                )
                operation = "rewritten"
                history_changed = True
            return SyncResult(
                operation,
                source_head.branch,
                target_head.branch,
                target_head.sha,
                source_head.sha,
                archive_refs,
                history_changed,
            )

        archive_refs.append(
            _archive(
                repository,
                target,
                target_head.branch,
                target_head.sha,
                timestamp,
            )
        )
        new_target_ref = source_head.ref
        new_target_sha = _read_remote_ref(target, new_target_ref)
        if new_target_sha != source_head.sha:
            _push_current(
                repository,
                target,
                source_head.branch,
                source_head.sha,
                new_target_sha,
            )
        set_default_branch(source_head.branch)
        _run(
            [
                "git",
                "push",
                target,
                f"--force-with-lease={target_head.ref}:{target_head.sha}",
                f":{target_head.ref}",
            ],
            cwd=repository,
        )
        return SyncResult(
            "default_branch_changed",
            source_head.branch,
            target_head.branch,
            target_head.sha,
            source_head.sha,
            archive_refs,
            True,
        )


def ensure_target_repository(repository: str, name: str) -> None:
    view = _run(["fj", "--json", "repo", "view", repository], check=False)
    if view.returncode == 0:
        return

    create = _run(
        ["fj", "repo", "create", name, "--private", "--yes"], check=False
    )
    if create.returncode == 0:
        return

    retry = _run(["fj", "--json", "repo", "view", repository], check=False)
    if retry.returncode == 0:
        return

    view_error = view.stderr.strip() or view.stdout.strip() or "query failed"
    create_error = create.stderr.strip() or create.stdout.strip() or "creation failed"
    raise MirrorError(
        f"unable to query or create Forgejo repository; "
        f"query: {view_error}; create: {create_error}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirror and archive a remote default branch")
    parser.add_argument("--source", required=True, help="public HTTPS source repository")
    parser.add_argument("--target", required=True, help="authenticated Forgejo Git remote")
    parser.add_argument(
        "--target-repository", required=True, help="Forgejo owner/repository identifier"
    )
    parser.add_argument("--target-name", required=True, help="Forgejo repository name")
    arguments = parser.parse_args()

    try:
        ensure_target_repository(arguments.target_repository, arguments.target_name)

        def set_default_branch(branch: str) -> None:
            _run(
                [
                    "fj",
                    "repo",
                    "edit",
                    "--repo",
                    arguments.target_repository,
                    "--default-branch",
                    branch,
                    "--yes",
                ]
            )

        result = sync_repository(arguments.source, arguments.target, set_default_branch)
        print(json.dumps(asdict(result), separators=(",", ":")))
    except MirrorError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
