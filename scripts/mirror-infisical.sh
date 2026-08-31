#!/usr/bin/env bash
# Mirror an upstream repository's main branch and tags to a private target
# repository, then rebase the target's custom branch onto the updated main.
#
# Every mirror ref keeps the upstream SHA: pushes are fast-forward or
# lease-protected forced updates, never unconditional rewrites. On the first
# run the target branch is seeded with the full upstream history; later runs
# use the target itself as an object cache and only fetch the upstream delta.
#
# Required environment:
#   SOURCE_REPO               Upstream repository URL (HTTPS or local path).
#   INFISICAL_MIRROR_URL      Mirror destination repository URL (HTTPS or
#                              local path).
#   INFISICAL_MIRROR_USERNAME / INFISICAL_MIRROR_TOKEN
#                              HTTPS credentials for the destination.
#                              Required when INFISICAL_MIRROR_URL is HTTP(S),
#                              ignored otherwise.
#
# Optional environment:
#   SOURCE_BRANCH             Upstream branch to mirror. Defaults to main.
#   INFISICAL_MIRROR_BRANCH   Destination branch name. Defaults to main.
#   CUSTOM_BRANCH             Branch holding maintainer commits, rebased onto the
#                              updated main. Defaults to custom. A missing branch
#                              is fine and simply skipped.
#   GIT_USER_NAME / GIT_USER_EMAIL
#                              Identity used when git writes commits (e.g. during
#                              a rebase). Defaults to github-actions[bot].
set -euo pipefail

SOURCE_REPO="${SOURCE_REPO:?missing SOURCE_REPO}"
SOURCE_BRANCH="${SOURCE_BRANCH:-main}"
INFISICAL_MIRROR_URL="${INFISICAL_MIRROR_URL:?missing INFISICAL_MIRROR_URL}"
INFISICAL_MIRROR_BRANCH="${INFISICAL_MIRROR_BRANCH:-main}"
INFISICAL_MIRROR_USERNAME="${INFISICAL_MIRROR_USERNAME:-}"
INFISICAL_MIRROR_TOKEN="${INFISICAL_MIRROR_TOKEN:-}"
CUSTOM_BRANCH="${CUSTOM_BRANCH:-custom}"
GIT_USER_NAME="${GIT_USER_NAME:-github-actions[bot]}"
GIT_USER_EMAIL="${GIT_USER_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"

