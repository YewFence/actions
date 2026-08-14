import importlib.util
import json
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/render-mirror-matrix.py"
SPEC = importlib.util.spec_from_file_location("render_mirror_matrix", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
render_mirror_matrix = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_mirror_matrix)


class RenderMirrorMatrixTests(unittest.TestCase):
    def render(self, config: str, selected_name: str | None = None) -> str:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mirrors.toml"
            path.write_text(textwrap.dedent(config), encoding="utf-8")
            return render_mirror_matrix.render_mirror_matrix(path, selected_name)

    def assert_config_error(self, config: str, message: str) -> None:
        with self.assertRaisesRegex(render_mirror_matrix.ConfigError, message):
            self.render(config)

    def test_derives_name_and_renders_stable_json(self) -> None:
        self.assertEqual(
            self.render('''
                [[mirrors]]
                repository = "https://example.com/owner/example.git"
            '''),
            '{"include":[{"name":"example","repository":"https://example.com/owner/example.git"}]}',
        )

    def test_custom_name_and_selection(self) -> None:
        matrix = json.loads(self.render('''
            [[mirrors]]
            repository = "https://example.com/owner/first"

            [[mirrors]]
            repository = "https://example.com/owner/second.git"
            name = "backup.second"
        ''', "backup.second"))
        self.assertEqual(matrix["include"], [{
            "name": "backup.second",
            "repository": "https://example.com/owner/second.git",
        }])

    def test_rejects_unsafe_urls(self) -> None:
        for repository in (
            "http://example.com/owner/repo.git",
            "https://user:token@example.com/owner/repo.git",
            "https://example.com/owner/repo.git?token=value",
            "https://example.com/#fragment",
        ):
            with self.subTest(repository=repository):
                self.assert_config_error(
                    f'[[mirrors]]\nrepository = "{repository}"\n',
                    "HTTPS URL|must not contain|repository path",
                )

    def test_rejects_invalid_and_duplicate_names(self) -> None:
        self.assert_config_error('''
            [[mirrors]]
            repository = "https://example.com/owner/first.git"
            name = "owner/repo"
        ''', "name must")
        self.assert_config_error('''
            [[mirrors]]
            repository = "https://one.example/owner/repo.git"

            [[mirrors]]
            repository = "https://two.example/another/repo.git"
        ''', "duplicate mirror name")

    def test_rejects_unknown_fields_empty_config_and_selection(self) -> None:
        self.assert_config_error('mirrors = []\n', "at least one")
        self.assert_config_error('''
            [[mirrors]]
            repository = "https://example.com/owner/repo.git"
            branch = "main"
        ''', "unknown field 'branch'")
        with self.assertRaisesRegex(render_mirror_matrix.ConfigError, "unknown mirror selection"):
            self.render('''
                [[mirrors]]
                repository = "https://example.com/owner/repo.git"
            ''', "missing")


if __name__ == "__main__":
    unittest.main()
