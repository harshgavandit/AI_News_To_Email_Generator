#!/usr/bin/env bash
# Open one tracking issue per failure kind, or comment on the open one, so a broken
# release is visible in the repository (and notifies watchers) rather than only in logs.
# Usage: report-incident.sh "<title>" <revision> <run-url>
set -euo pipefail
title="$1"
revision="$2"
run_url="$3"
label="release-incident"
gh label create "$label" --repo "$GITHUB_REPOSITORY" --color B60205 \
  --description "Automatic report of a failed main build or production smoke" 2>/dev/null || true
body=$(printf 'Revision `%s` · [workflow run](%s)\n\nFollow docs/RELEASE-FLOW.md (Rollback). Close this issue once production serves a verified revision again.' \
  "$revision" "$run_url")
existing=$(gh issue list --repo "$GITHUB_REPOSITORY" --state open --label "$label" --search "in:title \"$title\"" \
  --json number --jq '.[0].number // empty')
if [[ -n "$existing" ]]; then
  gh issue comment "$existing" --repo "$GITHUB_REPOSITORY" --body "$body"
  echo "Updated incident #$existing" >> "$GITHUB_STEP_SUMMARY"
else
  url=$(gh issue create --repo "$GITHUB_REPOSITORY" --title "$title" --label "$label" --body "$body")
  echo "Opened $url" >> "$GITHUB_STEP_SUMMARY"
fi
