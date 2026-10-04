#!/usr/bin/env python3
"""Install agentkeel into a repository for Claude Code. Preview by default.

  python3 install.py <repo>              show what would change, change nothing
  python3 install.py <repo> --apply      make those changes
  python3 install.py <repo> --uninstall  preview removal (add --apply to remove)

What it does, and what it never does:
  - copies the hooks and agentkeel_core/ into <repo>/.claude/hooks/
  - merges the hook entries into <repo>/.claude/settings.json; existing hooks and settings are
    kept, nothing is overwritten, and the v0.1 entries (tier-guard, write-path-guard) are removed
  - writes the instruction fragment into AGENTS.md between agentkeel markers (creating AGENTS.md
    if needed). It never creates a CLAUDE.md: Claude Code loads CLAUDE.md instead of AGENTS.md
    when one exists, so a CLAUDE.md would hide these instructions. If one exists, it says so.

Installed is not active. Claude Code reads the hooks when a session starts; the report ends with
the one test that proves they loaded. Codex is not supported in this version (Stage 2).
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK_FILES = ["task.py", "task-guard.py", "secret-guard.py", "plan-gate-guard.py", "plan-size-guard.sh"]
CORE_FILES = ["__init__.py", "shell.py", "gitops.py", "record.py"]
OBSOLETE = ["tier.sh", "tier-guard.py", "write-path-guard.py"]
START, END = "<!-- agentkeel:start -->", "<!-- agentkeel:end -->"


def atomic_write(path, text):
    """Write beside the real file (a symlink stays a symlink) and keep its permissions."""
    path = os.path.realpath(path)
    mode = os.stat(path).st_mode & 0o777 if os.path.exists(path) else 0o644
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".agentkeel-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def is_ours(path):
    """A file agentkeel wrote: every hook and core module names agentkeel in its first lines."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return "agentkeel" in fh.read(2000)
    except OSError:
        return False


def ours(command):
    return any(f"/.claude/hooks/{n}" in command for n in HOOK_FILES + OBSOLETE)


def merged_settings(existing, template, remove):
    hooks = existing.setdefault("hooks", {})
    # drop every agentkeel entry first; then (unless removing) add the current ones back
    for event in list(hooks):
        groups = []
        for g in hooks[event]:
            kept = [h for h in g.get("hooks", []) if not ours(str(h.get("command", "")))]
            if kept:
                groups.append({**g, "hooks": kept})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if not remove:
        for event, groups in template["hooks"].items():
            target = hooks.setdefault(event, [])
            for g in groups:
                same = next((t for t in target if t.get("matcher") == g.get("matcher")), None)
                if same is None:
                    target.append(json.loads(json.dumps(g)))
                else:
                    same.setdefault("hooks", []).extend(g["hooks"])
    if not hooks:
        existing.pop("hooks")
    return existing


def agents_text(current, fragment, remove):
    block = f"{START}\n{fragment.rstrip()}\n{END}\n"
    if START in current and END in current:
        before, rest = current.split(START, 1)
        after = rest.split(END, 1)[1].lstrip("\n")
        if remove:
            return (before.rstrip("\n") + "\n" + (("\n" + after) if after else "")).lstrip("\n")
        return before + block + (("\n" + after) if after else "")
    if remove:
        return current
    return (current.rstrip("\n") + "\n\n" if current.strip() else "") + block


