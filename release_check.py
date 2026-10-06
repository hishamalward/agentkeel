#!/usr/bin/env python3
"""Release consistency: one product version across every file that states one.

  python3 release_check.py                  the version fields agree with each other
  python3 release_check.py --tag v0.4.0     ... and with the release tag (CI runs this on a tag push)

The version is read where it is declared: the Claude and Codex plugin manifests, the Claude
marketplace entry, and the versioned plugin paths in README.md. There is no separate version file
to keep in step. Exit 0 when all agree, 1 with the disagreements listed.
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def declared(root=ROOT):
    """[(where, version)] for every version-bearing field."""
    found = []
    for rel in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        with open(os.path.join(root, rel)) as fh:
            found.append((rel, str(json.load(fh).get("version", ""))))
    with open(os.path.join(root, ".claude-plugin/marketplace.json")) as fh:
        for p in json.load(fh).get("plugins", []):
            if "version" in p:
                found.append((f".claude-plugin/marketplace.json ({p.get('name')})", str(p["version"])))
    rel = ".agents/plugins/marketplace.json"
    with open(os.path.join(root, rel)) as fh:
        for p in json.load(fh).get("plugins", []):
            if "version" in p:
                found.append((f"{rel} ({p.get('name')})", str(p["version"])))
    with open(os.path.join(root, "README.md")) as fh:
        for n, line in enumerate(fh, 1):
            for v in re.findall(r"plugins/cache/agentkeel/agentkeel/([^/\s`]+)/", line):
                found.append((f"README.md:{n}", v))
    return found


def problems(found, tag=None):
    out = [f"{where}: {v!r} is not MAJOR.MINOR.PATCH" for where, v in found if not SEMVER.match(v)]
    versions = sorted({v for _, v in found})
    if len(versions) > 1:
        out.append("the version fields disagree: " + "; ".join(f"{w} = {v}" for w, v in found))
    if tag is not None:
        want = tag[1:] if tag.startswith("v") else tag
        out += [f"{where}: {v} does not match the tag {tag}" for where, v in found if v != want]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag")
    ap.add_argument("--root", default=ROOT)
    args = ap.parse_args(argv)
    found = declared(args.root)
    errs = problems(found, args.tag)
    if errs:
        print("release check: FAIL\n  " + "\n  ".join(errs))
        return 1
    print(f"release check: {found[0][1]} in {len(found)} places" + (f", matches {args.tag}" if args.tag else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
