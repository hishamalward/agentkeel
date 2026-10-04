"""Split a shell command line into the simple commands a guard has to judge.

A guard that reads one regex match per command line misses the second command in
`git push origin feat && git push origin main`. This module reads the whole line: every
simple command, in order, with its leading VAR=value assignments, its argv with wrappers
(sudo, env, timeout, ...) removed, and the directory it runs in after any earlier `cd`.

It is a reader for guards, not a shell. Known limits, stated so nobody relies on more:
variables and globs are not expanded, a command hidden behind a script or an npm script is
not seen, and a `cd` inside a subshell is treated like any other `cd`.
"""
import os
import re
import shlex
from dataclasses import dataclass, field

SEPARATOR_CHARS = set(";&|()\n")
REDIRECT_CHARS = set("<>&")
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z0-9_.-]+)\1")
SUBST_RE = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "for", "!", "{", "}",
            "time", "case", "esac", "in"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
MAX_DEPTH = 4


@dataclass
class SimpleCommand:
    argv: list
    env: dict = field(default_factory=dict)
    cwd: str = ""

    @property
    def name(self):
        return os.path.basename(self.argv[0]) if self.argv else ""

    def text(self):
        return " ".join(self.argv)


def strip_heredocs(command):
    """Drop heredoc bodies: text fed to `cat <<EOF` is data, not commands."""
    lines = command.split("\n")
    out, pending = [], []
    for line in lines:
        if pending:
            if line.strip() == pending[0]:
                pending.pop(0)
            continue
        out.append(line)
        for m in HEREDOC_RE.finditer(line):
            if "<<<" not in line[max(0, m.start() - 1):m.start() + 3]:
                pending.append(m.group(2))
    return "\n".join(out)


def tokens(command):
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    try:
        return list(lex)
    except ValueError:
        # unbalanced quotes: fall back to a plain split, still separated on the operators
        return re.findall(r"[;&|()\n]+|[<>]+|[^\s;&|()<>]+", command)


def _is_separator(tok):
    return tok and set(tok) <= SEPARATOR_CHARS and not set(tok) & set("<>")


def _is_redirect(tok):
    return tok and set(tok) <= REDIRECT_CHARS and set(tok) & set("<>")


def _unwrap(argv, env):
    """Remove leading assignments and wrapper commands; return the real argv."""
    changed = True
    while argv and changed:
        changed = False
        while argv and ASSIGN_RE.match(argv[0]):
            k, v = argv[0].split("=", 1)
            env[k] = v
            argv = argv[1:]
            changed = True
        if not argv:
            break
        head = os.path.basename(argv[0])
        if head in KEYWORDS or head in ("command", "builtin", "exec", "nohup", "noglob"):
            argv = argv[1:]
            changed = True
        elif head == "sudo":
            argv = argv[1:]
            while argv and argv[0].startswith("-"):
                takes = argv[0] in ("-u", "-g", "-C", "-p", "-h", "-U", "-r", "-t")
                argv = argv[2:] if takes else argv[1:]
            changed = True
        elif head == "env":
            argv = argv[1:]
            while argv and (argv[0].startswith("-") or ASSIGN_RE.match(argv[0])):
                if ASSIGN_RE.match(argv[0]):
                    k, v = argv[0].split("=", 1)
                    env[k] = v
                    argv = argv[1:]
                elif argv[0] in ("-u", "-C", "-S"):
                    argv = argv[2:]
                else:
                    argv = argv[1:]
            changed = True
        elif head in ("nice", "timeout", "caffeinate"):
            argv = argv[1:]
            while argv and argv[0].startswith("-"):
                takes = argv[0] in ("-n", "-s", "-k", "--signal", "--kill-after", "-w")
                argv = argv[2:] if takes else argv[1:]
            if head == "timeout" and argv:
                argv = argv[1:]  # the duration
            changed = True
        elif head == "xargs":
            argv = argv[1:]
            while argv and argv[0].startswith("-"):
                takes = argv[0] in ("-I", "-n", "-P", "-L", "-s", "-E", "-d")
                argv = argv[2:] if takes else argv[1:]
            changed = True
    return argv


def _resolve_cd(argv, cwd):
    if len(argv) < 2 or argv[1] in ("-",):
        return os.path.expanduser("~") if len(argv) < 2 else cwd
    target = argv[-1]
    return os.path.normpath(os.path.join(cwd, os.path.expanduser(target)))


def commands(command, cwd, _depth=0):
    """Every simple command in `command`, in order, as SimpleCommand(argv, env, cwd)."""
    if _depth > MAX_DEPTH or not command:
        return []
    command = strip_heredocs(str(command))
    result = []
    # command substitutions run too: read them as commands of their own
    for m in SUBST_RE.finditer(command):
        inner = m.group(1) if m.group(1) is not None else m.group(2)
        result.extend(commands(inner, cwd, _depth + 1))
    command = command.replace("`", "\n")
    here = cwd
    current = []
    toks = tokens(command) + [";"]
    i = 0
    while i < len(toks):
        tok = toks[i]
        if _is_separator(tok):
            if current:
                env = {}
                argv = _unwrap(current, env)
                if argv:
                    name = os.path.basename(argv[0])
                    if name in ("cd", "pushd"):
                        here = _resolve_cd(argv, here)
                    elif name in SHELLS and "-c" in argv[1:]:
                        idx = argv.index("-c")
                        if idx + 1 < len(argv):
                            result.extend(commands(argv[idx + 1], here, _depth + 1))
                    elif name == "eval" and len(argv) > 1:
                        result.extend(commands(" ".join(argv[1:]), here, _depth + 1))
                    else:
                        result.append(SimpleCommand(argv=argv, env=env, cwd=here))
                current = []
            i += 1
            continue
        if _is_redirect(tok):
            if current and current[-1].isdigit():
                current.pop()  # the fd number in 2>&1
            i += 2  # the operator and its target
            continue
        current.append(tok)
        i += 1
    return result
