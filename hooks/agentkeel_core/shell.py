"""agentkeel core: split a shell command line into the simple commands a guard has to judge.

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


QUOTED_RE = re.compile(r"'[^']*'|\"(?:[^\"\\\\]|\\\\.)*\"|\$\(\([^)]*\)\)")
SHELL_FED_RE = re.compile(r"(?:^|[|;&]\s*)(?:\S*/)?(?:bash|sh|zsh|dash|ksh|eval|xargs)\b")


def strip_heredocs(command):
    """Drop heredoc bodies: text fed to `cat <<EOF` is data, not commands. A body fed to a shell
    (`bash <<EOF`) is commands, so it is kept. `<<` inside quotes or $((...)) is not a heredoc."""
    lines = command.split("\n")
    out, pending = [], []
    for line in lines:
        if pending:
            delim, keep = pending[0]
            if line.strip() == delim:
                pending.pop(0)
            elif keep:
                out.append(line)
            continue
        out.append(line)
        spans = [q.span() for q in QUOTED_RE.finditer(line)]
        for m in HEREDOC_RE.finditer(line):
            if any(a < m.start() < b for a, b in spans):
                continue  # `<<` inside quotes or $((...)) is not a heredoc
            if "<<<" in line[max(0, m.start() - 1):m.start() + 3]:
                continue
            fed_to_shell = bool(SHELL_FED_RE.search(QUOTED_RE.sub(" ", line[:m.start()])))
            pending.append((m.group(2), fed_to_shell))
    return "\n".join(out)


def tokens(command):
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""  # a `#` comment must not swallow the newline that ends it
    try:
        return list(lex)
    except ValueError:
        # unbalanced quotes: fall back to a plain split, still separated on the operators
        return re.findall(r"[;&|()\n]+|[<>]+|[^\s;&|()<>]+", command)


def _is_separator(tok):
    return tok and set(tok) <= SEPARATOR_CHARS and not set(tok) & set("<>")


def _is_redirect(tok):
    return tok and set(tok) <= REDIRECT_CHARS and set(tok) & set("<>")


def _split(text):
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _shell_c(argv):
    """The command string of `bash -c '...'`, `bash -lc '...'`, `sh -ec '...'`; else None."""
    for i, a in enumerate(argv[1:], start=1):
        if a.startswith("-") and not a.startswith("--") and "c" in a[1:]:
            return argv[i + 1] if i + 1 < len(argv) else None
        if not a.startswith("-"):
            return None
    return None


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
                elif argv[0] in ("-S", "--split-string") and len(argv) > 1:
                    argv = _split(argv[1]) + argv[2:]
                    break
                elif argv[0].startswith(("-S", "--split-string=")) and len(argv[0]) > 2:
                    value = argv[0].split("=", 1)[1] if argv[0].startswith("--") else argv[0][2:]
                    argv = _split(value) + argv[1:]
                    break
                elif argv[0] in ("-u", "-C"):
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


def commands(command, cwd, _depth=0, _env=None):
    """Every simple command in `command`, in order, as SimpleCommand(argv, env, cwd)."""
    if _depth > MAX_DEPTH or not command:
        return []
    command = strip_heredocs(str(command).replace("\\\n", " "))
    result = []
    # command substitutions run too: read them as commands of their own
    for m in SUBST_RE.finditer(command):
        inner = m.group(1) if m.group(1) is not None else m.group(2)
        result.extend(commands(inner, cwd, _depth + 1, _env))
    command = command.replace("`", "\n")
    here = cwd
    current = []
    toks = tokens(command) + [";"]
    i = 0
    while i < len(toks):
        tok = toks[i]
        if _is_separator(tok):
            if current:
                env = dict(_env or {})  # assignments of an enclosing `VAR=x bash -c` reach this command
                argv = _unwrap(current, env)
                if argv:
                    name = os.path.basename(argv[0])
                    if name in ("cd", "pushd"):
                        here = _resolve_cd(argv, here)
                    elif name in SHELLS and _shell_c(argv) is not None:
                        result.extend(commands(_shell_c(argv), here, _depth + 1, env))
                    elif name == "eval" and len(argv) > 1:
                        result.extend(commands(" ".join(argv[1:]), here, _depth + 1, env))
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