if [[ "$INFISICAL_MIRROR_URL" == http://* || "$INFISICAL_MIRROR_URL" == https://* ]]; then
  : "${INFISICAL_MIRROR_USERNAME:?missing INFISICAL_MIRROR_USERNAME}"
  : "${INFISICAL_MIRROR_TOKEN:?missing INFISICAL_MIRROR_TOKEN}"
  remote="${INFISICAL_MIRROR_URL#https://}"
  remote="${remote#http://}"
  host="${remote%%/*}"
  if [[ "$host" == "$remote" ]]; then
    echo "INFISICAL_MIRROR_URL must include a host and repository path" >&2
    exit 1
  fi
  git config --global credential.helper store
  printf 'protocol=https\nhost=%s\nusername=%s\npassword=%s\n\n' \
    "$host" "$INFISICAL_MIRROR_USERNAME" "$INFISICAL_MIRROR_TOKEN" | git credential approve
fi

work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT

target_tip="$(git ls-remote "$INFISICAL_MIRROR_URL" "refs/heads/$INFISICAL_MIRROR_BRANCH" | cut -f1)"
custom_tip="$(git ls-remote "$INFISICAL_MIRROR_URL" "refs/heads/$CUSTOM_BRANCH" | cut -f1)"

if [[ -z "$target_tip" ]]; then
  # First run: seed the target with the full main branch and all tags.
  echo "Seeding $INFISICAL_MIRROR_BRANCH and tags from $SOURCE_REPO."
  git clone --branch "$SOURCE_BRANCH" --single-branch "$SOURCE_REPO" "$work/source"
  git -C "$work/source" fetch --tags origin
  git -C "$work/source" push "$INFISICAL_MIRROR_URL" "HEAD:refs/heads/$INFISICAL_MIRROR_BRANCH"
  git -C "$work/source" push --force "$INFISICAL_MIRROR_URL" --tags
  if [[ -z "$custom_tip" ]]; then
    echo "custom branch ($CUSTOM_BRANCH) does not exist yet; skipping."
  fi
  exit 0
fi

# Incremental run: clone the target as an object cache, fetch the upstream
# delta, update the mirror, then rebase the custom branch onto the new main.
git clone --filter=blob:none --branch "$INFISICAL_MIRROR_BRANCH" --single-branch \
  "$INFISICAL_MIRROR_URL" "$work/cache"
git -C "$work/cache" config user.name "$GIT_USER_NAME"
git -C "$work/cache" config user.email "$GIT_USER_EMAIL"
# Replayed commits must never be signed with whatever key the runner has.
git -C "$work/cache" config commit.gpgsign false
git -C "$work/cache" config tag.gpgsign false
git -C "$work/cache" remote add upstream "$SOURCE_REPO"

git -C "$work/cache" fetch upstream "$SOURCE_BRANCH"
new_tip="$(git -C "$work/cache" rev-parse FETCH_HEAD)"
git -C "$work/cache" fetch upstream '+refs/tags/*:refs/tags/*'

if [[ "$new_tip" != "$target_tip" ]]; then
  git -C "$work/cache" push \
    --force-with-lease="refs/heads/$INFISICAL_MIRROR_BRANCH:$target_tip" \
    "$INFISICAL_MIRROR_URL" "$new_tip:refs/heads/$INFISICAL_MIRROR_BRANCH"
  echo "Updated $INFISICAL_MIRROR_BRANCH: ${target_tip:0:12} -> ${new_tip:0:12}"
else
  echo "$INFISICAL_MIRROR_BRANCH is already up to date at ${new_tip:0:12}."
fi
git -C "$work/cache" push --force "$INFISICAL_MIRROR_URL" --tags

if [[ -z "$custom_tip" ]]; then
  echo "custom branch ($CUSTOM_BRANCH) does not exist yet; skipping."
  exit 0
fi

git -C "$work/cache" fetch origin "$CUSTOM_BRANCH"
custom_sha="$(git -C "$work/cache" rev-parse FETCH_HEAD)"
if ! fork="$(git -C "$work/cache" merge-base "$custom_sha" "$new_tip")"; then
  echo "error: $CUSTOM_BRANCH and $INFISICAL_MIRROR_BRANCH no longer share history;" >&2
  echo "upstream likely rewrote its history. main and tags are mirrored, but the" >&2
  echo "custom branch was left untouched and must be rebased manually." >&2
  exit 1
fi
if [[ "$fork" == "$new_tip" ]]; then
  echo "$CUSTOM_BRANCH is already rebased onto the latest $INFISICAL_MIRROR_BRANCH; skipping."
  exit 0
fi

git -C "$work/cache" checkout -B custom "$custom_sha"
if ! git -C "$work/cache" rebase --onto "$new_tip" "$fork"; then
  git -C "$work/cache" rebase --abort || true
  echo "error: rebasing $CUSTOM_BRANCH onto $INFISICAL_MIRROR_BRANCH conflicted." >&2
  echo "main and tags are mirrored; the custom branch was left untouched and" >&2
  echo "must be rebased manually." >&2
  exit 1
fi
git -C "$work/cache" push \
  --force-with-lease="refs/heads/$CUSTOM_BRANCH:$custom_tip" \
  "$INFISICAL_MIRROR_URL" "custom:refs/heads/$CUSTOM_BRANCH"
echo "Rebased $CUSTOM_BRANCH onto $INFISICAL_MIRROR_BRANCH and pushed."
