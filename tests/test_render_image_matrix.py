import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "render-image-matrix.py"
)
SPEC = importlib.util.spec_from_file_location("render_image_matrix", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
render_image_matrix = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_image_matrix)


class RenderImageMatrixTests(unittest.TestCase):
    def render(
        self,
        config: str,
        selected_name: str | None = None,
        images_toml: str | None = None,
    ) -> str:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "images.toml"
            config_path.write_text(textwrap.dedent(config), encoding="utf-8")
            return render_image_matrix.render_image_matrix(
                config_path, selected_name, images_toml
            )

    def assert_config_error(
        self, config: str, message: str, images_toml: str | None = None
    ) -> None:
        with self.assertRaisesRegex(render_image_matrix.ConfigError, message):
            self.render(config, images_toml=images_toml)

    def test_minimal_configuration_uses_defaults_and_stable_json(self) -> None:
        matrix = self.render(
            """
            [[images]]
            name = "example"
            repository = "owner/example"
            ref = "main"
            """
        )

        self.assertEqual(
            matrix,
            '{"include":[{"name":"example","repository":"owner/example",'
            '"ref":"main","context":".","dockerfile":"Dockerfile",'
            '"platforms":"linux/amd64"}]}',
        )

    def test_multiple_images_and_name_selection(self) -> None:
        config = """
            [[images]]
            name = "first"
            repository = "owner/first"
            ref = "main"

            [[images]]
            name = "second"
            repository = "another/second"
            ref = "v1.2.3"
            context = "docker"
            dockerfile = "docker/Dockerfile"
            platforms = ["linux/amd64", "linux/arm64"]
        """

        matrix = json.loads(self.render(config, "second"))

        self.assertEqual(
            matrix,
            {
                "include": [
                    {
                        "name": "second",
                        "repository": "another/second",
                        "ref": "v1.2.3",
                        "context": "docker",
                        "dockerfile": "docker/Dockerfile",
                        "platforms": "linux/amd64,linux/arm64",
                    }
                ]
            },
        )

    def test_credentials_are_validated_but_not_rendered(self) -> None:
        matrix = json.loads(
            self.render(
                """
                [[images]]
                name = "private"
                repository = "owner/private"
                ref = "main"
                """,
                images_toml='''
                    [[images]]
                    name = "private"
                    username = "octocat"
                    password = "token-value"
                ''',
            )
        )

        self.assertEqual(matrix["include"][0]["repository"], "owner/private")
        self.assertNotIn("username", matrix["include"][0])
        self.assertNotIn("password", matrix["include"][0])

    def test_images_toml_can_add_a_private_image(self) -> None:
        matrix = json.loads(
            self.render(
                """
                [[images]]
                name = "public"
                repository = "owner/public"
                ref = "main"
                """,
                images_toml='''
                    [[images]]
                    name = "private"
                    repository = "owner/private"
                    ref = "main"
                    username = "octocat"
                    password = "token-value"
                ''',
            )
        )

        self.assertEqual(
            [image["name"] for image in matrix["include"]], ["public", "private"]
        )

    def test_images_toml_environment_variable_is_merged(self) -> None:
        previous = os.environ.get("IMAGES_TOML")
        os.environ["IMAGES_TOML"] = textwrap.dedent(
            """
            [[images]]
            name = "private"
            repository = "owner/private"
            ref = "main"
            username = "octocat"
            password = "token-value"
            """
        )
        try:
            matrix = json.loads(
                self.render(
                    """
                    [[images]]
                    name = "public"
                    repository = "owner/public"
                    ref = "main"
                    """
                )
            )
        finally:
            if previous is None:
                os.environ.pop("IMAGES_TOML", None)
            else:
                os.environ["IMAGES_TOML"] = previous

        self.assertEqual(
            [image["name"] for image in matrix["include"]], ["public", "private"]
        )

    def test_empty_images_toml_is_ignored(self) -> None:
        config = """
            [[images]]
            name = "public"
            repository = "owner/public"
            ref = "main"
        """

        self.assertEqual(
            json.loads(self.render(config, images_toml="")),
            {
                "include": [
                    {
                        "name": "public",
                        "repository": "owner/public",
                        "ref": "main",
                        "context": ".",
                        "dockerfile": "Dockerfile",
                        "platforms": "linux/amd64",
                    }
                ]
            },
        )
        self.assertEqual(
            json.loads(self.render(config, images_toml="  \n\t"))["include"][0]["name"],
            "public",
        )

    def test_invalid_non_empty_images_toml_is_rejected(self) -> None:
        self.assert_config_error(
            """
            [[images]]
            name = "public"
            repository = "owner/public"
            ref = "main"
            """,
            "IMAGES_TOML",
            images_toml="not valid toml =",
        )

    def test_username_and_password_must_be_paired(self) -> None:
        self.assert_config_error(
            """
            [[images]]
            name = "example"
            repository = "owner/example"
            ref = "main"
            username = "octocat"
            """,
            "provided together",
        )

    def test_credentials_env_file_uses_merged_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "images.toml"
            env_path = Path(directory) / "github-env"
            config_path.write_text(
                textwrap.dedent(
                    """
                    [[images]]
                    name = "private"
                    repository = "owner/private"
                    ref = "main"
                    """
                ),
                encoding="utf-8",
            )

            render_image_matrix.write_credentials_env(
                config_path,
                "private",
                env_path,
                '[[images]]\nname = "private"\nusername = "octocat"\npassword = "token-value"\n',
            )
            content = env_path.read_text(encoding="utf-8")

        self.assertIn("SOURCE_USERNAME<<", content)
        self.assertIn("\noctocat\n", content)
        self.assertIn("SOURCE_PASSWORD<<", content)
        self.assertIn("\ntoken-value\n", content)

    def test_duplicate_name_is_rejected(self) -> None:
        self.assert_config_error(
            """
            [[images]]
            name = "same"
            repository = "owner/first"
            ref = "main"

            [[images]]
            name = "same"
            repository = "owner/second"
            ref = "main"
            """,
            "duplicate image name",
        )

    def test_unknown_image_field_is_rejected(self) -> None:
        self.assert_config_error(
            """
            [[images]]
            name = "example"
            repository = "owner/example"
            ref = "main"
            platfroms = ["linux/amd64"]
            """,
            "unknown field 'platfroms'",
        )

    def test_empty_image_list_is_rejected(self) -> None:
        self.assert_config_error("images = []", "at least one")

    def test_invalid_repository_is_rejected(self) -> None:
        self.assert_config_error(
            """
            [[images]]
            name = "example"
            repository = "https://github.com/owner/example"
            ref = "main"
            """,
            "owner/repository format",
        )

    def test_path_traversal_is_rejected(self) -> None:
        self.assert_config_error(
            """
            [[images]]
            name = "example"
            repository = "owner/example"
            ref = "main"
            dockerfile = "../Dockerfile"
            """,
            "repository-relative path",
        )

    def test_unsupported_and_duplicate_platforms_are_rejected(self) -> None:
        base_config = """
            [[images]]
            name = "example"
            repository = "owner/example"
            ref = "main"
            platforms = {platforms}
        """
        self.assert_config_error(
            base_config.format(platforms='["linux/riscv64"]'),
            "unsupported platform",
        )
        self.assert_config_error(
            base_config.format(platforms='["linux/amd64", "linux/amd64"]'),
            "must not contain duplicates",
        )

    def test_unknown_selection_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            render_image_matrix.ConfigError, "unknown image selection 'missing'"
        ):
            self.render(
                """
                [[images]]
                name = "example"
                repository = "owner/example"
                ref = "main"
                """,
                "missing",
            )

    def test_cli_reports_configuration_errors_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "images.toml"
            config_path.write_text("images = []\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--config", str(config_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("error: configuration must contain", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
