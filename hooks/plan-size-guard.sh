#!/usr/bin/env bash
# agentkeel plan-size guard (PostToolUse, matcher Write|Edit).
#
# Plans never carry code. A plan is a table: task, files it may touch, blocked by, the check that
# proves it, and whether the check's scope fits inside those files. When a plan grows past
# 300 lines it is carrying implementation, which makes implementers into transcribers whose
# transcription then gets reviewed: the work done twice. In practice the worst case was a
# 4105-line plan for 541 lines of shell.
#
# Runs after every write to docs/plans/*plan*.md and reports the actual number back. Exit 2 with
# the message on stderr is fed to the model; the write itself has already happened.
set -uo pipefail

LIMIT="${AGENTKEEL_PLAN_LIMIT:-300}"
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

if [ "${1:-}" = "--selftest" ]; then
  T=$(mktemp -d 2>/dev/null || mktemp -d -t agentkeel); mkdir -p "$T/docs/plans" "$T/docs/specs"
  yes "task line" | head -n 301 > "$T/docs/plans/x-plan.md"
  yes "task line" | head -n 299 > "$T/docs/plans/y-plan.md"
  yes "task line" | head -n 900 > "$T/docs/specs/z-spec.md"
  fail=0
  printf '{"tool_name":"Write","tool_input":{"file_path":"%s"}}' "$T/docs/plans/x-plan.md" | "$SELF" >/dev/null 2>&1; [ $? -eq 2 ] || { echo "selftest FAIL: 301 lines allowed" >&2; fail=1; }
  printf '{"tool_name":"Write","tool_input":{"file_path":"%s"}}' "$T/docs/plans/y-plan.md" | "$SELF" >/dev/null 2>&1; [ $? -eq 0 ] || { echo "selftest FAIL: 299 lines blocked" >&2; fail=1; }
  printf '{"tool_name":"Write","tool_input":{"file_path":"%s"}}' "$T/docs/specs/z-spec.md" | "$SELF" >/dev/null 2>&1; [ $? -eq 0 ] || { echo "selftest FAIL: spec treated as plan" >&2; fail=1; }
  printf 'not json' | "$SELF" >/dev/null 2>&1; [ $? -eq 0 ] || { echo "selftest FAIL: bad input blocked" >&2; fail=1; }
  rm -rf "$T"
  [ $fail -eq 0 ] && echo "plan-size-guard selftest: PASS"
  exit $fail
fi

INPUT=$(cat)
FILE=$(printf '%s' "$INPUT" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))
except Exception: print("")' 2>/dev/null)

case "$FILE" in
  */docs/plans/*plan*.md) ;;
  *) exit 0 ;;
esac
[ -f "$FILE" ] || exit 0

LINES=$(wc -l < "$FILE" | tr -d ' ')
[ "$LINES" -gt "$LIMIT" ] || exit 0

cat >&2 <<MSG
PLAN SIZE GUARD: $(basename "$FILE") is now $LINES lines; the limit is $LIMIT.

A plan this long is carrying code. Plans never carry code: a plan is the task table (task, files
it may touch, blocked by, the check that proves it, and whether the check's scope fits inside
those files). Implementers do the implementing; a plan that transcribes it makes the work happen
twice, once in the plan and once in review of the transcription.

Cut it to the table. If the deliverable is small enough that the plan would have to carry the
code, there is no plan: go straight to the task list and implement with the per-task review.
Gate the plan ONCE; do not re-gate a revised plan.
MSG
exit 2
