"""agentkeel repostate: read a working tree's state without running anything its repository names.

The hooks and the human's commands run outside the task's sandbox. A task can write its own
`.git/config`, so any git command run in its repository with that config can run the task's
programs with the host's rights: a clean filter on `git add`, `core.fsmonitor` on `git status`,
a hook. `core.hooksPath` alone does not stop filters or fsmonitor.

So this module never runs git with the repository's config:
  - refs, HEAD and the stash reflog are read as files;
  - the tree of the working folder is computed by git in a temporary git folder that holds only
    agentkeel's own config. The repository's objects are reached as a read-only alternate, and new
    objects go to the temporary folder. The system and global config are not read either.
`.gitattributes` can still name a filter, but with no definition in any config read, git runs none.

Every failure raises InspectError. Callers fail closed: no state means "not known to be preserved"
or "unrecorded", never "clean".
"""
import os
import re
import shutil
import subprocess
import tempfile

SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
FIXED_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"
SHADOW_CONFIG = ("[core]\n\trepositoryformatversion = 0\n\tbare = false\n\tfsmonitor = false\n"
                 "\tuntrackedCache = false\n\thooksPath = " + os.devnull + "\n")


class InspectError(Exception):
    pass


class Repo:
    def __init__(self, top, gitdir, commondir):
        self.top, self.gitdir, self.commondir = top, gitdir, commondir


def _read(path):
    if os.path.islink(path) or not os.path.isfile(path):
        raise InspectError(f"{path} is not a plain file")
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as e:
        raise InspectError(f"{path} could not be read: {e}") from e


def locate(path):
    """The repository that holds `path`, found by reading files only."""
    here = os.path.realpath(path)
    while True:
        dotgit = os.path.join(here, ".git")
        if os.path.lexists(dotgit):
            break
        parent = os.path.dirname(here)
        if parent == here:
            raise InspectError(f"{path} is not inside a git repository")
        here = parent
    if os.path.islink(dotgit):
        raise InspectError(f"{dotgit} is a symbolic link")
    if os.path.isdir(dotgit):
        gitdir = commondir = dotgit
    else:
        text = _read(dotgit).strip()
        if not text.startswith("gitdir: "):
            raise InspectError(f"{dotgit} names no git folder")
        gitdir = os.path.realpath(os.path.join(here, text[len("gitdir: "):]))
        commondir = gitdir
        if os.path.exists(os.path.join(gitdir, "commondir")):
            commondir = os.path.realpath(os.path.join(gitdir, _read(os.path.join(gitdir, "commondir")).strip()))
    for d in (gitdir, commondir):
        if not os.path.isdir(d):
            raise InspectError(f"{d} is missing")
    if os.path.exists(os.path.join(commondir, "reftable")):
        raise InspectError("the repository stores refs in a reftable, which agentkeel does not read")
    if not os.path.isdir(os.path.join(commondir, "objects")):
        raise InspectError(f"{commondir} has no objects folder")
    return Repo(here, gitdir, commondir)


def _packed(commondir):
    path = os.path.join(commondir, "packed-refs")
    out = {}
    if not os.path.lexists(path):
        return out
    for line in _read(path).splitlines():
        if not line or line.startswith(("#", "^")):
            continue
        parts = line.split(" ", 1)
        if len(parts) != 2 or not SHA_RE.match(parts[0]):
            raise InspectError(f"packed-refs has a line agentkeel cannot read: {line[:80]}")
        out[parts[1]] = parts[0]
    return out


def resolve(repo, name, depth=0):
    """The commit id a ref names, or None when the ref does not exist (an unborn branch)."""
    if depth > 5:
        raise InspectError(f"{name}: too many symbolic refs")
    for base in ((repo.gitdir, repo.commondir) if name == "HEAD" else (repo.commondir,)):
        path = os.path.join(base, name)
        if os.path.lexists(path):
            text = _read(path).strip()
            if text.startswith("ref: "):
                return resolve(repo, text[5:].strip(), depth + 1)
            if not SHA_RE.match(text):
                raise InspectError(f"{name} holds '{text[:60]}', not a commit id")
            return text
    return _packed(repo.commondir).get(name)


def refs(repo, prefix):
    """{refname: id} under `prefix` (for example refs/heads/), loose refs over packed ones."""
    out = {k: v for k, v in _packed(repo.commondir).items() if k.startswith(prefix)}
    root = os.path.join(repo.commondir, prefix)
    if os.path.lexists(root):
        if os.path.islink(root):
            raise InspectError(f"{prefix} is a symbolic link")
        for folder, dirs, files in os.walk(root):
            for name in files:
                path = os.path.join(folder, name)
                ref = prefix + os.path.relpath(path, root).replace(os.sep, "/")
                text = _read(path).strip()
                if text.startswith("ref: "):
                    target = resolve(repo, text[5:].strip())
                    if target:
                        out[ref] = target
                    continue
                if not SHA_RE.match(text):
                    raise InspectError(f"{ref} holds '{text[:60]}', not a commit id")
                out[ref] = text
    return out


