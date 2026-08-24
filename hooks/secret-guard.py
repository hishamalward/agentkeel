#!/usr/bin/env python3
"""agentkeel secret guard (PreToolUse, matcher Bash).

A secret may be used; it may not be shown. Once a value is printed it is in the transcript, in
the session log, and in whatever the transcript is later pasted into. This refuses the shell
commands whose only effect is to show one:

  - printing an env file:      cat .env, less .env.local, head .env.production, bat .env
                               (.env.example, .env.sample and .env.template are fine)
  - printing key material:     cat id_rsa, cat server.pem, cat ~/.aws/credentials, cat ~/.netrc
  - dumping the environment:   env, printenv (bare), printenv API_KEY
  - echoing a secret variable: echo $API_KEY, echo "${DB_PASSWORD}", printf %s $GITHUB_TOKEN
  - showing an env file via git: git show HEAD:.env, git diff .env, git log -p .env

Reading a secret into the environment is not showing it, so `source .env`, `. .env` and
`export $(cat .env | xargs)` are allowed.

Override: AGENTKEEL_SHOW_SECRETS=1, echoed to stderr when used.

What this cannot see: a program that reads the secret and prints it (python -c ...), or a value
already in a file that gets printed under a name this list does not know. It is a courtesy guard
with sharp defaults, not a DLP system. Exit 0 allows; exit 2 blocks; unparseable input allows.
"""
import json
import os
import re
import subprocess
import sys

ENV_FILE_RE = re.compile(r"(?:^|[\s/'\"=:])(\.env(?:\.[A-Za-z0-9_.-]+)?)(?=$|[\s'\";|&)])")
ENV_FILE_OK = re.compile(r"^\.env\.(?:example|sample|template|dist)$")
KEY_FILE_RE = re.compile(
    r"(?:^|[\s/'\"])(?:id_rsa|id_ed25519|id_ecdsa|id_dsa|[^\s'\"]+\.(?:pem|key|p12|pfx)|credentials\.json"
    r"|\.aws/credentials|\.netrc|\.npmrc|\.pypirc|\.git-credentials|\.docker/config\.json)(?=$|[\s'\";|&)])"
)
SHOW_CMDS = {"cat", "less", "more", "head", "tail", "bat", "nl", "strings", "xxd", "od", "open", "code",
             "vim", "vi", "nano", "tac", "grep", "rg", "awk", "sed", "cut", "sort"}
SECRET_NAME_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
SECRET_WORD_RE = re.compile(r"(?i)(key|token|secret|password|passwd|credential|auth)")
SPLIT_RE = re.compile(r"\|\||&&|;|\|")
SUBST_RE = re.compile(r"\$\([^)]*\)|`[^`]*`")


def block(msg):
    sys.stderr.write("SECRET GUARD: " + msg.rstrip() + "\n")
    return 2


def first_word(segment):
    words = segment.strip().split()
    while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
        words.pop(0)
    if words and words[0] in ("sudo", "command", "exec", "time", "nohup"):
        words.pop(0)
    return words


def offending(command):
    """Return a short reason if the command shows a secret, else None."""
    for raw in SPLIT_RE.split(command):
        segment = SUBST_RE.sub(" ", raw)  # a `cat .env` inside $(...) is reading, not showing
        words = first_word(segment)
        if not words:
            continue
        cmd = os.path.basename(words[0])
        args = words[1:]
        if cmd == "env" and not args:
            return "bare `env` prints every variable, secrets included"
        if cmd == "printenv":
            if not args:
                return "bare `printenv` prints every variable, secrets included"
            if any(SECRET_WORD_RE.search(a) for a in args):
                return f"`printenv {' '.join(args)}` prints a secret"
        if cmd in ("echo", "printf"):
            for m in SECRET_NAME_RE.finditer(segment):
                if SECRET_WORD_RE.search(m.group(1)):
                    return f"`{cmd}` of ${m.group(1)} prints a secret"
        if cmd in SHOW_CMDS:
            for m in ENV_FILE_RE.finditer(segment):
                if not ENV_FILE_OK.match(m.group(1)):
                    return f"`{cmd} {m.group(1)}` prints an env file"
            if KEY_FILE_RE.search(segment):
                return f"`{cmd}` of key material"
        if cmd == "git" and args and args[0] in ("show", "diff", "log", "cat-file", "grep"):
            for m in ENV_FILE_RE.finditer(segment):
                if not ENV_FILE_OK.match(m.group(1)):
                    return f"`git {args[0]}` of {m.group(1)} prints an env file"
    return None


def decide(payload, environ=os.environ):
    if payload.get("tool_name") != "Bash":
        return 0
    command = str((payload.get("tool_input") or {}).get("command", ""))
    reason = offending(command)
    if not reason:
        return 0
    if environ.get("AGENTKEEL_SHOW_SECRETS") == "1":
        sys.stderr.write(f"SECRET GUARD: override AGENTKEEL_SHOW_SECRETS=1 used: {reason}\n")
        return 0
    return block(
        f"refusing: {reason}.\n"
        "A secret may be used, not shown; once printed it lives in the transcript.\n"
        "Use it without printing (source .env, read it in the program), or check that it is set\n"
        "with `test -n \"$VAR\" && echo set`. If the human asked to see it, run with\n"
        "AGENTKEEL_SHOW_SECRETS=1 so the override is on record."
    )


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        return selftest()
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
    except Exception:
        return 0
    try:
        return decide(payload)
    except Exception as exc:
        sys.stderr.write(f"secret-guard: internal error, allowing: {exc}\n")
        return 0


def selftest():
    here = os.path.abspath(__file__)

    def run(command, expect, env=None):
        payload = {"tool_name": "Bash", "tool_input": {"command": command}}
        out = subprocess.run([sys.executable, here], input=json.dumps(payload), text=True,
                             capture_output=True, env={**os.environ, **(env or {})})
        ok = out.returncode == expect
        print(("PASS" if ok else "FAIL"), repr(command), "->", out.returncode)
        return ok

    results = [
        run("cat .env", 2), run("cat .env.example", 0), run("head -n 3 apps/web/.env.local", 2),
        run("printenv", 2), run("printenv PATH", 0), run("echo $API_KEY", 2), run("echo $HOME", 0),
        run("git show HEAD:.env", 2), run("source .env && npm test", 0),
        run("export $(cat .env | xargs) && npm test", 0), run("cat ~/.aws/credentials", 2),
        run("cat .env", 0, {"AGENTKEEL_SHOW_SECRETS": "1"}),
    ]
    print("secret-guard selftest:", "PASS" if all(results) else "FAIL")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
