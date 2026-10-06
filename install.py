#!/usr/bin/env python3
"""Install agentkeel into a repository for Claude Code and Codex. Preview by default.

  python3 install.py <repo>              show what would change, change nothing
  python3 install.py <repo> --apply      make those changes
  python3 install.py <repo> --uninstall  preview removal (add --apply to remove)
  python3 install.py <repo> --doctor     check what is installed and trusted (--live: prove it)
  --host claude|codex|all                which hosts (default all)

What it does, and what it never does:
  - copies the hooks and agentkeel_core/ into <repo>/.claude/hooks/
  - merges the hook entries into <repo>/.claude/settings.json (Claude Code) and
    <repo>/.codex/hooks.json (Codex); existing hooks and settings are kept, nothing is
    overwritten, and the v0.1 entries (tier-guard, write-path-guard) are removed
  - writes the instruction fragment into AGENTS.md between agentkeel markers (creating AGENTS.md
    if needed). It never creates a CLAUDE.md: Claude Code loads CLAUDE.md instead of AGENTS.md
    when one exists, so a CLAUDE.md would hide these instructions. If one exists, it says so.

Installed is not active. Hosts read hooks when a session starts, and Codex runs a new project
hook only after the human trusts it (/hooks in codex). --doctor reports what is installed and
trusted; --doctor --live proves each host refuses an undeclared write.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK_FILES = ["task.py", "task-guard.py", "secret-guard.py", "plan-gate-guard.py", "plan-size-guard.sh"]
CORE_FILES = ["__init__.py", "shell.py", "gitops.py", "record.py", "patch.py", "host.py", "checks.py", "pages.py",
              "starters.py", "hostcheck.py"]
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


def _known_commands():
    """Every hook command agentkeel has ever written: the current templates and the v0.1/v0.2
    form. A user's own entry that merely names a file of the same name is never one of them."""
    known = {f'"$CLAUDE_PROJECT_DIR"/.claude/hooks/{n}' for n in HOOK_FILES + OBSOLETE}
    for name in ("claude-hooks.json", "codex-hooks.json"):
        with open(os.path.join(HERE, "templates", name), encoding="utf-8") as fh:
            for groups in json.load(fh)["hooks"].values():
                for g in groups:
                    known.update(h["command"] for h in g["hooks"])
    return known


KNOWN = None


def ours(command):
    global KNOWN
    if KNOWN is None:
        KNOWN = _known_commands()
    return command.strip() in KNOWN


def merged_settings(existing, template, remove, left_alone=()):
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
                g = {**g, "hooks": [h for h in g["hooks"]
                                    if not any(f"/.claude/hooks/{n}" in h["command"] for n in left_alone)]}
                if not g["hooks"]:
                    continue  # its script is the user's own file, left alone above
                same = next((t for t in target if t.get("matcher") == g.get("matcher")), None)
                if same is None:
                    target.append(json.loads(json.dumps(g)))
                else:
                    same.setdefault("hooks", []).extend(g["hooks"])
    if not hooks:
        existing.pop("hooks")
    return existing


def agents_insert(current, fragment):
    """(new text, separator): the block replaces an existing one in place, or is appended after a
    separator that gives one blank line. Nothing outside the block changes."""
    block = f"{START}\n{fragment.rstrip()}\n{END}\n"
    if START in current and END in current:
        i, j = current.index(START), current.index(END) + len(END)
        if current[j:j + 1] == "\n":
            j += 1
        return current[:i] + block + current[j:], None
    sep = "" if not current else ("\n" if current.endswith("\n") else "\n\n")
    return current + sep + block, sep


def agents_remove(current, sep):
    """The text without the block (and the separator install added, when it is still there);
    every other byte, the user's later edits included, stays as it is."""
    if START not in current or END not in current:
        return current
    i, j = current.index(START), current.index(END) + len(END)
    if current[j:j + 1] == "\n":
        j += 1
    before, after = current[:i], current[j:]
    if sep and not after and before.endswith(sep):
        before = before[:-len(sep)]
    return before + after


HOST_CONFIG = {
    "claude": (os.path.join(".claude", "settings.json"), "claude-hooks.json"),
    "codex": (os.path.join(".codex", "hooks.json"), "codex-hooks.json"),
}


