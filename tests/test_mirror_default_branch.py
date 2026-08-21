import importlib.util
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import call, patch

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/mirror-default-branch.py"
SPEC = importlib.util.spec_from_file_location("mirror_default_branch", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
mirror = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mirror)


class MirrorDefaultBranchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.source = root / "source.git"
        self.target = root / "target.git"
        self.work = root / "work"
        self.git("init", "--bare", str(self.source))
        self.git("init", "--bare", str(self.target))
        self.git("init", "-b", "main", str(self.work))
        self.git("-C", str(self.work), "config", "user.name", "Mirror Tests")
        self.git("-C", str(self.work), "config", "user.email", "mirror@example.invalid")
        self.git("-C", str(self.work), "config", "commit.gpgsign", "false")
        self.git("-C", str(self.work), "config", "tag.gpgsign", "false")
        (self.work / "content.txt").write_text("one\n", encoding="utf-8")
        self.git("-C", str(self.work), "add", "content.txt")
        self.git("-C", str(self.work), "commit", "-m", "initial")
        self.git("-C", str(self.work), "remote", "add", "origin", str(self.source))
        self.git("-C", str(self.work), "push", "origin", "main")
        self.set_head(self.source, "main")
        self.now = datetime(2026, 8, 15, 12, 30, tzinfo=UTC)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def git(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments], check=True, capture_output=True, text=True
        ).stdout.strip()

    def set_head(self, repository: Path, branch: str) -> None:
        self.git("-C", str(repository), "symbolic-ref", "HEAD", f"refs/heads/{branch}")

    def sync(self):
        def set_default(branch: str) -> None:
            self.set_head(self.target, branch)

        return mirror.sync_repository(
            str(self.source), str(self.target), set_default, now=self.now
        )

    def refs(self, repository: Path) -> dict[str, str]:
        output = self.git(
            "-C", str(repository), "for-each-ref", "--format=%(refname) %(objectname)"
        )
        return dict(line.split(" ", 1) for line in output.splitlines() if line)

    def test_initial_sync_and_fast_forward_do_not_archive(self) -> None:
        created = self.sync()
        self.assertEqual(created.operation, "created")
        self.assertFalse(created.history_changed)

        (self.work / "content.txt").write_text("two\n", encoding="utf-8")
        self.git("-C", str(self.work), "commit", "-am", "update")
        self.git("-C", str(self.work), "push", "origin", "main")
        updated = self.sync()

        self.assertEqual(updated.operation, "fast_forward")
        self.assertFalse(updated.history_changed)
        self.assertFalse(any(ref.startswith("refs/heads/archive/") for ref in self.refs(self.target)))

    def test_force_push_archives_old_tip_and_reports_history_change(self) -> None:
        self.sync()
        old_sha = self.refs(self.target)["refs/heads/main"]
        self.git("-C", str(self.work), "checkout", "--orphan", "rewritten")
        (self.work / "content.txt").write_text("rewritten\n", encoding="utf-8")
        self.git("-C", str(self.work), "add", "content.txt")
        self.git("-C", str(self.work), "commit", "-m", "rewrite")
        self.git("-C", str(self.work), "push", "--force", "origin", "HEAD:main")

        result = self.sync()

        archive_ref = (
            "refs/heads/archive/heads/main/2026-08-15T12-30-00Z-" + old_sha
        )
        self.assertEqual(result.operation, "rewritten")
        self.assertTrue(result.history_changed)
        self.assertEqual(result.archive_refs, [archive_ref])
        self.assertEqual(self.refs(self.target)[archive_ref], old_sha)

    def test_default_branch_change_archives_and_removes_old_branch(self) -> None:
        self.sync()
        old_sha = self.refs(self.target)["refs/heads/main"]
        self.git("-C", str(self.work), "branch", "trunk")
        self.git("-C", str(self.work), "push", "origin", "trunk")
        self.set_head(self.source, "trunk")

        result = self.sync()
        refs = self.refs(self.target)

        self.assertEqual(result.operation, "default_branch_changed")
        self.assertTrue(result.history_changed)
        self.assertNotIn("refs/heads/main", refs)
        self.assertIn("refs/heads/trunk", refs)
        self.assertIn(
            "refs/heads/archive/heads/main/2026-08-15T12-30-00Z-" + old_sha,
            refs,
        )
        self.assertEqual(
            self.git("-C", str(self.target), "symbolic-ref", "HEAD"),
            "refs/heads/trunk",
        )

    def test_other_branches_and_tags_are_not_mirrored(self) -> None:
        self.git("-C", str(self.work), "branch", "other")
        self.git("-C", str(self.work), "tag", "v1")
        self.git("-C", str(self.work), "push", "origin", "other", "v1")

        self.sync()
        refs = self.refs(self.target)

        self.assertNotIn("refs/heads/other", refs)
        self.assertNotIn("refs/tags/v1", refs)

    def test_invalid_source_head_keeps_target_unchanged(self) -> None:
        self.sync()
        before = self.refs(self.target)
        self.set_head(self.source, "missing")

        with self.assertRaisesRegex(mirror.MirrorError, "valid default branch"):
            self.sync()

        self.assertEqual(self.refs(self.target), before)

    def test_missing_target_is_created_with_fj(self) -> None:
        missing = subprocess.CompletedProcess([], 1, "", "not found")
        created = subprocess.CompletedProcess([], 0, "created", "")
        units_disabled = subprocess.CompletedProcess([], 0, "", "")

        with patch.object(
            mirror, "_run", side_effect=[missing, created, units_disabled]
        ) as run:
            self.assertIsNone(mirror.ensure_target_repository("owner/repo", "repo"))

        self.assertEqual(
            run.call_args_list,
            [
                call(["fj", "--json", "repo", "view", "owner/repo"], check=False),
                call(
                    ["fj", "repo", "create", "repo", "--yes"],
                    check=False,
                ),
                call(
                    [
                        "fj",
                        "repo",
                        "units",
                        "--repo",
                        "owner/repo",
                        "actions",
                        "--enable",
                        "false",
                    ],
                    check=False,
                ),
            ],
        )

    def test_existing_target_has_actions_disabled(self) -> None:
        found = subprocess.CompletedProcess([], 0, "{}", "")
        units_disabled = subprocess.CompletedProcess([], 0, "", "")

        with patch.object(
            mirror, "_run", side_effect=[found, units_disabled]
        ) as run:
            self.assertIsNone(mirror.ensure_target_repository("owner/repo", "repo"))

        self.assertEqual(
            run.call_args_list,
            [
                call(["fj", "--json", "repo", "view", "owner/repo"], check=False),
                call(
                    [
                        "fj",
                        "repo",
                        "units",
                        "--repo",
                        "owner/repo",
                        "actions",
                        "--enable",
                        "false",
                    ],
                    check=False,
                ),
            ],
        )

    def test_private_target_adds_private_create_flag(self) -> None:
        missing = subprocess.CompletedProcess([], 1, "", "not found")
        created = subprocess.CompletedProcess([], 0, "created", "")
        units_disabled = subprocess.CompletedProcess([], 0, "", "")

        with patch.object(
            mirror, "_run", side_effect=[missing, created, units_disabled]
        ) as run:
            mirror.ensure_target_repository("owner/repo", "repo", private=True)

        self.assertEqual(
            run.call_args_list[1],
            call(
                ["fj", "repo", "create", "repo", "--private", "--yes"],
                check=False,
            ),
        )

    def test_units_failure_is_returned_without_blocking_sync(self) -> None:
        missing = subprocess.CompletedProcess([], 1, "", "not found")
        created = subprocess.CompletedProcess([], 0, "created", "")
        units_failed = subprocess.CompletedProcess([], 1, "", "units denied")

        with patch.object(
            mirror, "_run", side_effect=[missing, created, units_failed]
        ), patch("sys.stderr"):
            error = mirror.ensure_target_repository("owner/repo", "repo")

        self.assertEqual(error, "units denied")

    def test_failed_create_rechecks_repository_before_failing(self) -> None:
        missing = subprocess.CompletedProcess([], 1, "", "not found")
        conflict = subprocess.CompletedProcess([], 1, "", "already exists")
        found = subprocess.CompletedProcess([], 0, "{}", "")
        units_disabled = subprocess.CompletedProcess([], 0, "", "")

        with patch.object(
            mirror, "_run", side_effect=[missing, conflict, found, units_disabled]
        ):
            mirror.ensure_target_repository("owner/repo", "repo")

    def test_query_and_create_errors_are_both_reported(self) -> None:
        forbidden = subprocess.CompletedProcess([], 1, "", "forbidden")
        denied = subprocess.CompletedProcess([], 1, "", "permission denied")

        with patch.object(
            mirror, "_run", side_effect=[forbidden, denied, forbidden]
        ), self.assertRaisesRegex(
            mirror.MirrorError, "query: forbidden; create: permission denied"
        ):
            mirror.ensure_target_repository("owner/repo", "repo")


if __name__ == "__main__":
    unittest.main()
