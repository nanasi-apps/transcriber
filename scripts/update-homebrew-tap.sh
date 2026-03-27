#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAP_REPO="${TAP_REPO:-nanasi-apps/homebrew-tap}"
TAP_BRANCH="${TAP_BRANCH:-main}"
TAP_CASK_PATH="${TAP_CASK_PATH:-Casks/transcriber.rb}"
SOURCE_REPOSITORY="${SOURCE_REPOSITORY:-${GITHUB_REPOSITORY:-}}"
WORKTREE=""

error() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  if [ -n "$WORKTREE" ] && [ -d "$WORKTREE" ] && [ "${KEEP_TAP_WORKTREE:-0}" != "1" ]; then
    rm -rf "$WORKTREE"
  fi
}

trap cleanup EXIT

[ -n "${CASK_VERSION:-}" ] || error "CASK_VERSION is required"
[ -n "${CASK_SHA256:-}" ] || error "CASK_SHA256 is required"
[ -n "${CASK_ARTIFACT:-}" ] || error "CASK_ARTIFACT is required"
[ -n "$SOURCE_REPOSITORY" ] || error "SOURCE_REPOSITORY or GITHUB_REPOSITORY is required"

WORKTREE="${TAP_WORKTREE:-$(mktemp -d)}"

if [ "${DRY_RUN:-0}" = "1" ]; then
  mkdir -p "$WORKTREE"
else
  [ -n "${TAP_GITHUB_TOKEN:-}" ] || error "TAP_GITHUB_TOKEN is required"
  git clone --depth 1 --branch "$TAP_BRANCH" "https://x-access-token:${TAP_GITHUB_TOKEN}@github.com/${TAP_REPO}.git" "$WORKTREE"
fi

node "$ROOT/scripts/render-homebrew-cask.mjs" \
  --version "$CASK_VERSION" \
  --sha256 "$CASK_SHA256" \
  --repository "$SOURCE_REPOSITORY" \
  --artifact "$CASK_ARTIFACT" \
  --output "$WORKTREE/$TAP_CASK_PATH"

if [ "${DRY_RUN:-0}" = "1" ]; then
  printf 'Rendered %s\n' "$WORKTREE/$TAP_CASK_PATH"
  exit 0
fi

git -C "$WORKTREE" add "$TAP_CASK_PATH"

if git -C "$WORKTREE" diff --cached --quiet; then
  printf 'Homebrew tap is already up to date.\n'
  exit 0
fi

git -C "$WORKTREE" \
  -c user.name='github-actions[bot]' \
  -c user.email='41898282+github-actions[bot]@users.noreply.github.com' \
  commit -m "transcriber ${CASK_VERSION}"
git -C "$WORKTREE" push origin "HEAD:${TAP_BRANCH}"
