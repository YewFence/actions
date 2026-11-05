import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load_script("prepare_image_release", "prepare-image-release.py")
publish = load_script("publish_image_manifest", "publish-image-manifest.py")
REVISION = hashlib.sha1(b"source commit").hexdigest()
OLD_REVISION = hashlib.sha1(b"previous commit").hexdigest()
TAG_OBJECT = hashlib.sha1(b"annotated tag object").hexdigest()


class ImageReleaseTests(unittest.TestCase):
    def definition(self, context=None, source=None):
        target = {
            "context": context
            or "https://github.com/example/app.git?branch=main&subdir=container",
            "dockerfile": "Dockerfile",
            "platforms": ["linux/amd64", "linux/arm64"],
            "labels": {
                "org.opencontainers.image.source": "https://github.com/example/app"
            },
        }
        if source:
            target["labels"][prepare.VERSION_SOURCE] = source
        return {"group": {"default": {"targets": ["app"]}}, "target": {"app": target}}

    def test_derived_image_gets_upstream_tag_and_revision_labels(self):
        definition = self.definition(source="dockerfile")
        bake, metadata = prepare.create_plan(
            definition,
            "app",
            {"refs/heads/main": REVISION},
            dockerfile="FROM alpine:3.24 AS tools\nFROM example/upstream:2.1.2@sha256:abc AS final\n",
        )
        self.assertEqual(
            metadata["tags"],
            ["ghcr.io/yewfence/app:latest", "ghcr.io/yewfence/app:2.1.2"],
        )
        self.assertEqual(metadata["owner"], "example")
        self.assertEqual(metadata["repository"], "app")
        self.assertEqual(metadata["labels"][prepare.VERSION], "2.1.2")
        self.assertEqual(metadata["labels"][prepare.REVISION], REVISION)
        self.assertEqual(
            metadata["labels"][prepare.BASE_NAME], "example/upstream:2.1.2@sha256:abc"
        )
        target = bake["target"]["app"]
        self.assertEqual(target["platforms"], ["linux/amd64", "linux/arm64"])
        self.assertEqual(
            target["labels"]["org.opencontainers.image.source"],
            "https://github.com/example/app",
        )
        self.assertEqual(
            parse_qs(urlsplit(target["context"]).query),
            {
                "ref": [REVISION],
                "checksum": [REVISION],
                "subdir": ["container"],
            },
        )

    def test_current_checkout_commit_wins_over_remote_branch(self):
        bake, metadata = prepare.create_plan(
            self.definition(source="dockerfile"),
            "app",
            {"refs/heads/main": OLD_REVISION},
            dockerfile="FROM example/upstream:1.2.3\n",
            checkout_repository="Example/App",
            checkout_revision=REVISION,
            checkout_ref="refs/heads/main",
        )
        self.assertEqual(metadata["revision"], REVISION)
        self.assertEqual(
            parse_qs(urlsplit(bake["target"]["app"]["context"]).query)["ref"],
            [REVISION],
        )

    def test_other_branch_in_same_repository_keeps_its_own_revision(self):
        _, metadata = prepare.create_plan(
            self.definition("https://github.com/example/app.git?branch=custom"),
            "app",
            {"refs/heads/custom": OLD_REVISION},
            checkout_repository="example/app",
            checkout_revision=REVISION,
            checkout_ref="refs/heads/main",
        )
        self.assertEqual(metadata["revision"], OLD_REVISION)

    def test_other_repository_does_not_use_orchestrator_revision(self):
        _, metadata = prepare.create_plan(
            self.definition(),
            "app",
            {"refs/heads/main": REVISION},
            checkout_repository="example/orchestrator",
            checkout_revision=OLD_REVISION,
        )
        self.assertEqual(metadata["revision"], REVISION)

    def test_branch_ahead_of_release_only_gets_latest(self):
        definition = self.definition()
        definition["target"]["app"]["labels"][prepare.VERSION] = "stale"
        _, metadata = prepare.create_plan(
            definition,
            "app",
            {
                "refs/heads/main": REVISION,
                "refs/tags/v1.2.3": OLD_REVISION,
            },
        )
        self.assertEqual(metadata["tags"], ["ghcr.io/yewfence/app:latest"])
        self.assertIsNone(metadata["version"])
        self.assertEqual(metadata["labels"][prepare.VERSION], "")
        self.assertEqual(metadata["labels"][prepare.REVISION], REVISION)

    def test_exact_lightweight_release_tag_gets_version(self):
        _, metadata = prepare.create_plan(
            self.definition(),
            "app",
            {
                "refs/heads/main": REVISION,
                "refs/tags/v1.2.3": REVISION,
            },
        )
        self.assertEqual(metadata["version"], "1.2.3")
        self.assertEqual(metadata["tags"][-1], "ghcr.io/yewfence/app:1.2.3")

    def test_annotated_tag_uses_peeled_commit(self):
        definition = self.definition("https://github.com/example/app.git?tag=v1.2.3")
        _, metadata = prepare.create_plan(
            definition,
            "app",
            {
                "refs/tags/v1.2.3": TAG_OBJECT,
                "refs/tags/v1.2.3^{}": REVISION,
            },
        )
        self.assertEqual(metadata["revision"], REVISION)
        self.assertEqual(metadata["version"], "1.2.3")

    def test_branch_at_annotated_tag_object_does_not_claim_release_version(self):
        _, metadata = prepare.create_plan(
            self.definition(),
            "app",
            {
                "refs/heads/main": REVISION,
                "refs/tags/v1.2.3": REVISION,
                "refs/tags/v1.2.3^{}": OLD_REVISION,
            },
        )
        self.assertIsNone(metadata["version"])

    def test_multiple_distinct_release_versions_require_explicit_tag(self):
        refs = {
            "refs/heads/main": REVISION,
            "refs/tags/v1.2.3": REVISION,
            "refs/tags/v1.2.4": REVISION,
        }
        with self.assertRaisesRegex(ValueError, "multiple release versions"):
            prepare.create_plan(self.definition(), "app", refs)
        _, metadata = prepare.create_plan(
            self.definition("https://github.com/example/app.git?tag=v1.2.3"),
            "app",
            refs,
        )
        self.assertEqual(metadata["version"], "1.2.3")
        _, metadata = prepare.create_plan(
            self.definition("https://github.com/example/app.git?ref=refs/tags/v1.2.4"),
            "app",
            refs,
        )
        self.assertEqual(metadata["version"], "1.2.4")

    def test_full_commit_ref_and_legacy_subdir_are_supported(self):
        context = f"https://github.com/example/app.git#{REVISION}:container"
        _, query = prepare.parse_context(context)
        self.assertEqual(prepare.resolve_revision(query, {}), REVISION)
        pinned = prepare.pin_context(context, query, REVISION)
        self.assertEqual(parse_qs(urlsplit(pinned).query)["subdir"], ["container"])
        self.assertEqual(urlsplit(pinned).fragment, "")

    def test_default_branch_context_uses_head(self):
        _, metadata = prepare.create_plan(
            self.definition("https://github.com/example/app.git"),
            "app",
            {"HEAD": REVISION},
        )
        self.assertEqual(metadata["revision"], REVISION)

    def test_checksum_mismatch_fails_before_build(self):
        query = {"branch": ["main"], "checksum": [OLD_REVISION]}
        with self.assertRaisesRegex(ValueError, "checksum"):
            prepare.resolve_revision(query, {"refs/heads/main": REVISION})
        with self.assertRaisesRegex(ValueError, "checksum"):
            prepare.create_plan(
                self.definition(
                    f"https://github.com/example/app.git?checksum={OLD_REVISION}"
                ),
                "app",
                {},
                checkout_repository="example/app",
                checkout_revision=REVISION,
                checkout_ref="refs/heads/main",
            )

    def test_ambiguous_and_missing_refs_fail(self):
        with self.assertRaisesRegex(ValueError, "ambiguous Git ref"):
            prepare.resolve_revision(
                {"ref": ["release"]},
                {
                    "refs/heads/release": REVISION,
                    "refs/tags/release": OLD_REVISION,
                },
            )
        with self.assertRaisesRegex(ValueError, "Git ref not found"):
            prepare.resolve_revision({"branch": ["missing"]}, {})

    def test_unsafe_or_ambiguous_contexts_are_rejected(self):
        for context in (
            "https://user:secret@github.com/example/app.git",
            "https://example.org/owner/app.git",
            "https://github.com/example/app.git?branch=main&tag=v1.0.0",
            "https://github.com/example/app.git?branch=main&branch=other",
            "https://github.com/example/app.git?branch=main#other",
        ):
            with self.subTest(context=context), self.assertRaises(ValueError):
                prepare.parse_context(context)

    def test_dockerfile_parser_expands_build_arguments(self):
        content = "ARG APP_VERSION=1.2.3\nFROM alpine AS tools\nFROM example/app:${APP_VERSION} AS final\n"
        self.assertEqual(
            prepare.dockerfile_version(content, {"args": {"APP_VERSION": "1.3.0"}}),
            ("1.3.0", "example/app:1.3.0"),
        )

    def test_explicit_final_stage_name_is_respected(self):
        self.assertEqual(
            prepare.dockerfile_version(
                "FROM alpine AS tools\nFROM example/app:1.2.3 as runtime\n",
                {"target": "runtime"},
            ),
            ("1.2.3", "example/app:1.2.3"),
        )

    def test_version_source_stage_reads_that_stage_image(self):
        self.assertEqual(
            prepare.dockerfile_version(
                "FROM example/app:1.2.3 AS base\nRUN nothing\nFROM alpine:3.20\nCOPY --from=base /app /app\n",
                {"version_source_stage": "base"},
            ),
            ("1.2.3", "example/app:1.2.3"),
        )

    def test_two_segment_release_tags_are_accepted(self):
        self.assertEqual(
            prepare.dockerfile_version(
                "FROM postgres:18.6 AS base\nFROM base\n",
                {"version_source_stage": "base"},
            )[0],
            "18.6",
        )
        self.assertEqual(prepare.RELEASE_TAG.fullmatch("3.24").group(1), "3.24")
        self.assertEqual(prepare.RELEASE_TAG.fullmatch("1.2.3-1.pgdg12+1"), None)

    def test_version_source_stage_must_exist_and_be_versioned(self):
        with self.assertRaisesRegex(ValueError, "version source stage not found"):
            prepare.dockerfile_version("FROM example/app:1.2.3 AS base\n", {"version_source_stage": "missing"})
        with self.assertRaisesRegex(ValueError, "explicit version tag"):
            prepare.dockerfile_version(
                "FROM scratch AS tools\nFROM example/app:1.2.3 AS base\n",
                {"version_source_stage": "tools"},
            )

    def test_nonversioned_base_image_is_not_mislabeled(self):
        for image in (
            "example/app:latest",
            "example/app:main",
            "localhost:5000/app",
            "scratch",
        ):
            with self.subTest(image=image), self.assertRaises(ValueError):
                prepare.dockerfile_version(f"FROM {image}\n", {})
        with self.assertRaisesRegex(ValueError, "final build stage"):
            prepare.dockerfile_version("FROM example/app:1.2.3\n", {"target": "tools"})

    def test_authentication_stays_out_of_process_arguments(self):
        with (
            patch.dict(
                os.environ,
                {
                    "GH_TOKEN": "test-token",
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "existing.key",
                    "GIT_CONFIG_VALUE_0": "value",
                },
            ),
            patch.object(prepare.subprocess, "run") as run,
        ):
            run.return_value.stdout = f"{REVISION}\trefs/heads/main\n"
            self.assertEqual(
                prepare.read_remote_refs("example/app"), {"refs/heads/main": REVISION}
            )
        args, kwargs = run.call_args
        self.assertNotIn("test-token", " ".join(args[0]))
        self.assertEqual(kwargs["env"]["GIT_CONFIG_COUNT"], "2")
        self.assertEqual(kwargs["env"]["GIT_CONFIG_KEY_0"], "existing.key")
        self.assertEqual(
            kwargs["env"]["GIT_CONFIG_KEY_1"], "http.https://github.com/.extraheader"
        )
        self.assertTrue(
            kwargs["env"]["GIT_CONFIG_VALUE_1"].startswith("AUTHORIZATION: basic ")
        )

    def test_source_probe_does_not_read_source_or_write_plan(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(prepare.subprocess, "run") as run,
            patch.object(prepare, "read_remote_refs") as refs,
            patch("builtins.print") as output,
        ):
            run.return_value.stdout = json.dumps(self.definition())
            prepare.prepare_release(
                "app", Path(temporary) / "release", source_only=True
            )
            refs.assert_not_called()
            output.assert_called_once()
            self.assertEqual(
                json.loads(output.call_args.args[0]),
                {"owner": "example", "repository": "app"},
            )
            self.assertFalse((Path(temporary) / "release").exists())

    def test_prepare_writes_bake_and_metadata_from_one_resolution(self):
        definition = self.definition(source="dockerfile")
        definition["target"]["app"]["dockerfile-inline"] = (
            "FROM example/upstream:2.1.2\n"
        )
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(prepare.subprocess, "run") as run,
            patch.object(
                prepare, "read_remote_refs", return_value={"refs/heads/main": REVISION}
            ) as refs,
        ):
            run.return_value.stdout = json.dumps(definition)
            directory = Path(temporary)
            prepare.prepare_release("app", directory)
            refs.assert_called_once_with("example/app")
            bake = json.loads((directory / "bake.json").read_text())
            metadata = json.loads((directory / "release.json").read_text())
            self.assertEqual(
                metadata["tags"],
                ["ghcr.io/yewfence/app:latest", "ghcr.io/yewfence/app:2.1.2"],
            )
            self.assertNotIn("tags", bake["target"]["app"])
            self.assertEqual(
                bake["target"]["app"]["labels"][prepare.REVISION], metadata["revision"]
            )
            self.assertNotIn("secret", bake["target"]["app"])

    def test_derived_version_changes_with_dockerfile_without_a_second_setting(self):
        for version in ("1.2.3", "1.2.4", "2.0.0-rc.1"):
            with self.subTest(version=version):
                _, metadata = prepare.create_plan(
                    self.definition(source="dockerfile"),
                    "app",
                    {"refs/heads/main": REVISION},
                    dockerfile=f"FROM example/upstream:{version}\n",
                )
                self.assertEqual(metadata["version"], version)
                self.assertEqual(
                    metadata["tags"][-1], f"ghcr.io/yewfence/app:{version}"
                )


