#!/usr/bin/env python3
"""agentkeel: decide which checks a candidate commit needs, from the paths it changes.

  python3 select_checks.py --base <rev> --head <rev>   prints `app=true` or `app=false`

A change that touches only documentation does not run the app tests; anything else does. The
documentation patterns default to Markdown, docs/ and design-exploration/, and can be replaced
with AGENTKEEL_DOCS_GLOBS (colon-separated fnmatch patterns). When the paths cannot be read (a
missing base, a shallow clone), the answer is app=true: an unknown change runs everything.
Standard library only, so it runs in CI before any install step.
"""
import argparse
import fnmatch
import os
import subprocess
import sys

DEFAULT_DOCS = ["*.md", "docs/*", "design-exploration/*", "LICENSE", ".github/ISSUE_TEMPLATE/*"]


def changed(base, head):
    mb = subprocess.run(["git", "merge-base", base, head], capture_output=True, text=True)
    if mb.returncode != 0:
        return None
    start = mb.stdout.strip()
    if start == subprocess.run(["git", "rev-parse", head], capture_output=True, text=True).stdout.strip():
        start = f"{head}~1"  # head is already on base (a push to main): judge its own commit
    out = subprocess.run(["git", "diff", "--name-only", start, head], capture_output=True, text=True)
    return out.stdout.split() if out.returncode == 0 else None


def needs_app(paths, docs):
    if paths is None:
        return True
    return any(not any(fnmatch.fnmatchcase(p, g) for g in docs) for p in paths)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default="HEAD")
    a = ap.parse_args(argv)
    docs = [g for g in os.environ.get("AGENTKEEL_DOCS_GLOBS", "").split(":") if g] or DEFAULT_DOCS
    paths = changed(a.base, a.head)
    print(f"app={'true' if needs_app(paths, docs) else 'false'}")
    sys.stderr.write(f"changed: {', '.join(paths) if paths is not None else '(unknown)'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
