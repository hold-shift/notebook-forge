#!/usr/bin/env bash
# API happy-path smoke test against an imported document (M5 gate).
# Boots uvicorn on a scratch port, exercises list → get → edit → dirty →
# changes → rollback → clean, then shuts down. Non-interactive.
set -euo pipefail
cd "$(dirname "$0")/../backend"

PORT="${SMOKE_PORT:-8431}"
BASE="http://127.0.0.1:$PORT"
SLUG="${SMOKE_SLUG:-1934-1945_junior}"

uv run uvicorn notebook_forge.api:app --port "$PORT" --log-level warning &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT

for _ in $(seq 1 40); do
  curl -fsS "$BASE/api/documents" >/dev/null 2>&1 && break
  sleep 0.25
done

fail() { echo "SMOKE FAIL: $1" >&2; exit 1; }
jqpy() { uv run python -c "import json,sys; d=json.load(sys.stdin); $1"; }

echo "1. list documents"
curl -fsS "$BASE/api/documents" | jqpy "
assert len(d) >= 7, f'expected >=7 docs, got {len(d)}'
doc = next(x for x in d if x['slug'] == '$SLUG')
t = doc['targets'][0]
assert t['status'] == 'PUBLISHED', f'expected published, got {t}'
print('   ok: 7 docs, $SLUG is PUBLISHED')"

echo "2. get document"
curl -fsS "$BASE/api/documents/$SLUG" > /tmp/smoke_doc.json
jqpy "
assert d['meta']['title'], 'no title'
assert len(d['blocks']) > 10, 'no blocks'
print('   ok:', d['meta']['title'], len(d['blocks']), 'blocks')" < /tmp/smoke_doc.json

echo "3. edit a paragraph -> save"
uv run python - "$SLUG" <<'PY'
import json, sys, urllib.request
slug = sys.argv[1]
doc = json.load(open('/tmp/smoke_doc.json'))
blocks = doc['blocks']
para = next(b for b in blocks if b['type'] == 'paragraph')
para['content'][0]['text'] = 'SMOKE-EDIT ' + para['content'][0]['text']
body = json.dumps({'blocks': blocks, 'summary': 'smoke-test edit'}).encode()
req = urllib.request.Request(
    f'http://127.0.0.1:{__import__("os").environ.get("SMOKE_PORT", "8431")}/api/documents/{slug}/blocks',
    data=body, method='PUT', headers={'Content-Type': 'application/json'})
resp = json.load(urllib.request.urlopen(req))
assert resp['ok']
assert resp['targets'][0]['dirty'], 'expected dirty after edit'
print('   ok: saved, target now dirty')
PY

echo "4. change log records the edit"
curl -fsS "$BASE/api/documents/$SLUG/changes" | jqpy "
assert d[0]['kind'] == 'edit' and d[0]['summary'] == 'smoke-test edit', d[0]
print('   ok: edit logged')"

echo "5. search finds the edit"
curl -fsS "$BASE/api/search?q=SMOKE-EDIT" | jqpy "
assert d and d[0]['slug'] == '$SLUG', d
print('   ok: FTS hit')"

echo "6. rollback to the import snapshot -> clean"
SNAP=$(curl -fsS "$BASE/api/documents/$SLUG/snapshots" | jqpy "print(d[-1]['id'])")
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d "{\"snapshot_id\": $SNAP}" "$BASE/api/documents/$SLUG/rollback" | jqpy "
assert d['ok'] and not d['targets'][0]['dirty'], d
print('   ok: rolled back, clean again')"

echo "7. asset serving"
SHA=$(jqpy "
imgs = [b for b in d['blocks'] if b['type'] == 'forgeImage']
print(imgs[0]['props']['assetId'])" < /tmp/smoke_doc.json)
curl -fsS -o /tmp/smoke_asset "$BASE/api/assets/$SHA"
[ -s /tmp/smoke_asset ] || fail "asset empty"
echo "   ok: asset $SHA served ($(wc -c < /tmp/smoke_asset | tr -d ' ') bytes)"

echo "SMOKE PASS"