def stash_entries(repo):
    """Every stash entry, not only the newest: refs/stash and each id in its reflog."""
    out = []
    tip = resolve(repo, "refs/stash")
    if tip:
        out.append(tip)
    log = os.path.join(repo.commondir, "logs", "refs", "stash")
    if os.path.lexists(log):
        for line in _read(log).splitlines():
            parts = line.split(" ", 2)
            if len(parts) < 2 or not SHA_RE.match(parts[1]):
                raise InspectError("the stash reflog has a line agentkeel cannot read")
            if parts[1].strip("0") and parts[1] not in out:
                out.append(parts[1])
    return out


class Shadow:
    """A temporary git folder for one repository: agentkeel's config, the repository's objects as a
    read-only alternate, and nothing else of the repository's own."""

    def __init__(self, repo):
        self.repo = repo
        self.dir = tempfile.mkdtemp(prefix="agentkeel-shadow-")
        try:
            os.makedirs(os.path.join(self.dir, "objects", "info"))
            os.makedirs(os.path.join(self.dir, "refs"))
            os.makedirs(os.path.join(self.dir, "info"))
            with open(os.path.join(self.dir, "config"), "w") as fh:
                fh.write(SHADOW_CONFIG)
            with open(os.path.join(self.dir, "HEAD"), "w") as fh:
                fh.write("ref: refs/heads/agentkeel-shadow\n")
            with open(os.path.join(self.dir, "objects", "info", "alternates"), "w") as fh:
                fh.write(os.path.join(repo.commondir, "objects") + "\n")
            exclude = os.path.join(repo.commondir, "info", "exclude")
            if os.path.isfile(exclude) and not os.path.islink(exclude):
                shutil.copyfile(exclude, os.path.join(self.dir, "info", "exclude"))  # patterns only
        except Exception:
            self.close()
            raise

    def git(self, *args, index=None):
        env = {"PATH": FIXED_PATH, "HOME": os.path.expanduser("~"), "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_DIR": self.dir, "GIT_WORK_TREE": self.repo.top,
               "GIT_INDEX_FILE": index or os.path.join(self.dir, "index"), "LC_ALL": "C"}
        try:
            p = subprocess.run(["git", *args], cwd=self.repo.top, env=env, capture_output=True, text=True,
                               input="", timeout=300)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise InspectError(f"git {args[0]} could not run: {e}") from e
        if p.returncode != 0:
            raise InspectError(f"git {args[0]} failed: {(p.stderr or p.stdout).strip()[:300]}")
        return p.stdout.strip()

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _tree_of(shadow, commit):
    return shadow.git("rev-parse", "--verify", f"{commit}^{{tree}}")


def state(path):
    """(HEAD, tree id of the working folder as it is, untracked files included)."""
    repo = locate(path)
    head = resolve(repo, "HEAD")
    with Shadow(repo) as sh:
        if head:
            sh.git("read-tree", head)
        sh.git("add", "-A")
        return head, sh.git("write-tree")


def inspect(path):
    """Everything release needs to know about a clone, or InspectError."""
    repo = locate(path)
    head = resolve(repo, "HEAD")
    branches = refs(repo, "refs/heads/")
    stashes = stash_entries(repo)
    with Shadow(repo) as sh:
        head_tree = _tree_of(sh, head) if head else sh.git("mktree")
        if head:
            sh.git("read-tree", head)
        sh.git("add", "-A")
        work_tree = sh.git("write-tree")
        index_tree = head_tree
        index = os.path.join(repo.gitdir, "index")
        if os.path.lexists(index):
            if os.path.islink(index) or not os.path.isfile(index):
                raise InspectError("the clone's index is not a plain file")
            copy = os.path.join(sh.dir, "index-copy")
            shutil.copyfile(index, copy)
            index_tree = sh.git("write-tree", index=copy)  # what is staged
        changed = set()
        for tree in {work_tree, index_tree} - {head_tree}:
            changed.update(filter(None, sh.git("diff-tree", "-r", "--name-only", "--no-renames",
                                               head_tree, tree).splitlines()))
    return {"top": os.path.realpath(repo.top), "head": head, "branches": branches, "stashes": stashes, "changed": sorted(changed)}
