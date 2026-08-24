#!/usr/bin/env bash
# agentkeel: declare the tier of the task you are about to start.
#
# Usage: tier.sh small|medium|large <slug>
#
# Writes .claude/state/agentkeel-tier.json at the top of the current worktree. Every agentkeel
# guard reads it: no declaration means no writes; small permits explicit-path commits in the tree
# you are in; medium and large require a branch that is not main; large also requires an approved
# spec at docs/specs/<slug>-spec.md before any edit outside docs/.
#
# The declaration expires (AGENTKEEL_TIER_TTL_HOURS, default 8) so yesterday's "small" cannot
# grant today's commit on main. Re-declaring is allowed and recorded; a task never grows a tier
# on its own, so the human decides whether it really did.
set -uo pipefail

usage() { echo "usage: tier.sh small|medium|large <slug>   (slug: kebab-case, e.g. json-flag)" >&2; }

SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

if [ "${1:-}" = "--selftest" ]; then
  T=$(mktemp -d 2>/dev/null || mktemp -d -t agentkeel)
  ( cd "$T" && git init -q -b main . 2>/dev/null || git init -q . ) || { echo "selftest: git init failed" >&2; exit 1; }
  ( cd "$T" && "$SELF" medium json-flag >/dev/null 2>&1 ) || { echo "selftest FAIL: declare" >&2; exit 1; }
  grep -q '"tier": "medium"' "$T/.claude/state/agentkeel-tier.json" || { echo "selftest FAIL: state" >&2; exit 1; }
  ( cd "$T" && "$SELF" huge json-flag >/dev/null 2>&1 ) && { echo "selftest FAIL: bad tier accepted" >&2; exit 1; }
  ( cd "$T" && "$SELF" small json-flag 2>&1 >/dev/null | grep -q "re-declared" ) || { echo "selftest FAIL: re-declare note" >&2; exit 1; }
  rm -rf "$T"; echo "tier.sh selftest: PASS"; exit 0
fi

TIER="${1:-}"; SLUG="${2:-}"
case "$TIER" in small|medium|large) ;; *) usage; exit 2 ;; esac
[ -n "$SLUG" ] || { usage; exit 2; }
case "$SLUG" in *[!a-z0-9-]*) echo "tier.sh: slug must be kebab-case (a-z, 0-9, -)" >&2; exit 2 ;; esac

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "tier.sh: not inside a git repository" >&2; exit 2; }
BRANCH=$(git -C "$ROOT" symbolic-ref --short HEAD 2>/dev/null || git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
TTL="${AGENTKEEL_TIER_TTL_HOURS:-8}"
STATE_DIR="$ROOT/.claude/state"
mkdir -p "$STATE_DIR"

python3 - "$STATE_DIR/agentkeel-tier.json" "$TIER" "$SLUG" "$TTL" "$BRANCH" <<'PY'
import json, os, sys, time
path, tier, slug, ttl, branch = sys.argv[1:6]
now = int(time.time())
prev = None
try:
    with open(path) as fh:
        prev = json.load(fh)
except Exception:
    prev = None
state = {"tier": tier, "slug": slug, "branch": branch, "declared_at": now,
         "expires_at": now + int(float(ttl) * 3600)}
if prev and prev.get("tier") != tier:
    state["previous"] = {"tier": prev.get("tier"), "slug": prev.get("slug"),
                         "declared_at": prev.get("declared_at")}
    sys.stderr.write(f"agentkeel: re-declared {prev.get('tier')} -> {tier}. "
                     "A task never grows a tier on its own; the human decides re-scoping.\n")
tmp = path + ".tmp"
with open(tmp, "w") as fh:
    json.dump(state, fh, indent=2, sort_keys=True)
os.replace(tmp, path)
print(f"agentkeel: tier {tier} declared for '{slug}' on branch {branch or '?'}; expires in {ttl} h")
PY