def plan(repo, remove, hosts=("claude", "codex")):
    actions = []  # (description, function)
    skipped = []
    hooks_dir = os.path.join(repo, ".claude", "hooks")
    left_alone = []
    for name in HOOK_FILES:
        dst = os.path.join(hooks_dir, name)
        if os.path.exists(dst) and not is_ours(dst):
            skipped.append(f"{os.path.relpath(dst, repo)} exists and is not agentkeel's; left alone, and\n"
                           "    no agentkeel hook entry points at it")
            left_alone.append(name)
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
            def tidy():
                shutil.rmtree(os.path.join(core, "__pycache__"), ignore_errors=True)
                for d in (core, hooks_dir):
                    if os.path.isdir(d) and not os.listdir(d):
                        os.rmdir(d)
            actions.append((f"remove {os.path.relpath(core, repo)}/ and .claude/hooks/ if empty", tidy))
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

    for h in hosts:
        rel, template_name = HOST_CONFIG[h]
        actions += config_actions(repo, rel, template_name, remove, drop_when_empty=(h == "codex"),
                                  left_alone=left_alone)
    toml = os.path.join(repo, ".codex", "config.toml")
    if "codex" in hosts and os.path.exists(toml):
        text = open(toml, encoding="utf-8").read()
        doubled = [n for n in HOOK_FILES if n.rsplit(".", 1)[0] in text]
        if doubled:
            skipped.append(".codex/config.toml already defines hooks named " + ", ".join(doubled) +
                           "; Codex loads both files, so each would run twice (a plan-gate dispatch\n"
                           "    would count twice). Remove those entries from config.toml by hand")

    agents_path = os.path.join(repo, "AGENTS.md")
    current = open(agents_path, encoding="utf-8", newline="").read() if os.path.exists(agents_path) else ""
    with open(os.path.join(HERE, "templates", "AGENTS.agentkeel.md"), encoding="utf-8") as fh:
        fragment = fh.read()
    if (START in current) != (END in current) or (START in current and current.index(END) < current.index(START)):
        raise SystemExit("install: AGENTS.md has a broken agentkeel block (one marker missing or out of\n"
                         "order); fix the markers by hand. Nothing changed.")
    actions += agents_actions(agents_path, current, fragment, remove, os.path.exists(agents_path))
    return actions, skipped


def backup_path(path):
    """Where the original bytes of a config file are kept between install and uninstall."""
    import hashlib
    home = os.path.realpath(os.path.expanduser(os.environ.get("AGENTKEEL_HOME") or "~/.agentkeel"))
    key = hashlib.sha256(os.path.realpath(path).encode()).hexdigest()[:16]
    return os.path.join(home, "install-backups", key)


def prune(d):
    if os.path.isdir(d) and not os.listdir(d):
        os.rmdir(d)


def save_original(path):
    b = backup_path(path)
    if os.path.exists(b) or os.path.exists(b + ".absent"):
        return  # keep the first original across repeated installs
    os.makedirs(os.path.dirname(b), exist_ok=True)
    if os.path.exists(path):
        shutil.copy2(path, b)
    else:
        open(b + ".absent", "w").close()


def restore_or_write(path, new, remove):
    """On uninstall, put back the original bytes when the content is the same as before install."""
    b = backup_path(path)
    if remove and os.path.exists(b):
        try:
            with open(b, encoding="utf-8") as fh:
                original = json.load(fh)
        except (OSError, ValueError):
            original = None
        if original == new:
            mode = os.stat(path).st_mode & 0o777 if os.path.exists(path) else None
            shutil.copyfile(b, os.path.realpath(path))
            if mode is not None:
                os.chmod(os.path.realpath(path), mode)
            os.remove(b)
            prune(os.path.dirname(b))
            return
    atomic_write(path, json.dumps(new, indent=2) + "\n")


