import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "mirror-infisical.sh"


class MirrorInfisicalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.home = root / "home"
        self.home.mkdir()
        self.source = root / "source"
        self.target = root / "target.git"
        self.git("init", "-b", "main", str(self.source))
        self.git("-C", str(self.source), "config", "user.name", "Upstream")
        self.git("-C", str(self.source), "config", "user.email", "upstream@example.invalid")
        self.git("-C", str(self.source), "config", "commit.gpgsign", "false")
        self.git("-C", str(self.source), "config", "tag.gpgsign", "false")
        self.git("init", "--bare", str(self.target))
        self.git("-C", str(self.target), "symbolic-ref", "HEAD", "refs/heads/main")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def git(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments], check=True, capture_output=True, text=True
        ).stdout.strip()

    def commit(self, message: str, path: str = "file.txt", content: str | None = None) -> None:
        target = self.source / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content if content is not None else message, encoding="utf-8")
        self.git("-C", str(self.source), "add", path)
        self.git("-C", str(self.source), "commit", "-m", message)

    def tag(self, name: str) -> None:
        self.git("-C", str(self.source), "tag", name)

    def upstream_tip(self) -> str:
        return self.git("-C", str(self.source), "rev-parse", "main")

    def upstream_tag_sha(self, name: str) -> str:
        return self.git("-C", str(self.source), "rev-parse", name)

    def target_ref_sha(self, ref: str) -> str:
        output = self.git("ls-remote", str(self.target), ref)
        return output.split()[0] if output else ""

    def run_script(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        env = {
            "SOURCE_REPO": str(self.source),
            "SOURCE_BRANCH": "main",
            "INFISICAL_MIRROR_URL": str(self.target),
            "INFISICAL_MIRROR_BRANCH": "main",
            "CUSTOM_BRANCH": "custom",
            "GIT_USER_NAME": "Mirror Bot",
            "GIT_USER_EMAIL": "mirror-bot@example.invalid",
            "HOME": str(self.home),
        }
        env.update(overrides)
        return subprocess.run(
            ["bash", str(SCRIPT_PATH)], capture_output=True, text=True, env=env, check=False
        )

    def custom_work(self) -> Path:
        work = Path(self.temporary_directory.name) / "custom-work"
        self.git("clone", "-b", "main", str(self.target), str(work))
        self.git("-C", str(work), "config", "user.name", "YewFence")
        self.git("-C", str(work), "config", "user.email", "yewfence@example.invalid")
        self.git("-C", str(work), "config", "commit.gpgsign", "false")
        self.git("-C", str(work), "checkout", "-b", "custom")
        return work

    def custom_commit(
        self, work: Path, message: str, path: str = "custom.txt", content: str | None = None
    ) -> None:
        target = work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content if content is not None else message, encoding="utf-8")
        self.git("-C", str(work), "add", path)
        self.git("-C", str(work), "commit", "-m", message)

    def test_seed_mirrors_main_and_tags(self) -> None:
        self.commit("initial", content="one\n")
        self.tag("v1.0.0")
        self.commit("second", content="two\n")

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target_ref_sha("refs/heads/main"), self.upstream_tip())
        self.assertEqual(
            self.target_ref_sha("refs/tags/v1.0.0"), self.upstream_tag_sha("v1.0.0")
        )
        self.assertIn("does not exist yet", result.stdout)


    def test_incremental_fast_forwards_main_and_new_tag(self) -> None:
        self.commit("initial", content="one\n")
        self.run_script()
        self.commit("third", content="three\n")
        self.tag("v1.1.0")

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target_ref_sha("refs/heads/main"), self.upstream_tip())
        self.assertEqual(
            self.target_ref_sha("refs/tags/v1.1.0"), self.upstream_tag_sha("v1.1.0")
        )
        self.assertIn("Updated main", result.stdout)

    def test_no_change_run_is_a_noop(self) -> None:
        self.commit("initial", content="one\n")
        self.run_script()
        tip = self.target_ref_sha("refs/heads/main")

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target_ref_sha("refs/heads/main"), tip)
        self.assertIn("already up to date", result.stdout)

    def test_custom_rebased_onto_updated_main(self) -> None:
        self.commit("initial", content="one\n")
        self.run_script()
        work = self.custom_work()
        self.custom_commit(work, "custom one", path="custom-one.txt")
        self.custom_commit(work, "custom two", path="custom-two.txt")
        self.git("-C", str(work), "push", "origin", "custom")
        old_custom_sha = self.target_ref_sha("refs/heads/custom")
        self.commit("upstream advance", content="two\n")

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target_ref_sha("refs/heads/main"), self.upstream_tip())
        check = Path(self.temporary_directory.name) / "check"
        self.git("clone", str(self.target), str(check))
        self.assertEqual(
            self.git("-C", str(check), "rev-parse", "origin/custom~2"),
            self.git("-C", str(check), "rev-parse", "origin/main"),
        )
        log = self.git("-C", str(check), "log", "--oneline", "origin/custom")
        self.assertIn("custom one", log)
        self.assertIn("custom two", log)
        self.assertIn("upstream advance", log)
        self.assertNotEqual(old_custom_sha, self.target_ref_sha("refs/heads/custom"))

    def test_custom_already_on_top_is_skipped(self) -> None:
        self.commit("initial", content="one\n")
        self.run_script()
        work = self.custom_work()
        self.custom_commit(work, "custom one")
        self.git("-C", str(work), "push", "origin", "custom")
        self.run_script()
        rebased = self.target_ref_sha("refs/heads/custom")

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target_ref_sha("refs/heads/custom"), rebased)
        self.assertIn("already rebased", result.stdout)

    def test_conflict_keeps_custom_untouched_and_main_mirrored(self) -> None:
        self.commit("initial", content="line1\nline2\n")
        self.run_script()
        work = self.custom_work()
        self.custom_commit(work, "custom edit", path="file.txt", content="CUSTOM\nline2\n")
        self.git("-C", str(work), "push", "origin", "custom")
        old_custom_sha = self.target_ref_sha("refs/heads/custom")
        self.commit("upstream edit", content="UPSTREAM\nline2\n")

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.target_ref_sha("refs/heads/main"), self.upstream_tip())
        self.assertEqual(self.target_ref_sha("refs/heads/custom"), old_custom_sha)
        self.assertIn("conflicted", result.stderr)

    def test_upstream_rewrite_follows_main_and_flags_custom(self) -> None:
        self.commit("initial", content="one\n")
        self.run_script()
        work = self.custom_work()
        self.custom_commit(work, "custom one")
        self.git("-C", str(work), "push", "origin", "custom")
        old_custom_sha = self.target_ref_sha("refs/heads/custom")
        self.git("-C", str(self.source), "checkout", "--orphan", "rewritten")
        (self.source / "file.txt").unlink()
        self.commit("rewritten", content="fresh\n")
        self.git("-C", str(self.source), "branch", "-D", "main")
        self.git("-C", str(self.source), "branch", "-m", "main")

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.target_ref_sha("refs/heads/main"), self.upstream_tip())
        self.assertEqual(self.target_ref_sha("refs/heads/custom"), old_custom_sha)
        self.assertIn("rewrote its history", result.stderr)

    def test_missing_required_env_fails(self) -> None:
        result = self.run_script(SOURCE_REPO="")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SOURCE_REPO", result.stderr)


if __name__ == "__main__":
    unittest.main()
