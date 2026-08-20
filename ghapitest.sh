PR=7259
REPO=rhinstaller/anaconda

eval $(gh api repos/$REPO/pulls/$PR --jq '"HEAD_OWNER=\(.head.repo.owner.login) HEAD_REPO=\(.head.repo.name) SHA=\(.head.sha)"')

echo "Head repo: $HEAD_OWNER/$HEAD_REPO  SHA: $SHA"

echo ""
echo "=== Force-push events ==="
gh api "repos/$REPO/issues/$PR/events" \
  --paginate --jq '.[] | select(.event == "head_ref_force_pushed") | {event, created_at}'

echo ""
echo "=== Timeline: commits and pushes relative to comments ==="
gh api "repos/$REPO/issues/$PR/timeline" \
  --paginate --jq '.[] | select(.event == "committed" or .event == "commented" or .event == "head_ref_force_pushed") | {event, created_at, sha: (.sha // null), body: (.body // null | if . then .[0:80] else null end)}'