def _read_bytes(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def agents_actions(path, current, fragment, remove, exists):
    """Install: insert the block, keep the pre-install bytes once, and snapshot the installed bytes.
    Uninstall: if the file still matches the snapshot exactly, put the pre-install bytes back (or
    delete a file install created); if the user edited it, remove only the block."""
    b = backup_path(path)
    meta_path, snap_path = b + ".meta", b + ".installed"
    try:
        with open(meta_path) as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        meta = {}
    if remove:
        if START not in current:
            return []
        unchanged = _read_bytes(snap_path) == current.encode("utf-8")
        original = _read_bytes(b)
        if unchanged and (original is not None or meta.get("absent")):
            new = None if meta.get("absent") else original
        else:
            text = agents_remove(current, meta.get("sep"))
            new = None if (not text.strip() and meta.get("absent")) else text.encode("utf-8")

        def apply_remove():
            if new is None:
                os.remove(path)
            else:
                mode = os.stat(path).st_mode & 0o777
                real = os.path.realpath(path)
                with open(real, "wb") as fh:
                    fh.write(new)
                os.chmod(real, mode)
            for leftover in (b, meta_path, snap_path, b + ".absent"):
                if os.path.exists(leftover):
                    os.remove(leftover)
            prune(os.path.dirname(b))
        return [("remove AGENTS.md (install created it)" if new is None else
                 "remove the agentkeel block from AGENTS.md", apply_remove)]
    text, sep = agents_insert(current, fragment)
    if text == current:
        return []

    def apply_install():
        os.makedirs(os.path.dirname(b), exist_ok=True)
        snap = _read_bytes(snap_path)
        if snap is not None and snap != current.encode("utf-8"):
            # edited since the last install: the pre-install bytes no longer describe this file
            for stale in (b,):
                if os.path.exists(stale):
                    os.remove(stale)
            meta.pop("absent", None)
        elif not os.path.exists(b) and not meta.get("absent") and snap is None:
            if exists:
                shutil.copyfile(os.path.realpath(path), b)
            else:
                meta["absent"] = True
        if sep is not None:
            meta["sep"] = sep
        with open(meta_path, "w") as fh:
            json.dump(meta, fh)
        atomic_write(path, text)
        with open(snap_path, "wb") as fh:
            fh.write(text.encode("utf-8"))
    verb = "update the agentkeel block in" if START in current else "add the agentkeel block to"
    return [(f"{verb} AGENTS.md{'' if exists else ' (new file)'}", apply_install)]


def config_actions(repo, rel, template_name, remove, drop_when_empty, left_alone=()):
    path = os.path.join(repo, rel)
    try:
        with open(path, encoding="utf-8") as fh:
            existing = json.load(fh)
    except FileNotFoundError:
        existing = None
    except ValueError as exc:
        raise SystemExit(f"install: {path} is not valid JSON ({exc}); fix it first, nothing changed")
    if existing is None and remove:
        return []
    with open(os.path.join(HERE, "templates", template_name), encoding="utf-8") as fh:
        template = json.load(fh)
    new = merged_settings(json.loads(json.dumps(existing or {})), template, remove, left_alone)
    if new == existing:
        return []
    if remove and (not new) and (drop_when_empty or os.path.exists(backup_path(path) + ".absent")):
        def drop():
            os.remove(path)
            for leftover in (backup_path(path) + ".absent", backup_path(path)):
                if os.path.exists(leftover):
                    os.remove(leftover)
            prune(os.path.dirname(backup_path(path)))
            if not os.listdir(os.path.dirname(path)):
                os.rmdir(os.path.dirname(path))
        return [(f"remove {rel} (it held only agentkeel hooks)", drop)]
    verb = "remove agentkeel entries from" if remove else "merge agentkeel hook entries into"

    def write():
        if not remove:
            save_original(path)
        restore_or_write(path, new, remove)
    return [(f"{verb} {rel} (other hooks and settings kept)", write)]


def probe_prompt(name):
    return (f"This is an automated check of this repository's guard hooks. Without declaring any task, "
            f"use your file editing tool once to create the file {name} containing the word probe. "
            "Do not retry, do not use the shell, and do not work around a refusal. Reply with the exact "
            "error text you received, or 'created' if it worked.")


def doctor(repo, hosts, live):
    """Report, per host, what is installed, trusted and (with --live) proven to refuse."""
    import re
    import subprocess
    rows = []

    def row(host, check, ok, detail=""):
        rows.append((host, check, ok, detail))

    hooks_dir = os.path.join(repo, ".claude", "hooks")
    for name in HOOK_FILES + [os.path.join("agentkeel_core", n) for n in CORE_FILES]:
        p = os.path.join(hooks_dir, name)
        if not (os.path.exists(p) and is_ours(p)):
            row("all", f"hook file {name}", False, "missing or not agentkeel's")
    if not any(r[1].startswith("hook file") for r in rows):
        row("all", "hook files", True, ".claude/hooks/ complete")
    for name in HOOK_FILES:
        p = os.path.join(hooks_dir, name)
        if os.path.exists(p):
            cmd = ["bash", p, "--selftest"] if name.endswith(".sh") else ["python3", p, "--selftest"]
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            row("all", f"selftest {name}", out.returncode == 0, "" if out.returncode == 0 else out.stdout[-200:])
    for h in hosts:
        rel, _ = HOST_CONFIG[h]
        try:
            with open(os.path.join(repo, rel), encoding="utf-8") as fh:
                cfg = json.load(fh)
            cmds = [x.get("command", "") for groups in cfg.get("hooks", {}).values() for g in groups for x in g.get("hooks", [])]
            n = sum(1 for c in cmds if ours(c))
            row(h, f"{rel} entries", n >= 4, f"{n} agentkeel hook entries")
        except (OSError, ValueError) as exc:
            row(h, f"{rel} entries", False, str(exc)[:80])
    if "codex" in hosts:
        try:
            with open(os.path.expanduser("~/.codex/config.toml"), encoding="utf-8") as fh:
                text = fh.read()  # read for two markers only; nothing from it is printed
            trusted_project = re.search(r'\[projects\."' + re.escape(repo) + r'"\][^\[]*trust_level\s*=\s*"trusted"', text)
            forms = {repo, repo.replace("/private/tmp/", "/tmp/", 1), repo.replace("/private/var/", "/var/", 1)}
            trusted_hooks = sum(text.count(os.path.join(f, ".codex", "hooks.json") + ":") for f in forms)
            row("codex", "project trusted", bool(trusted_project), "" if trusted_project else "open codex in the repo and trust it")
            row("codex", "hooks trusted", trusted_hooks >= 4,
                f"{trusted_hooks} trust entries for .codex/hooks.json (hash not re-verified); run /hooks in codex if low")
        except OSError:
            row("codex", "trust", False, "~/.codex/config.toml not readable")
    if live:
        import uuid
        for h in hosts:
            # a name no file can already have, checked anyway: the doctor never touches a user file
            name = f"agentkeel-doctor-probe-{uuid.uuid4().hex[:12]}.txt"
            probe = os.path.join(repo, name)
            if os.path.lexists(probe):
                row(h, "live refusal reaches the agent", False, f"{name} already exists; not run")
                continue
            if h == "claude":
                cmd = ["claude", "-p", "--model", "sonnet", "--permission-mode", "bypassPermissions", probe_prompt(name)]
            else:
                cmd = ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "--ephemeral",
                       "-c", 'model_reasoning_effort="low"', "-C", repo, probe_prompt(name)]
            env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT")}
            try:
                out = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=600, env=env)
                text = out.stdout + out.stderr
            except (OSError, subprocess.TimeoutExpired) as exc:
                text = str(exc)
            created = os.path.lexists(probe)  # it did not exist before this run, so it is ours
            refused = "no task is declared" in text
            row(h, "live refusal reaches the agent", refused and not created,
                "refused before the write" if refused and not created else
                ("THE PROBE FILE WAS CREATED: hooks not active" if created else "no refusal text seen in the output"))
            if created:
                os.remove(probe)
    width = max(len(r[1]) for r in rows) if rows else 10
    for host_, check, ok, detail in rows:
        print(f"  {'PASS' if ok else 'FAIL'}  {host_:6} {check:<{width}}  {detail}")
    if not live:
        print("\n  Not verified live. Run again with --live to prove each host refuses a write\n"
              "  (one short model session per host).")
    return 0 if all(r[2] for r in rows) else 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("repo")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--uninstall", action="store_true")
    p.add_argument("--host", choices=("claude", "codex", "all"), default="all",
                   help="which agent hosts to configure (default: all)")
    p.add_argument("--doctor", action="store_true", help="check the installation; changes nothing")
    p.add_argument("--live", action="store_true", help="with --doctor: one short model session per host")
    args = p.parse_args(argv)
    hosts = ("claude", "codex") if args.host == "all" else (args.host,)
    repo = os.path.realpath(args.repo)
    if not os.path.isdir(os.path.join(repo, ".git")) and not os.path.isfile(os.path.join(repo, ".git")):
        print(f"install: {repo} is not the top of a git repository", file=sys.stderr)
        return 2
    if args.doctor:
        print(f"agentkeel doctor for {repo}")
        return doctor(repo, hosts, args.live)
    actions, skipped = plan(repo, args.uninstall, hosts)
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
        print("\nConfigured, not yet verified. Hooks load when a session starts.")
        if "codex" in hosts:
            print("Codex skips new or changed project hooks until you trust them: open `codex` in the\n"
                  "repo, run /hooks, and trust the agentkeel entries (the project must be trusted too).")
        print(f"Then run `python3 {os.path.abspath(__file__)} {repo} --doctor` to check, and prove it live:\n"
              "ask for a one-line edit before declaring a task; it must be refused with\n"
              "'no task is declared for this session'.")
    if args.uninstall and args.apply:
        print(f"\nTask records and logs in {os.path.expanduser('~/.agentkeel')} are kept; delete that folder by hand if wanted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
