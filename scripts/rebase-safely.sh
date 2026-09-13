#!/usr/bin/env bash
# Rebase onto origin/main without ever merging generated output.
#
# public/ is build output. Merging it is what pushed git conflict markers to
# production once already — so conflicts there are resolved by deleting the
# directory and rebuilding from source, never by picking a side.
#
# The build's output is captured rather than discarded: this script refuses to
# continue when verify fails, and a guard whose failure you can't diagnose is
# only half a guard.
set -uo pipefail
cd "$(dirname "$0")/.."

LOG=$(mktemp -t run206-build.XXXXXX)
git fetch -q origin

BEHIND=$(git rev-list --count HEAD..origin/main)
echo "behind origin/main by $BEHIND commit(s)"

REBASED=no
if [ "$BEHIND" != "0" ]; then
  git rebase origin/main >/dev/null 2>&1
  if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then
    # resolve source conflicts only; generated files are regenerated below
    git diff --name-only --diff-filter=U | grep -v '^public/' | xargs -r git checkout --theirs
    git diff --name-only --diff-filter=U | xargs -r git add
    GIT_EDITOR=true git rebase --continue >/dev/null 2>&1 || {
      echo "FAILED: rebase could not continue — resolve by hand"; exit 1; }
  fi
  REBASED=yes
fi

# Only regenerate when a rebase actually touched things, or when public/ is
# missing. A full build takes minutes (Race Roster is crawled at their required
# 5s delay), so rebuilding a known-good public/ for nothing just burns time —
# and an earlier version of this script destroyed a good build doing exactly
# that before being killed by a shell timeout.
if [ "$REBASED" = "yes" ] || [ ! -f public/events.json ]; then
  rm -rf public
  if ! python3 scripts/build.py >"$LOG" 2>&1; then
    echo "FAILED: build errored. Last lines:"; tail -15 "$LOG"; exit 1
  fi
  tail -3 "$LOG"
else
  echo "no rebase and public/ is intact — reusing the existing build"
fi

git show origin/main:public/events.json > /tmp/run206-baseline.json 2>/dev/null || true
if ! python3 scripts/verify.py --baseline /tmp/run206-baseline.json; then
  echo "FAILED: verify refused to publish — nothing pushed"; exit 1
fi

git add -A
git diff --staged --quiet || git commit -q -m "build: regenerate from source"
echo "ready to push: $(git rev-list --count origin/main..HEAD) commit(s)"
