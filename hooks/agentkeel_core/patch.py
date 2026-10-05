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
each one. For an added file the full new content is known; for an update only the added and
removed lines are.
"""
import re
from dataclasses import dataclass, field

HEADER_RE = re.compile(r"^\*\*\* (Add File|Update File|Delete File|Move to): (.+?)\s*$")


@dataclass
class FileChange:
    kind: str                 # add | update | delete | move-to
    path: str
    added: list = field(default_factory=list)
    removed: list = field(default_factory=list)

    def new_content(self):
        """The whole new text for an added file; None when only a diff is known."""
        return "\n".join(self.added) + ("\n" if self.added else "") if self.kind == "add" else None


def envelope(text):
    """The patch text from a command line or tool input that carries one, else None."""
    if not text or "*** Begin Patch" not in text:
        return None
    start = text.index("*** Begin Patch")
    end = text.find("*** End Patch", start)
    return text[start:end + len("*** End Patch")] if end != -1 else text[start:]


def parse(text):
    """FileChange for every file the patch touches, in order. A move yields the update of the
    source and a move-to of the destination."""
    changes, current = [], None
    for line in (text or "").split("\n"):
        m = HEADER_RE.match(line)
        if m:
            kind = {"Add File": "add", "Update File": "update", "Delete File": "delete",
                    "Move to": "move-to"}[m.group(1)]
            current = FileChange(kind, m.group(2))
            changes.append(current)
            continue
        if current is None or line.startswith("***"):
            continue
        if line.startswith("+"):
            current.added.append(line[1:])
        elif line.startswith("-"):
            current.removed.append(line[1:])
    return changes
