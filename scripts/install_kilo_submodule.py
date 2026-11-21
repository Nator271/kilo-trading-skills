#!/usr/bin/env python3
"""Install kilo-trading-skills as a submodule into another project's .kilo.

Copies skills/, workflows/, skillsets/ and .kilo/ from the submodule into
the destination project so Kilo Code can discover them locally.

Usage (from the destination project):
    python3 <submodule>/scripts/install_kilo_submodule.py \
        --source <path-to-submodule> --dest <path-to-destination>

By default, existing directories are replaced. Use --merge to add/update
files without removing pre-existing content.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install kilo-trading-skills into a project .kilo directory."
    )
    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="Path to the kilo-trading-skills submodule checkout.",
    )
    parser.add_argument(
        "--dest",
        required=True,
        type=Path,
        help="Path to the destination project (where .kilo/ will be created/updated).",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge into existing .kilo instead of replacing directories and config.",
    )
    parser.add_argument(
        "--install-hook",
        action="store_true",
        help="Install the post-merge git hook so skills auto-update on pull.",
    )
    return parser.parse_args()


EXCLUDED_DIR_NAMES = {"tests", "__pycache__", ".pytest_cache", ".venv"}
EXCLUDED_FILE_NAMES = {".DS_Store"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def copy_tree(src: Path, dst: Path, *, merge: bool = False) -> None:
    """Copy src into dst, excluding test/build artifacts.
    If merge, only add/update files, never delete."""
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.is_dir() and item.name in EXCLUDED_DIR_NAMES:
            continue
        if item.is_file() and item.name in EXCLUDED_FILE_NAMES:
            continue
        if item.is_file() and item.suffix in EXCLUDED_SUFFIXES:
            continue
        target = dst / item.name
        if item.is_dir():
            if merge and target.exists():
                copy_tree(item, target, merge=True)
            else:
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(item, target, symlinks=True)
        else:
            shutil.copy2(item, target)


def load_kilo_jsonc(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_kilo_jsonc(dest: Path, skills_rel: str, *, merge: bool = False) -> None:
    kilo_dir = dest / ".kilo"
    kilo_dir.mkdir(parents=True, exist_ok=True)
    kilo_jsonc = kilo_dir / "kilo.jsonc"

    if merge:
        config = load_kilo_jsonc(kilo_jsonc)
    else:
        config = {}

    # Ensure required top-level keys exist.
    config.setdefault("$schema", "https://app.kilo.ai/config.json")
    config.setdefault("snapshot", False)
    config.setdefault("default_agent", "code")
    config.setdefault("instructions", ["AGENTS.md"])

    # Merge skills paths.
    skills = config.setdefault("skills", {})
    paths = skills.setdefault("paths", [])
    if skills_rel not in paths:
        paths.append(skills_rel)

    # Merge permissions (keep existing, add missing defaults).
    default_permissions = {
        "bash": "allow",
        "edit": "allow",
        "read": "allow",
        "glob": "allow",
        "grep": "allow",
        "task": "allow",
        "webfetch": "allow",
        "websearch": "allow",
        "skill": "allow",
    }
    perms = config.setdefault("permission", {})
    for key, value in default_permissions.items():
        perms.setdefault(key, value)
    config["permission"] = perms

    text = json.dumps(config, indent=2) + "\n"
    kilo_jsonc.write_text(text, encoding="utf-8")


def confirm_overwrite(dest: Path) -> bool:
    """Ask the user to confirm overwriting existing .kilo content."""
    kilo_dest = dest / ".kilo"
    existing = []
    for name in ("skills", "workflows", "skillsets", "agents", "commands", "plans"):
        if (kilo_dest / name).exists():
            existing.append(name)
    if (kilo_dest / "kilo.jsonc").exists():
        existing.append("kilo.jsonc")

    if not existing:
        return True

    print(
        f"\nWARNING: The following already exist in {kilo_dest}:",
        file=sys.stderr,
    )
    for name in existing:
        print(f"  - {name}", file=sys.stderr)
    print(
        "Without --merge, these will be REPLACED by the submodule content.",
        file=sys.stderr,
    )
    try:
        answer = input("Continue? [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    dest = args.dest.resolve()

    if not (source / "skills").is_dir():
        print(f"ERROR: {source}/skills not found", flush=True)
        return 1

    kilo_dest = dest / ".kilo"

    # Confirm before overwriting when not merging.
    if not args.merge and not confirm_overwrite(dest):
        print("Aborted.", flush=True)
        return 1

    # Copy skills into .kilo/skills so kilo.jsonc can point at them.
    copy_tree(source / "skills", kilo_dest / "skills", merge=args.merge)

    # Copy workflows and skillsets so skills can read them.
    copy_tree(source / "workflows", kilo_dest / "workflows", merge=args.merge)
    copy_tree(source / "skillsets", kilo_dest / "skillsets", merge=args.merge)

    # Copy agent/command/plan resources from the submodule .kilo.
    if (source / ".kilo").is_dir():
        for sub in ("agents", "commands", "plans"):
            copy_tree(source / ".kilo" / sub, kilo_dest / sub, merge=args.merge)

    # Write (or merge into) kilo.jsonc pointing at the installed skills.
    write_kilo_jsonc(dest, "./.kilo/skills", merge=args.merge)

    # Install the post-merge hook if requested.
    if args.install_hook:
        hook_src = source / "scripts" / "hooks" / "post-merge"
        hook_dst = dest / ".git" / "hooks" / "post-merge"
        if not hook_src.is_file():
            print(
                f"WARNING: hook script not found at {hook_src}, skipping hook install.",
                flush=True,
            )
        else:
            hook_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(hook_src, hook_dst)
            try:
                hook_dst.chmod(0o755)
            except OSError:
                pass
            print(f"Installed post-merge hook at {hook_dst}", flush=True)

    print(
        f"Installed kilo-trading-skills from {source} into {kilo_dest}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
