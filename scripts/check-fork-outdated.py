#!/usr/bin/env python3
"""Check which of your GitHub forks are behind their upstream repositories.

Reads an ignore list (one repository name per line, ``#`` comments allowed),
lists the authenticated user's forks via the GraphQL API, compares each fork's
default branch with its parent using the REST compare endpoint, optionally
sends a Telegram message listing the outdated forks, and writes a Markdown
summary to stdout (intended for ``GITHUB_STEP_SUMMARY``).

Design document: docs/fork-outdated-notifier.md
"""

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GITHUB_API = "https://api.github.com"
TELEGRAM_API = "https://api.telegram.org"
USER_AGENT = "fork-outdated-notifier (+https://github.com/YewFence/actions)"
MAX_ERROR_DETAIL_CHARS = 200
REQUEST_TIMEOUT_SECONDS = 30

FORKS_QUERY = """
query($cursor: String) {
  viewer {
    repositories(first: 100, after: $cursor, isFork: true, ownerAffiliations: [OWNER]) {
      nodes {
        name
        nameWithOwner
        url
        isArchived
        defaultBranchRef { name }
        parent {
          nameWithOwner
          defaultBranchRef { name }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

# Placeholder used by tests to validate the query payload shape.


class ConfigError(Exception):
    """A required configuration value is missing or invalid."""


class ApiError(Exception):
    """An upstream API request failed."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _json_request(
    url: str,
    token: str | None,
    payload: dict | None = None,
    accept: str = "application/vnd.github+json",
) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Accept", accept)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:MAX_ERROR_DETAIL_CHARS]
        raise ApiError(
            f"HTTP {error.code} from {url}: {detail}", status=error.code
        ) from error
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, json.JSONDecodeError) as error:
        raise ApiError(f"request to {url} failed: {error}") from error


def list_forks(token: str) -> list[dict]:
    forks: list[dict] = []
    cursor: str | None = None
    while True:
        payload = _json_request(
            f"{GITHUB_API}/graphql",
            token,
            payload={"query": FORKS_QUERY, "variables": {"cursor": cursor}},
        )
        if payload.get("errors"):
            raise ApiError(f"GraphQL errors: {payload['errors']}")
        repositories = payload["data"]["viewer"]["repositories"]
        forks.extend(repositories["nodes"])
        page_info = repositories["pageInfo"]
        if not page_info["hasNextPage"]:
            return forks
        cursor = page_info["endCursor"]


def compare_fork(token: str, parent: str, parent_branch: str, fork: dict) -> dict:
    fork_owner, fork_repo = fork["nameWithOwner"].split("/", 1)
    fork_branch = fork["defaultBranchRef"]["name"]
    basehead = f"{parent_branch}...{fork_owner}:{fork_repo}:{fork_branch}"
    url = f"{GITHUB_API}/repos/{parent}/compare/{urllib.parse.quote(basehead, safe='...:')}"
    try:
        payload = _json_request(url, token)
    except ApiError as error:
        if error.status == 404:
            return {**fork, "unavailable": True, "behind_by": 0, "ahead_by": 0}
        raise
    return {
        **fork,
        "unavailable": False,
        "behind_by": payload["behind_by"],
        "ahead_by": payload["ahead_by"],
    }


def load_ignore_list(path: Path) -> list[str]:
    if not path.exists():
        raise ConfigError(f"ignore list not found: {path}")
    entries: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip().lower()
        if entry:
            entries.append(entry)
    return entries


def is_ignored(name_with_owner: str, ignore_entries: list[str]) -> bool:
    name = name_with_owner.lower()
    repo = name.split("/", 1)[-1]
    return any(entry in (name, repo) for entry in ignore_entries)


def render_message(forks: list[dict]) -> str:
    lines = [f"⚠️ {len(forks)} 个 fork 落后于上游:", ""]
    for fork in forks:
        parent = fork["parent"]["nameWithOwner"]
        lines.append(
            f"• {fork['nameWithOwner']} ← {parent} (落后 {fork['behind_by']} 个提交)"
        )
        lines.append(f"  {fork['url']}")
    return "\n".join(lines)


def render_summary(
    outdated: list[dict], unavailable: list[dict], total: int, ignored: int
) -> str:
    lines = [
        "## Fork outdated check",
        "",
        f"- Forks checked: {total}",
        f"- Outdated: {len(outdated)}",
        f"- Ignored: {ignored}",
        "",
    ]
    if outdated:
        lines.append("| Fork | Upstream | Behind |")
        lines.append("| --- | --- | ---: |")
        for fork in outdated:
            parent = fork["parent"]["nameWithOwner"]
            lines.append(
                f"| [{fork['nameWithOwner']}]({fork['url']}) | {parent} | {fork['behind_by']} |"
            )
        lines.append("")
    if unavailable:
        lines.append("### Upstream comparison unavailable")
        lines.extend(
            f"- `{fork['nameWithOwner']}` (parent: `{fork['parent']['nameWithOwner']}`)"
            for fork in unavailable
        )
        lines.append("")
    return "\n".join(lines)


def send_telegram(token: str, chat_id: str, text: str) -> None:
    _json_request(
        f"{TELEGRAM_API}/bot{token}/sendMessage",
        None,
        payload={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        accept="application/json",
    )


def run(
    gh_token: str,
    ignore_entries: list[str],
    telegram_token: str | None,
    telegram_chat_id: str | None,
) -> dict:
    forks = [
        fork
        for fork in list_forks(gh_token)
        if fork.get("parent")
        and fork.get("defaultBranchRef")
        and fork["parent"].get("defaultBranchRef")
    ]
    ignored = sum(
        1 for fork in forks if is_ignored(fork["nameWithOwner"], ignore_entries)
    )
    forks = [
        fork
        for fork in forks
        if not is_ignored(fork["nameWithOwner"], ignore_entries)
    ]
    compared = [
        compare_fork(
            gh_token,
            fork["parent"]["nameWithOwner"],
            fork["parent"]["defaultBranchRef"]["name"],
            fork,
        )
        for fork in forks
    ]
    outdated = [fork for fork in compared if not fork["unavailable"] and fork["behind_by"] > 0]
    unavailable = [fork for fork in compared if fork["unavailable"]]

    notified = False
    telegram_error = None
    if outdated:
        if telegram_token and telegram_chat_id:
            try:
                send_telegram(telegram_token, telegram_chat_id, render_message(outdated))
                notified = True
            except ApiError as error:
                telegram_error = str(error)
                print(f"::error::Telegram notification failed: {error}", file=sys.stderr)
        else:
            print("::warning::outdated forks found but Telegram is not configured", file=sys.stderr)

    summary = render_summary(outdated, unavailable, total=len(forks), ignored=ignored)
    print(summary)
    return {
        "outdated": [fork["nameWithOwner"] for fork in outdated],
        "unavailable": [fork["nameWithOwner"] for fork in unavailable],
        "notified": notified,
        "telegram_error": telegram_error,
    }


def main() -> int:
    gh_token = os.environ.get("FORKS_GH_TOKEN") or os.environ.get("GH_TOKEN")
    if not gh_token:
        raise ConfigError("missing FORKS_GH_TOKEN (or GH_TOKEN)")

    ignore_path = Path(os.environ.get("FORKS_IGNORE_FILE", "forks-ignore.txt"))
    ignore_entries = load_ignore_list(ignore_path)

    result = run(
        gh_token,
        ignore_entries,
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
    )
    return 1 if result["telegram_error"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ConfigError, ApiError) as error:
        print(f"::error::{error}", file=sys.stderr)
        sys.exit(1)
