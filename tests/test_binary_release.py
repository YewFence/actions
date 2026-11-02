"""Verify release identity and the build-to-package boundary."""

import importlib.util
import json
import os
import tarfile
import tempfile
import unittest
from contextlib import chdir
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load_script("prepare-binary-release")
build = load_script("build-binary-release")


def prepare_fixture(directory, recipe_revision=None):
    config_directory = directory / "config"
    config_directory.mkdir()
    (config_directory / "binaries.toml").write_text(
        '[tools.josh]\n'
        'source = "https://github.com/josh-project/josh.git"\n'
        'tag = "r26.08.28"\n'
        f'revision = "{"a" * 40}"\n'
        "version_pattern = '^r(?P<major>\\d+)\\.(?P<minor>\\d+)\\.(?P<patch>\\d+)$'\n"
        'commands = ["josh", "josh-filter"]\n'
        'notes = """Unofficial prebuilt binaries of Josh.\\n\\n'
        'Upstream tag: `{source_tag}`\\n\\n'
        'Upstream commit: `{revision}`\\n\\n'
        'Commands: {commands}\\n\\n'
        'Linux GNU builds require glibc 2.36 or newer. Josh commands also need Git on PATH; `josh changes pull` needs Git 2.41 or newer."""\n'
        '[[tools.josh.platforms]]\n'
        'platform = "linux/amd64"\n'
        'target = "x86_64-unknown-linux-gnu"\n'
        'runner = "ubuntu-24.04"\n'
    )
    with chdir(config_directory):
        return prepare.prepare("josh", directory, recipe_revision)


class BinaryReleaseTests(unittest.TestCase):
    def test_calendar_tag_becomes_canonical_version_without_losing_source_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            plan = prepare_fixture(directory, "recipe-commit")
            self.assertEqual(plan["source_tag"], "r26.08.28")
            self.assertEqual(plan["version"], "26.8.28")
            self.assertEqual(plan["tag"], "josh-v26.8.28")
            self.assertEqual(plan["recipe_revision"], "recipe-commit")
            self.assertEqual(json.loads((directory / "release.json").read_text()), plan)
            self.assertIn("Distribution recipe commit: `recipe-commit`", plan["notes"])

    def test_build_pins_tag_and_packages_declared_commands_with_license(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            plan = prepare_fixture(directory)
            target = "x86_64-unknown-linux-gnu"
            output = directory / target

            def export_binaries(command, **kwargs):
                self.assertTrue(kwargs["check"])
                self.assertIn("tag=r26.08.28&checksum=" + plan["revision"], command[-1])
                self.assertIn("--network", command)
                self.assertIn("HTTPS_PROXY=http://127.0.0.1:7897", command)
                output.mkdir()
                for name in [*plan["commands"], "LICENSE"]:
                    path = output / name
                    path.write_text(name)
                    path.chmod(0o755 if name in plan["commands"] else 0o644)

            with patch.object(build.subprocess, "run", side_effect=export_binaries):
                archive = build.build(directory, target, host_proxy="http://127.0.0.1:7897")
            with tarfile.open(archive) as package:
                self.assertEqual(
                    set(package.getnames()), {"josh", "josh-filter", "LICENSE", "BUILD.json"}
                )
                self.assertEqual(json.load(package.extractfile("BUILD.json")), plan)
                self.assertTrue(package.getmember("josh").mode & os.X_OK)

    def test_notes_include_upstream_and_recipe_revisions(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            plan = prepare_fixture(directory, "recipe-commit")
            self.assertIn(f"Upstream tag: `{plan['source_tag']}`", plan["notes"])
            self.assertIn(f"Upstream commit: `{plan['revision']}`", plan["notes"])
            self.assertIn("Distribution recipe commit: `recipe-commit`", plan["notes"])

    def test_unknown_platform_fails_before_starting_docker(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            prepare_fixture(directory)
            with patch.object(build.subprocess, "run") as run:
                with self.assertRaises(StopIteration):
                    build.build(directory, "unsupported")
                run.assert_not_called()
