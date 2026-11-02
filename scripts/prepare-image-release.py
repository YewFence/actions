#!/usr/bin/env -S uv run python
# USAGE arg "<target>" help="Bake target to prepare"
# USAGE arg "<directory>" help="Output directory for the release plan"
# USAGE flag "--source-only" help="Print the context owner and repository as JSON without accessing source repositories"
# USAGE flag "--checkout-repository <repository>" help="Repository of the current checkout"
# USAGE flag "--checkout-revision <revision>" help="Commit of the current checkout"
# USAGE flag "--checkout-ref <ref>" help="Full Git ref of the current checkout"

"""Resolve one Bake target into a pinned, platform-independent release plan."""

import base64
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

from dockerfile_parse import DockerfileParser

VERSION_SOURCE = "dev.yewfence.image.version-source"
VERSION = "org.opencontainers.image.version"
REVISION = "org.opencontainers.image.revision"
BASE_NAME = "org.opencontainers.image.base.name"
RELEASE_TAG = re.compile(r"v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)")


def read_remote_refs(repository: str) -> dict[str, str]:
    """Read refs without putting authentication material in command arguments."""
    environment = os.environ.copy()
    token = environment.get("GH_TOKEN") or environment.get("GITHUB_TOKEN")
    if token:
        index = int(environment.get("GIT_CONFIG_COUNT", "0"))
        authorization = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        environment[f"GIT_CONFIG_KEY_{index}"] = "http.https://github.com/.extraheader"
        environment[f"GIT_CONFIG_VALUE_{index}"] = (
            f"AUTHORIZATION: basic {authorization}"
        )
        environment["GIT_CONFIG_COUNT"] = str(index + 1)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        ["git", "ls-remote", "--quiet", f"https://github.com/{repository}.git"],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        ref: revision
        for revision, ref in (line.split() for line in result.stdout.splitlines())
    }


def parse_context(context: str) -> tuple[str, dict[str, list[str]]]:
    """Read a GitHub Git context, including legacy ref/subdir fragments."""
    url = urlsplit(context)
    if (
        url.scheme != "https"
        or url.hostname != "github.com"
        or url.username
        or url.password
    ):
        raise ValueError("release contexts must be credential-free HTTPS GitHub URLs")
    repository = url.path.strip("/").removesuffix(".git")
    if len(repository.split("/")) != 2:
        raise ValueError("release context must identify a GitHub owner/repository")
    query = parse_qs(url.query, keep_blank_values=True)
    if url.fragment:
        if query:
            raise ValueError("Git context cannot combine query and fragment selectors")
        ref, separator, subdir = url.fragment.partition(":")
        if ref:
            query["ref"] = [ref]
        if separator and subdir:
            query["subdir"] = [subdir]
    selectors = [key for key in ("branch", "tag", "ref") if key in query]
    if len(selectors) > 1 or any(len(values) != 1 for values in query.values()):
        raise ValueError("Git context must have one unambiguous ref selector")
    return repository, query


def resolve_revision(query: dict[str, list[str]], refs: dict[str, str]) -> str:
    """Resolve branches and annotated tags to the actual commit being built."""
    if "branch" in query:
        ref = "refs/heads/" + query["branch"][0]
    elif "tag" in query:
        ref = "refs/tags/" + query["tag"][0]
    else:
        ref = query.get("ref", ["HEAD"])[0]
    if re.fullmatch(r"[0-9a-f]{40}", ref):
        revision = ref
    else:
        candidates = (ref, "refs/heads/" + ref, "refs/tags/" + ref)
        resolved = [name for name in candidates if name in refs]
        if not resolved:
            raise ValueError(f"Git ref not found: {ref}")
        if len(resolved) != 1:
            raise ValueError(f"ambiguous Git ref: {ref}")
        name = resolved[0]
        revision = refs.get(name + "^{}", refs[name])
    checksum = query.get("checksum", query.get("commit", [revision]))[0]
    if not revision.startswith(checksum):
        raise ValueError("Git context checksum does not match the resolved commit")
    return revision


def pin_context(context: str, query: dict[str, list[str]], revision: str) -> str:
    """Keep context options while replacing mutable selectors with a full commit."""
    url = urlsplit(context)
    pinned = {
        key: values[0]
        for key, values in query.items()
        if key not in {"branch", "tag", "ref", "checksum", "commit"}
    }
    pinned.update(ref=revision, checksum=revision)
    return urlunsplit((url.scheme, url.netloc, url.path, urlencode(pinned), ""))


def exact_version(
    query: dict[str, list[str]], refs: dict[str, str], revision: str
) -> str | None:
    """Use a release tag only when it points at the exact source commit."""
    versions = set()
    selected_tag = query.get("tag", [None])[0]
    if selected_tag is None and "ref" in query:
        ref = query["ref"][0]
        tag = ref.removeprefix("refs/tags/")
        if "refs/tags/" + tag in refs:
            selected_tag = tag
    for ref, value in refs.items():
        if not ref.startswith("refs/tags/") or ref.endswith("^{}"):
            continue
        tag = ref.removeprefix("refs/tags/")
        if selected_tag is not None and tag != selected_tag:
            continue
        match = RELEASE_TAG.fullmatch(tag)
        if match and refs.get(ref + "^{}", value) == revision:
            versions.add(match[1])
    if len(versions) > 1:
        raise ValueError(
            "multiple release versions point at this commit; select a Git tag explicitly"
        )
    return next(iter(versions), None)


