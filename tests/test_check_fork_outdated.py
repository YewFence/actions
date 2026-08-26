import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/check-fork-outdated.py"
SPEC = importlib.util.spec_from_file_location("check_fork_outdated", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def make_fork(
    name: str,
    parent: str | None,
    branch: str = "main",
    parent_branch: str = "main",
    behind: int = 0,
    ahead: int = 0,
    unavailable: bool = False,
) -> dict:
    parent_data = (
        {
            "nameWithOwner": parent,
            "defaultBranchRef": {"name": parent_branch},
        }
        if parent
        else None
    )
    return {
        "name": name.split("/", 1)[-1],
        "nameWithOwner": name,
        "url": f"https://github.com/{name}",
        "isArchived": False,
        "defaultBranchRef": {"name": branch},
        "parent": parent_data,
        "behind_by": behind,
        "ahead_by": ahead,
        "unavailable": unavailable,
    }


class IgnoreListTests(unittest.TestCase):
    def load(self, content: str) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forks-ignore.txt"
            path.write_text(content, encoding="utf-8")
            return checker.load_ignore_list(path)

    def test_parses_entries_and_comments(self) -> None:
        entries = self.load(
            "# header comment\n"
            "YewFence/JASM\n"
            "\n"
            "  spaced/repo  # trailing comment\n"
            "UPPER/Case\n"
        )
        self.assertEqual(entries, ["yewfence/jasm", "spaced/repo", "upper/case"])

    def test_missing_file_is_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(
            checker.ConfigError
        ):
            checker.load_ignore_list(Path(directory) / "missing.txt")

    def test_matches_full_name_and_bare_repo_name(self) -> None:
        entries = ["yewfence/jasm", "kuma-mieru"]
        self.assertTrue(checker.is_ignored("YewFence/JASM", entries))
        self.assertTrue(checker.is_ignored("YewFence/kuma-mieru", entries))
        self.assertTrue(checker.is_ignored("someoneelse/kuma-mieru", entries))
        self.assertFalse(checker.is_ignored("YewFence/cinny", entries))


class FakeApi:
    def __init__(self, forks: list[dict], compares: dict[str, dict | checker.ApiError]):
        self.forks = forks
        self.compares = compares

    def list_forks(self, token: str) -> list[dict]:
        return self.forks

    def compare(self, token: str, parent: str, parent_branch: str, fork: dict) -> dict:
        key = f"{parent}@{parent_branch}"
        result = self.compares[key]
        if isinstance(result, checker.ApiError):
            raise result
        return {**fork, **result}


def run_with_api(
    api: FakeApi,
    ignore: list[str] | None = None,
    telegram_token: str | None = None,
    telegram_chat_id: str | None = None,
) -> dict:
    with (
        patch.object(checker, "list_forks", api.list_forks),
        patch.object(checker, "compare_fork", api.compare),
        patch.object(checker, "send_telegram") as send_mock,
    ):
        result = checker.run(
            "gh-token",
            ignore or [],
            telegram_token=telegram_token,
            telegram_chat_id=telegram_chat_id,
        )
    result["send_mock"] = send_mock
    return result


class RunTests(unittest.TestCase):
    def test_outdated_fork_is_reported_and_ahead_is_ignored(self) -> None:
        api = FakeApi(
            forks=[
                make_fork("me/old", "upstream/old", behind=5),
                make_fork("me/ahead", "upstream/ahead", ahead=3, behind=0),
                make_fork("me/same", "upstream/same"),
            ],
            compares={
                "upstream/old@main": {"behind_by": 5, "ahead_by": 0, "unavailable": False},
                "upstream/ahead@main": {"behind_by": 0, "ahead_by": 3, "unavailable": False},
                "upstream/same@main": {"behind_by": 0, "ahead_by": 0, "unavailable": False},
            },
        )
        result = run_with_api(api, telegram_token="t", telegram_chat_id="c")
        self.assertEqual(result["outdated"], ["me/old"])
        self.assertTrue(result["notified"])
        message = result["send_mock"].call_args.args[2]
        self.assertIn("me/old", message)
        self.assertIn("5", message)
        self.assertNotIn("me/ahead", message)

    def test_ignored_fork_is_never_compared(self) -> None:
        api = FakeApi(
            forks=[make_fork("me/skip", "upstream/skip", behind=9)],
            compares={},
        )
        result = run_with_api(
            api, ignore=["me/skip"], telegram_token="t", telegram_chat_id="c"
        )
        self.assertEqual(result["outdated"], [])
        self.assertFalse(result["notified"])
        result["send_mock"].assert_not_called()

    def test_missing_parent_or_branch_is_skipped(self) -> None:
        forks = [
            make_fork("me/no-parent", None),
            make_fork("me/no-branch", "upstream/x"),
            make_fork("me/parent-no-branch", "upstream/y"),
        ]
        forks[1]["defaultBranchRef"] = None
        forks[2]["parent"]["defaultBranchRef"] = None
        api = FakeApi(forks=forks, compares={})
        result = run_with_api(api)
        self.assertEqual(result["outdated"], [])
        self.assertEqual(result["unavailable"], [])

    def test_compare_404_marks_unavailable_not_outdated(self) -> None:
        api = FakeApi(
            forks=[make_fork("me/gone", "upstream/gone")],
            compares={"upstream/gone@main": {"behind_by": 0, "ahead_by": 0, "unavailable": True}},
        )
        result = run_with_api(api)
        self.assertEqual(result["outdated"], [])
        self.assertEqual(result["unavailable"], ["me/gone"])
        self.assertFalse(result["notified"])

    def test_no_outdated_sends_no_message(self) -> None:
        api = FakeApi(
            forks=[make_fork("me/fresh", "upstream/fresh")],
            compares={"upstream/fresh@main": {"behind_by": 0, "ahead_by": 0, "unavailable": False}},
        )
        result = run_with_api(api, telegram_token="t", telegram_chat_id="c")
        self.assertFalse(result["notified"])
        result["send_mock"].assert_not_called()

    def test_telegram_failure_is_reported_not_raised(self) -> None:
        api = FakeApi(
            forks=[make_fork("me/old", "upstream/old")],
            compares={"upstream/old@main": {"behind_by": 2, "ahead_by": 0, "unavailable": False}},
        )
        with (
            patch.object(checker, "list_forks", api.list_forks),
            patch.object(checker, "compare_fork", api.compare),
            patch.object(
                checker, "send_telegram", side_effect=checker.ApiError("boom")
            ),
        ):
            result = checker.run("gh-token", [], telegram_token="t", telegram_chat_id="c")
        self.assertFalse(result["notified"])
        self.assertIn("boom", result["telegram_error"])


class CompareForkTests(unittest.TestCase):
    def fork(self, owner_repo: str = "me/repo", branch: str = "main") -> dict:
        return {
            "name": owner_repo.split("/", 1)[-1],
            "nameWithOwner": owner_repo,
            "defaultBranchRef": {"name": branch},
        }

    def test_404_marks_unavailable(self) -> None:
        with patch.object(
            checker, "_json_request", side_effect=checker.ApiError("not found", status=404)
        ):
            result = checker.compare_fork("token", "upstream/repo", "main", self.fork())
        self.assertTrue(result["unavailable"])
        self.assertEqual(result["behind_by"], 0)

    def test_other_errors_propagate(self) -> None:
        with (
            patch.object(
                checker, "_json_request", side_effect=checker.ApiError("boom", status=500)
            ),
            self.assertRaises(checker.ApiError),
        ):
            checker.compare_fork("token", "upstream/repo", "main", self.fork())

    def test_url_encodes_cross_fork_basehead(self) -> None:
        captured: dict[str, str] = {}

        def fake_request(url: str, token: str | None, payload: dict | None = None, **kwargs) -> dict:
            captured["url"] = url
            return {"behind_by": 7, "ahead_by": 1}

        with patch.object(checker, "_json_request", fake_request):
            result = checker.compare_fork("token", "upstream/repo", "dev", self.fork("me/repo", "feature/x"))
        self.assertEqual(result["behind_by"], 7)
        self.assertEqual(result["ahead_by"], 1)
        self.assertIn("dev...me:repo:feature%2Fx", captured["url"])


class JsonRequestTests(unittest.TestCase):
    class FakeResponse:
        def __init__(self, payload: dict):
            self.payload = json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self.payload

    def test_http_error_includes_status_and_detail(self) -> None:
        error = checker.urllib.error.HTTPError(
            "https://api.github.com/x",
            403,
            "Forbidden",
            None,
            io.BytesIO(b'{"message":"rate limited"}'),
        )
        with (
            patch.object(checker.urllib.request, "urlopen", side_effect=error),
            self.assertRaises(checker.ApiError) as caught,
        ):
            checker._json_request("https://api.github.com/x", "token")
        self.assertEqual(caught.exception.status, 403)
        self.assertIn("rate limited", str(caught.exception))

    def test_post_sets_json_headers(self) -> None:
        captured: dict = {}

        def fake_urlopen(request, timeout):
            captured["headers"] = dict(request.header_items())
            captured["data"] = request.data
            return self.FakeResponse({"ok": True})

        with patch.object(checker.urllib.request, "urlopen", fake_urlopen):
            result = checker._json_request("https://example.com", "tok", payload={"a": 1})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(captured["headers"]["Authorization"], "Bearer tok")
        self.assertEqual(captured["data"], b'{"a": 1}')


class RenderTests(unittest.TestCase):
    def test_message_format(self) -> None:
        text = checker.render_message([make_fork("me/old", "upstream/old", behind=3)])
        self.assertIn("1 个 fork", text)
        self.assertIn("me/old", text)
        self.assertIn("upstream/old", text)
        self.assertIn("https://github.com/me/old", text)

    def test_summary_counts(self) -> None:
        summary = checker.render_summary(
            [make_fork("me/old", "upstream/old", behind=3)],
            [make_fork("me/gone", "upstream/gone")],
            total=4,
            ignored=2,
        )
        self.assertIn("Forks checked: 4", summary)
        self.assertIn("Outdated: 1", summary)
        self.assertIn("Ignored: 2", summary)
        self.assertIn("me/gone", summary)


if __name__ == "__main__":
    unittest.main()
