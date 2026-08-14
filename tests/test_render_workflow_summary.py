import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "render-workflow-summary.py"
)
SPEC = importlib.util.spec_from_file_location("render_workflow_summary", SCRIPT_PATH)
render_workflow_summary = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(render_workflow_summary)


class RenderWorkflowSummaryTests(unittest.TestCase):
    def test_renders_image_plan(self) -> None:
        summary = render_workflow_summary.render_image_plan(
            {
                "include": [
                    {
                        "name": "example",
                        "repository": "owner/example",
                        "ref": "main",
                        "platforms": "linux/amd64,linux/arm64",
                    }
                ]
            }
        )

        self.assertEqual(
            summary,
            "## Image build plan\n\n"
            "- `example` from `owner/example@main` for `linux/amd64,linux/arm64`",
        )

    def test_renders_mirror_plan(self) -> None:
        summary = render_workflow_summary.render_mirror_plan(
            {
                "include": [
                    {
                        "name": "example",
                        "repository": "https://example.com/owner/example.git",
                    }
                ]
            }
        )

        self.assertEqual(
            summary,
            "## Repository mirror plan\n\n"
            "- `example` from `https://example.com/owner/example.git`",
        )

    def test_renders_mirror_result(self) -> None:
        summary = render_workflow_summary.render_mirror_result(
            {
                "operation": "rewritten",
                "source_branch": "main",
                "old_sha": None,
                "new_sha": "2222222",
                "archive_refs": ["refs/archive/main/1111111"],
            },
            "example",
            "https://example.com/owner/example.git",
        )

        self.assertEqual(
            summary,
            "## Repository mirror result\n\n"
            "- Mirror: `example`\n"
            "- Source: `https://example.com/owner/example.git`\n"
            "- Operation: `rewritten`\n"
            "- Default branch: `main`\n"
            "- Old commit: `none`\n"
            "- New commit: `2222222`\n"
            "- Archive: `refs/archive/main/1111111`",
        )


if __name__ == "__main__":
    unittest.main()