def plan(repo, remove):
    actions = []  # (description, function)
    skipped = []
    hooks_dir = os.path.join(repo, ".claude", "hooks")
    for name in HOOK_FILES:
        dst = os.path.join(hooks_dir, name)
        if os.path.exists(dst) and not is_ours(dst):
            skipped.append(f"{os.path.relpath(dst, repo)} exists and is not agentkeel's; left alone")
            continue
        if remove:
            if os.path.exists(dst):
                actions.append((f"remove {os.path.relpath(dst, repo)}", lambda d=dst: os.remove(d)))
        else:
            src = os.path.join(HERE, "hooks", name)
            actions.append((f"copy hooks/{name} -> {os.path.relpath(dst, repo)}",
                            lambda s=src, d=dst: (os.makedirs(os.path.dirname(d), exist_ok=True),
                                                  shutil.copy2(s, d), os.chmod(d, 0o755))))
    core = os.path.join(hooks_dir, "agentkeel_core")
    if remove:
        for name in CORE_FILES:
            dst = os.path.join(core, name)
            if os.path.exists(dst) and is_ours(dst):
                actions.append((f"remove {os.path.relpath(dst, repo)}", lambda d=dst: os.remove(d)))
        if os.path.isdir(core):
            actions.append((f"remove {os.path.relpath(core, repo)}/ if empty",
                            lambda: (shutil.rmtree(os.path.join(core, "__pycache__"), ignore_errors=True),
                                     os.rmdir(core) if not os.listdir(core) else None)))
    else:
        for name in CORE_FILES:
            src, dst = os.path.join(HERE, "hooks", "agentkeel_core", name), os.path.join(core, name)
            actions.append((f"copy hooks/agentkeel_core/{name}",
                            lambda s=src, d=dst: (os.makedirs(os.path.dirname(d), exist_ok=True),
                                                  shutil.copy2(s, d))))
    for name in OBSOLETE:
        dst = os.path.join(hooks_dir, name)
        if os.path.exists(dst) and is_ours(dst):
            actions.append((f"remove v0.1 hook {os.path.relpath(dst, repo)}", lambda d=dst: os.remove(d)))

    settings_path = os.path.join(repo, ".claude", "settings.json")
    try:
        with open(settings_path, encoding="utf-8") as fh:
            existing = json.load(fh)
    except FileNotFoundError:
        existing = {}
    except ValueError as exc:
        raise SystemExit(f"install: {settings_path} is not valid JSON ({exc}); fix it first, nothing changed")
    with open(os.path.join(HERE, "templates", "claude-hooks.json"), encoding="utf-8") as fh:
        template = json.load(fh)
    new = merged_settings(json.loads(json.dumps(existing)), template, remove)
    if new != existing:
        verb = "remove agentkeel entries from" if remove else "merge agentkeel hook entries into"
        actions.append((f"{verb} .claude/settings.json (other hooks and settings kept)",
                        lambda: atomic_write(settings_path, json.dumps(new, indent=2) + "\n")))

    agents_path = os.path.join(repo, "AGENTS.md")
    current = open(agents_path, encoding="utf-8").read() if os.path.exists(agents_path) else ""
    with open(os.path.join(HERE, "templates", "AGENTS.agentkeel.md"), encoding="utf-8") as fh:
        fragment = fh.read()
    if (START in current) != (END in current) or (START in current and current.index(END) < current.index(START)):
        raise SystemExit("install: AGENTS.md has a broken agentkeel block (one marker missing or out of\n"
                         "order); fix the markers by hand. Nothing changed.")
    text = agents_text(current, fragment, remove)
    if text != current:
        verb = "remove the agentkeel block from" if remove else ("update the agentkeel block in" if START in current
                                                                  else "add the agentkeel block to")
        if remove and not text.strip():
            actions.append(("remove AGENTS.md (it held only the agentkeel block)", lambda: os.remove(agents_path)))
        else:
            actions.append((f"{verb} AGENTS.md{'' if current or remove else ' (new file)'}",
                            lambda: atomic_write(agents_path, text)))
    return actions, skipped


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("repo")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--uninstall", action="store_true")
    args = p.parse_args(argv)
    repo = os.path.realpath(args.repo)
    if not os.path.isdir(os.path.join(repo, ".git")) and not os.path.isfile(os.path.join(repo, ".git")):
        print(f"install: {repo} is not the top of a git repository", file=sys.stderr)
        return 2
    actions, skipped = plan(repo, args.uninstall)
    mode = "apply" if args.apply else "preview (nothing changed; add --apply)"
    print(f"agentkeel {'uninstall' if args.uninstall else 'install'} into {repo}: {mode}")
    for desc, _ in actions:
        print(f"  - {desc}")
    if not actions:
        print("  - nothing to do")
    for note in skipped:
        print(f"  ! {note}")
    if args.apply:
        for _, fn in actions:
            fn()
    for name in ("CLAUDE.md", os.path.join(".claude", "CLAUDE.md"), "CLAUDE.local.md"):
        if os.path.exists(os.path.join(repo, name)):
            print(f"\nwarning: {name} exists. Claude Code loads it instead of AGENTS.md, so the agentkeel\n"
                  f"instructions are hidden from Claude. Add the line `@AGENTS.md` to {name}, or move its\n"
                  "content into AGENTS.md and delete it. This installer does not touch it.")
    if args.apply and not args.uninstall:
        print("\nConfigured, not yet verified. Hooks load when a Claude Code session starts. To prove it,\n"
              "start a new session in the repo and ask for a one-line edit before declaring a task:\n"
              "the edit must be refused with 'no task is declared for this session'.")
    if args.uninstall and args.apply:
        print(f"\nTask records and logs in {os.path.expanduser('~/.agentkeel')} are kept; delete that folder by hand if wanted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
