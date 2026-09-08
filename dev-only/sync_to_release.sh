#!/usr/bin/env bash
# Squash-syncs dev's current tree onto release, dropping dev-only paths, and tags the result.
# Run from dev, on a clean tree, with the version already decided.
#
# Usage: dev-only/sync_to_release.sh <tag>   e.g. dev-only/sync_to_release.sh v1.2.0
set -euo pipefail

TAG="${1:?Usage: sync_to_release.sh <tag>}"

# Pathspecs excluded from release. Glob patterns need '**' magic enabled.
EXCLUDES=(
  ':(glob,exclude)**/tests/**'
  ':(exclude)docs/adr'
  ':(exclude)docs/plans'
  ':(exclude)CONTEXT.md'
  ':(exclude)dev-only'
)

DEV_BRANCH="$(git branch --show-current)"
if [ "$DEV_BRANCH" = "release" ] || [ -z "$DEV_BRANCH" ]; then
  echo "run this from dev (currently on '${DEV_BRANCH:-detached HEAD}')" >&2
  exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "dev has uncommitted changes to tracked files, commit or stash first" >&2
  exit 1
fi
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "tag $TAG already exists" >&2
  exit 1
fi

DEV_SHA="$(git rev-parse HEAD)"

# Stash untracked files too: they'd otherwise sit in the shared working tree
# across the branch switch and get swept into the release commit by `git add -A`.
STASHED=0
if [ -n "$(git status --porcelain | grep '^??')" ]; then
  git stash push -u -m "sync_to_release: untracked WIP set aside during release sync"
  STASHED=1
fi
cleanup() {
  git checkout "$DEV_BRANCH" >/dev/null 2>&1 || true
  if [ "$STASHED" = 1 ]; then
    git stash pop
  fi
}
trap cleanup EXIT

if git show-ref --verify --quiet refs/heads/release; then
  git checkout release
else
  git checkout --orphan release
  git rm -rqf --ignore-unmatch -- .
  git commit --allow-empty -m "Initialise release branch"
fi
git rm -rq --ignore-unmatch -- .
git checkout "$DEV_BRANCH" -- . "${EXCLUDES[@]}"
git add -A
git commit -m "Release ${TAG} (from ${DEV_BRANCH}@${DEV_SHA:0:12})"
git tag -a "$TAG" -m "Release ${TAG} (from ${DEV_BRANCH}@${DEV_SHA:0:12})"

echo "release branch updated and tagged $TAG. Review with 'git show release --stat', then:"
echo "  git push origin release $DEV_BRANCH $TAG"
