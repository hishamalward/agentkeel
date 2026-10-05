"""agentkeel core: read a Codex `apply_patch` envelope into the file operations it performs.

The envelope:

    *** Begin Patch
    *** Add File: path/new.py
    +line
    *** Update File: path/old.py
    *** Move to: path/renamed.py
    @@ context
    -removed
    +added
    *** Delete File: path/gone.py
    *** End Patch

Every path is reported: an add, an update, a delete, and both ends of a move, so a guard judges
each one. Headers are read even when indented, and every envelope in the text is read, so a
second envelope or an indented header cannot hide a file. For an update, `apply` rebuilds the
new text from the old one, so a guard can judge the result exactly as it judges a whole-file
write; when the hunks do not fit the old text, the result is unknown (None).
"""
import re
from dataclasses import dataclass, field

HEADER_RE = re.compile(r"^\s*\*\*\* (Add File|Update File|Delete File|Move to): (.+?)\s*$")
BEGIN, END = "*** Begin Patch", "*** End Patch"


@dataclass
class FileChange:
    kind: str                 # add | update | delete | move-to
    path: str
    lines: list = field(default_factory=list)   # body lines as written (with their +/-/space)

    @property
    def added(self):
        return [l[1:] for l in self.lines if l.startswith("+")]

    @property
    def removed(self):
        return [l[1:] for l in self.lines if l.startswith("-")]

    def new_content(self):
        """The whole new text for an added file; None when only a diff is known."""
        return "\n".join(self.added) + ("\n" if self.added else "") if self.kind == "add" else None


def envelope(text):
    """All patch text in a command line or tool input (every envelope), else None."""
    if not text or BEGIN not in text:
        return None
    parts, pos = [], 0
    while True:
        start = text.find(BEGIN, pos)
        if start == -1:
            break
        end = text.find(END, start)
        parts.append(text[start:end + len(END)] if end != -1 else text[start:])
        if end == -1:
            break
        pos = end + len(END)
    return "\n".join(parts)


def parse(text):
    """FileChange for every file the patch touches, in order. A move yields the update of the
    source and a move-to of the destination (the hunks stay with the update)."""
    changes, current, body_owner = [], None, None
    for line in (text or "").replace("\r\n", "\n").split("\n"):
        m = HEADER_RE.match(line)
        if m:
            kind = {"Add File": "add", "Update File": "update", "Delete File": "delete",
                    "Move to": "move-to"}[m.group(1)]
            current = FileChange(kind, m.group(2).strip())
            changes.append(current)
            if kind != "move-to":
                body_owner = current
            continue
        if body_owner is None or line.strip().startswith("***"):
            continue
        body_owner.lines.append(line)
    return changes


def apply(old_text, change):
    """The new text of an updated file, or None when the hunks cannot be placed."""
    if change.kind == "add":
        return change.new_content()
    if change.kind != "update" or old_text is None:
        return None
    hunks, cur = [], []
    for l in change.lines:
        if l.startswith("@@"):
            if cur:
                hunks.append(cur)
            cur = []
        elif l == "" or l[0] in " +-":
            cur.append(l if l else " ")
    if cur:
        hunks.append(cur)
    lines, pos = old_text.split("\n"), 0
    for h in hunks:
        old = [l[1:] for l in h if l[0] in " -"]
        new = [l[1:] for l in h if l[0] in " +"]
        if not old:
            lines[pos:pos] = new
            pos += len(new)
            continue
        at = next((i for i in range(pos, len(lines) - len(old) + 1) if lines[i:i + len(old)] == old), None)
        if at is None:
            at = next((i for i in range(pos, len(lines) - len(old) + 1)
                       if [x.rstrip() for x in lines[i:i + len(old)]] == [x.rstrip() for x in old]), None)
        if at is None:
            return None
        lines[at:at + len(old)] = new
        pos = at + len(new)
    return "\n".join(lines)
