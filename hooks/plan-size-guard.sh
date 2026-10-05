#!/usr/bin/env bash
# agentkeel plan-size guard (PostToolUse, matcher Write|Edit).
#
# Plans never carry code. A plan is a table: task, files it may touch, blocked by, the check that
# proves it, and whether the check's scope fits inside those files. When a plan grows past
# 300 lines it is carrying implementation, which makes implementers into transcribers whose
# transcription then gets reviewed: the work done twice. In practice the worst case was a
# 4105-line plan for 541 lines of shell.
#
# The plan lives in the Working section of a feature's state page (docs/YYMMDD-<feature>-state.html).
# Runs after every write to a state page and reports the Working section's line count back. Exit 2 with
# the message on stderr is fed to the model; the write itself has already happened.
set -uo pipefail

LIMIT="${AGENTKEEL_PLAN_LIMIT:-300}"
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

if [ "${1:-}" = "--selftest" ]; then
  T=$(mktemp -d 2>/dev/null || mktemp -d -t agentkeel); mkdir -p "$T/docs"
  { echo '<section data-keel-transient="working">'; yes "<p>task</p>" | head -n 300; echo '</section>'; } > "$T/docs/261005-x-state.html"
  { echo '<section data-keel-transient="working">'; yes "<p>task</p>" | head -n 297; echo '</section>'; } > "$T/docs/261005-y-state.html"
  { yes "<p>current behavior</p>" | head -n 900; } > "$T/docs/261005-z-state.html"
  fail=0
  printf '{"tool_name":"Write","tool_input":{"file_path":"%s"}}' "$T/docs/261005-x-state.html" | "$SELF" >/dev/null 2>&1; [ $? -eq 2 ] || { echo "selftest FAIL: 301 lines allowed" >&2; fail=1; }
  printf '{"tool_name":"Write","tool_input":{"file_path":"%s"}}' "$T/docs/261005-y-state.html" | "$SELF" >/dev/null 2>&1; [ $? -eq 0 ] || { echo "selftest FAIL: 299 lines blocked" >&2; fail=1; }
  printf '{"tool_name":"Write","tool_input":{"file_path":"%s"}}' "$T/docs/261005-z-state.html" | "$SELF" >/dev/null 2>&1; [ $? -eq 0 ] || { echo "selftest FAIL: durable content counted as plan" >&2; fail=1; }
  printf 'not json' | "$SELF" >/dev/null 2>&1; [ $? -eq 0 ] || { echo "selftest FAIL: bad input blocked" >&2; fail=1; }
  rm -rf "$T"
  [ $fail -eq 0 ] && echo "plan-size-guard selftest: PASS"
  exit $fail
fi

INPUT=$(cat)
HOOKS_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ "${1:-}" = "--plugin" ]; then  # plugin hooks act only where the act lands in an opted-in repo
  printf '%s' "$INPUT" | python3 -c 'import json,sys
sys.path.insert(0, sys.argv[1])
from agentkeel_core import record
try: p = json.load(sys.stdin)
except Exception: sys.exit(1)
sys.exit(1 if record.plugin_inactive(["--plugin"], p) else 0)' "$HOOKS_DIR" 2>/dev/null || exit 0
fi
# Every file the call wrote: file_path for Claude Code's Write/Edit, each path in a Codex
# apply_patch envelope (read by the shared core, so both hosts are judged the same way).
FILES=$(printf '%s' "$INPUT" | python3 -c 'import json,sys,os
sys.path.insert(0, sys.argv[1])
try:
    from agentkeel_core import host
    p = json.load(sys.stdin)
    for e in host.events(p, p.get("cwd") or os.getcwd()):
        if e.kind == "edit": print(e.path)
except Exception:
    pass' "$HOOKS_DIR" 2>/dev/null)

FILE=""; LINES=0
while IFS= read -r f; do
  case "$f" in
    */docs/*-state.html)
      [ -f "$f" ] || continue
      n=$(python3 -c 'import sys
sys.path.insert(0, sys.argv[1])
from agentkeel_core import pages
print(sum(len(s.split("\n")) for s in pages.sections(open(sys.argv[2], encoding="utf-8", errors="replace").read(), "working")))' "$HOOKS_DIR" "$f" 2>/dev/null || echo 0)
      if [ "$n" -gt "$LIMIT" ]; then FILE="$f"; LINES="$n"; break; fi ;;
  esac
done <<EOF_FILES
$FILES
EOF_FILES
[ -n "$FILE" ] || exit 0

cat >&2 <<MSG
PLAN SIZE GUARD: the Working section of $(basename "$FILE") is now $LINES lines; the limit is $LIMIT.

A plan this long is carrying code. Plans never carry code: a plan is the task table (task, files
it may touch, blocked by, the check that proves it, and whether the check's scope fits inside
those files). Implementers do the implementing; a plan that transcribes it makes the work happen
twice, once in the plan and once in review of the transcription.

Cut it to the table. If the deliverable is small enough that the plan would have to carry the
code, there is no plan: go straight to the task list and implement with the per-task review.
Gate the plan ONCE; do not re-gate a revised plan.
MSG
exit 2
