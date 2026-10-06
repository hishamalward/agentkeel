"""The shared instructions in AGENTS.md: one managed block, the same for Claude Code and Codex.

AGENTS.md owns the stable working instructions, agentkeel.json the machine-readable policy, and
the plugin the runtime facts (paths, session). `init` keeps one block between the markers that
install.py also uses, and never touches a byte outside it. The block carries a hash of the text it
was written with, so init can tell its own text from a hand edit: its own text is updated to the
shipped version; an edited block is left exactly as it is and reported. It never creates a
CLAUDE.md, and it reports one that exists, because Claude Code then loads that file instead.
"""
import hashlib
import os
import tempfile

START, END = "<!-- agentkeel:start -->", "<!-- agentkeel:end -->"
HASH_PREFIX = "<!-- agentkeel:sha256="
CLAUDE_FILES = ("CLAUDE.md", "CLAUDE.local.md", os.path.join(".claude", "CLAUDE.md"))


def fragment_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "templates", "AGENTS.agentkeel.md")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def block_for(fragment):
    body = fragment.rstrip() + "\n"
    return f"{START}\n{HASH_PREFIX}{_sha(body)} -->\n{body}{END}\n"


def claude_conflicts(repo):
    return [name for name in CLAUDE_FILES if os.path.lexists(os.path.join(repo, name))]


def plan(current, fragment):
    """(status, new text or None). Status: added, current, updated, edited, broken."""
    has_start, has_end = START in current, END in current
    if has_start != has_end or (has_start and current.index(END) < current.index(START)):
        return "broken", None
    new_block = block_for(fragment)
    if not has_start:
        sep = "" if not current else ("\n" if current.endswith("\n") else "\n\n")
        return "added", current + sep + new_block
    i, j = current.index(START), current.index(END) + len(END)
    if current[j:j + 1] == "\n":
        j += 1
    inner = current[i + len(START):current.index(END)]
    inner = inner[1:] if inner.startswith("\n") else inner
    first, _, body = inner.partition("\n")
    if not first.startswith(HASH_PREFIX) or first[len(HASH_PREFIX):].split(" ")[0] != _sha(body):
        # no hash (an install.py block) or text that no longer matches its hash: a person's text
        return "edited", None
    if current[i:j] == new_block:
        return "current", None
    return "updated", current[:i] + new_block + current[j:]


def ensure(repo, fragment=None):
    """Apply the plan to <repo>/AGENTS.md. Returns (status, detail). Never follows a symbolic
    link, and refuses to write when the file changed between the read and the replace."""
    if fragment is None:
        try:
            with open(fragment_path(), encoding="utf-8") as fh:
                fragment = fh.read()
        except OSError:
            return "no-template", ("this copy of agentkeel has no instruction template (a per-repository\n"
                                   "install); install.py keeps the AGENTS.md block there")
    path = os.path.join(repo, "AGENTS.md")
    if os.path.islink(path):
        return "symlink", "AGENTS.md is a symbolic link; init does not write through it"
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            current = fh.read()
        existed = True
    except FileNotFoundError:
        current, existed = "", False
    status, text = plan(current, fragment)
    if text is None:
        return status, ""
    fd, tmp = tempfile.mkstemp(dir=repo, prefix=".agentkeel-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        if existed:
            os.chmod(tmp, os.stat(path).st_mode & 0o777)
            with open(path, encoding="utf-8", newline="") as fh:
                if fh.read() != current:
                    return "raced", "AGENTS.md changed while init ran; nothing was written"
            os.replace(tmp, path)
        else:
            os.chmod(tmp, 0o644)
            try:
                os.link(tmp, path)  # fails if AGENTS.md appeared meanwhile: never replaces it
            except FileExistsError:
                return "raced", "AGENTS.md appeared while init ran; nothing was written"
            status = "created"
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return status, ""
