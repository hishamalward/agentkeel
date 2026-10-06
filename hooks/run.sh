#!/bin/sh
# agentkeel hook launcher: run one of agentkeel's hook scripts with a verified interpreter, in
# isolated mode, under an emptied environment. The host's environment can carry PYTHONPATH and
# other variables that redirect a plain `python3 <script>` (measured on Codex, see
# docs/enforcement-design.md), so the hooks never inherit it. The interpreter is the one
# `task.py init` recorded in AGENTKEEL_HOME/interpreter (Python 3.10 or later); with no record, the
# first python3 of 3.10 or later in a fixed list of folders. Usage: run.sh <hook file in this folder> [args...]
here=$(cd "$(dirname "$0")" && pwd -P)
hook=$1
shift
case "$hook" in
  ""|*/*|.*) echo "agentkeel: run.sh needs a hook file name" >&2; exit 0 ;;
esac
[ -f "$here/$hook" ] || { echo "agentkeel: no hook $hook" >&2; exit 0; }
fixed_path=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin
home_dir=${AGENTKEEL_HOME:-$HOME/.agentkeel}
py=
if [ -r "$home_dir/interpreter" ]; then
  py=$(head -n 1 "$home_dir/interpreter")
  case "$py" in /*) [ -x "$py" ] || py= ;; *) py= ;; esac
fi
if [ -z "$py" ]; then
  for dir in /opt/homebrew/bin /usr/local/bin /usr/bin /bin; do
    if [ -x "$dir/python3" ] && "$dir/python3" -I -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
      py=$dir/python3
      break
    fi
  done
fi
[ -n "$py" ] || { echo "agentkeel: no Python 3.10 or later found; run task.py init with one" >&2; exit 0; }
keep() { eval "v=\${$1+set}"; [ "$v" = set ] && eval "printf '%s\n' \"$1=\$$1\""; }
env_args=$(for name in HOME AGENTKEEL_HOME AGENTKEEL_SCRATCH AGENTKEEL_GH CLAUDE_PROJECT_DIR \
    CLAUDE_PLUGIN_ROOT PLUGIN_ROOT CLAUDE_CODE_SESSION_ID CODEX_THREAD_ID GH_TOKEN GITHUB_TOKEN GH_HOST; do keep $name; done)
case "$hook" in
  *.sh) set -- /bin/bash "$here/$hook" "$@" ;;
  *) set -- "$py" -I "$here/$hook" "$@" ;;
esac
IFS='
'
# shellcheck disable=SC2086
exec /usr/bin/env -i PATH="$fixed_path" $env_args "$@"