def dockerfile_version(content: str, target: dict) -> tuple[str, str]:
    """Read the final upstream image with the Dockerfile parser, including ARG defaults."""
    parser = DockerfileParser(
        fileobj=io.BytesIO(content.encode()),
        build_args={
            key: value
            for key, value in target.get("args", {}).items()
            if value is not None
        },
    )
    image = parser.baseimage
    if target.get("target"):
        final_from = [
            item["value"] for item in parser.structure if item["instruction"] == "FROM"
        ][-1]
        parts = final_from.split()
        if len(parts) < 3 or parts[-2].upper() != "AS" or parts[-1] != target["target"]:
            raise ValueError("dockerfile version source requires the final build stage")
    name = image.partition("@")[0]
    last_component = name.rsplit("/", 1)[-1]
    if ":" not in last_component:
        raise ValueError("upstream image must have an explicit version tag")
    version = last_component.rsplit(":", 1)[1]
    if not RELEASE_TAG.fullmatch(version):
        raise ValueError(f"upstream image tag is not a release version: {version}")
    return version.removeprefix("v"), image


def matches_checkout(
    repository: str,
    query: dict[str, list[str]],
    checkout_repository: str,
    checkout_revision: str,
    checkout_ref: str,
) -> bool:
    """Use the workflow checkout only when it is the source selected by the target."""
    if repository.casefold() != checkout_repository.casefold() or not checkout_revision:
        return False
    if "branch" in query:
        return checkout_ref == "refs/heads/" + query["branch"][0]
    if "tag" in query:
        return checkout_ref == "refs/tags/" + query["tag"][0]
    if "ref" in query:
        return query["ref"][0] in {checkout_ref, checkout_revision}
    return bool(checkout_ref)


def create_plan(
    definition: dict,
    target_name: str,
    refs: dict[str, str],
    *,
    dockerfile: str | None = None,
    checkout_repository: str = "",
    checkout_revision: str = "",
    checkout_ref: str = "",
) -> tuple[dict, dict]:
    """Return a self-contained Bake definition and release metadata for all platforms."""
    target = definition["target"][target_name]
    repository, query = parse_context(target["context"])
    if matches_checkout(
        repository, query, checkout_repository, checkout_revision, checkout_ref
    ):
        revision = checkout_revision
        checksum = query.get("checksum", query.get("commit", [revision]))[0]
        if not revision.startswith(checksum):
            raise ValueError(
                "checkout revision does not match the Git context checksum"
            )
    else:
        revision = resolve_revision(query, refs)
    target["context"] = pin_context(target["context"], query, revision)
    labels = target.setdefault("labels", {})
    source = labels.get(VERSION_SOURCE)
    if source == "dockerfile":
        if dockerfile is None:
            raise ValueError("Dockerfile is required for the dockerfile version source")
        version, base_image = dockerfile_version(dockerfile, target)
        labels[BASE_NAME] = base_image
    elif source is None:
        version = exact_version(query, refs, revision)
    else:
        raise ValueError(f"unsupported version source: {source}")
    labels[REVISION] = revision
    labels[VERSION] = version or ""
    image = f"ghcr.io/yewfence/{target_name}"
    tags = [f"{image}:latest"]
    if version:
        tags.append(f"{image}:{version}")
    target.pop("tags", None)
    metadata = {
        "target": target_name,
        "owner": repository.split("/", 1)[0],
        "repository": repository.split("/", 1)[1],
        "revision": revision,
        "version": version,
        "tags": tags,
        "labels": labels.copy(),
    }
    return definition, metadata


def prepare_release(
    target_name: str,
    directory: Path,
    checkout_repository: str = "",
    checkout_revision: str = "",
    checkout_ref: str = "",
    source_only: bool = False,
) -> None:
    """Resolve the configured target once and persist its build and publication inputs."""
    command = ["docker", "buildx", "bake", "--file", "docker-bake.hcl"]
    if Path("private-repo-bake.hcl").is_file():
        command.extend(["--file", "private-repo-bake.hcl"])
    command.extend(["--print", target_name])
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    definition = json.loads(result.stdout)
    target = definition["target"][target_name]
    repository, query = parse_context(target["context"])
    if source_only:
        owner, name = repository.split("/", 1)
        print(json.dumps({"owner": owner, "repository": name}))
        return
    refs = read_remote_refs(repository)
    use_checkout = matches_checkout(
        repository, query, checkout_repository, checkout_revision, checkout_ref
    )
    revision = checkout_revision if use_checkout else resolve_revision(query, refs)
    dockerfile = None
    if target.get("labels", {}).get(VERSION_SOURCE) == "dockerfile":
        if "dockerfile-inline" in target:
            dockerfile = target["dockerfile-inline"]
        else:
            path = PurePosixPath(query.get("subdir", [""])[0]) / target.get(
                "dockerfile", "Dockerfile"
            )
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Dockerfile must be inside the Git context")
            if use_checkout:
                dockerfile = Path(path).read_text(encoding="utf-8")
            else:
                result = subprocess.run(
                    [
                        "gh",
                        "api",
                        f"repos/{repository}/contents/{quote(str(path), safe='/')}?ref={revision}",
                        "-H",
                        "Accept: application/vnd.github.raw+json",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                dockerfile = result.stdout
    bake, metadata = create_plan(
        definition,
        target_name,
        refs,
        dockerfile=dockerfile,
        checkout_repository=checkout_repository,
        checkout_revision=checkout_revision,
        checkout_ref=checkout_ref,
    )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "bake.json").write_text(
        json.dumps(bake, indent=2) + "\n", encoding="utf-8"
    )
    (directory / "release.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "target": target_name,
                "version": metadata["version"],
                "revision": revision,
            }
        )
    )


def main() -> int:
    try:
        prepare_release(
            os.environ["usage_target"],
            Path(os.environ["usage_directory"]),
            os.environ.get("usage_checkout_repository", ""),
            os.environ.get("usage_checkout_revision", ""),
            os.environ.get("usage_checkout_ref", ""),
            os.environ.get("usage_source_only") == "true",
        )
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