class ManifestTests(unittest.TestCase):
    def test_all_tags_share_both_platform_digests_and_annotations(self):
        _, metadata = prepare.create_plan(
            ImageReleaseTests().definition(source="dockerfile"),
            "app",
            {"refs/heads/main": REVISION},
            dockerfile="FROM example/app:1.2.3\n",
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "release.json").write_text(json.dumps(metadata))
            (directory / "digests").mkdir()
            digests = [
                hashlib.sha256(platform.encode()).hexdigest()
                for platform in ("amd64", "arm64")
            ]
            for digest in digests:
                (directory / "digests" / digest).touch()
            command = publish.manifest_command(directory)
        self.assertEqual(command[:4], ["docker", "buildx", "imagetools", "create"])
        self.assertEqual(
            [command[i + 1] for i, value in enumerate(command) if value == "--tag"],
            metadata["tags"],
        )
        self.assertEqual(
            command[-2:],
            [f"ghcr.io/yewfence/app@sha256:{digest}" for digest in sorted(digests)],
        )
        self.assertIn(f"index:{prepare.REVISION}={REVISION}", command)
        self.assertIn(f"index:{prepare.VERSION}=1.2.3", command)

    def test_empty_or_invalid_digests_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "release.json").write_text(
                json.dumps({"target": "app", "tags": [], "labels": {}})
            )
            (directory / "digests").mkdir()
            with self.assertRaisesRegex(ValueError, "no platform digests"):
                publish.manifest_command(directory)
            (directory / "digests" / "unexpected.json").touch()
            with self.assertRaisesRegex(ValueError, "invalid platform digest"):
                publish.manifest_command(directory)

    def test_dry_run_does_not_contact_registry(self):
        with (
            patch.dict(
                os.environ, {"usage_directory": "/tmp/release", "usage_dry_run": "true"}
            ),
            patch.object(
                publish, "manifest_command", return_value=["docker", "buildx"]
            ) as command,
            patch.object(publish.subprocess, "run") as run,
            patch("builtins.print") as output,
        ):
            self.assertEqual(publish.main(), 0)
            run.assert_not_called()
            command.assert_called_once_with(Path("/tmp/release"))
            output.assert_called_once_with(json.dumps(["docker", "buildx"]))


if __name__ == "__main__":
    unittest.main()
