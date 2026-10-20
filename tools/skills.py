#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["PyYAML>=6.0.2,<7"]
# ///
"""Manage a personal skill catalog and links into local harnesses."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import uuid

import yaml

NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK = re.compile(r"\]\(([^)\n]+)\)")


class SkillError(Exception):
    pass


def valid_name(name):
    if not NAME.fullmatch(name) or len(name) > 64:
        raise SkillError(f"Invalid skill name: {name!r}; use lowercase kebab-case, 1–64 characters")
    return name


def harnesses(home):
    return {
        "codex": home / ".codex/skills",
        "claude": home / ".claude/skills",
        "opencode": home / ".config/opencode/skills",
    }


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
    if not match:
        raise SkillError(f"Missing YAML frontmatter: {path}")
    try:
        data = yaml.safe_load(match[1])
    except yaml.YAMLError as exc:
        raise SkillError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SkillError(f"Frontmatter must be a mapping: {path}")
    return data, text[match.end():]


def check_skill(path, expected=None):
    if not path.is_dir() or path.is_symlink():
        raise SkillError(f"Catalog skill must be a real directory: {path}")
    root = path.resolve()
    for item in path.rglob("*"):
        if item.is_symlink():
            raise SkillError(f"Symlinks inside a skill are not portable: {item}")
        if not item.is_file() and not item.is_dir():
            raise SkillError(f"Unsupported file type: {item}")
    data, _ = frontmatter(path / "SKILL.md")
    name = valid_name(data.get("name", "") if isinstance(data.get("name"), str) else "")
    if name != (expected or path.name):
        raise SkillError(f"Folder/name mismatch: {path.name} vs {name}")
    desc = data.get("description")
    if not isinstance(desc, str) or not 1 <= len(desc.strip()) <= 1024:
        raise SkillError(f"Description must contain 1–1024 characters: {path}")
    for doc in path.rglob("*.md"):
        for raw in LINK.findall(doc.read_text(encoding="utf-8")):
            link = raw.strip().split(' "', 1)[0].strip("<>")
            if not link or link.startswith("#") or re.match(r"^[a-zA-Z][\w+.-]*:", link):
                continue
            target = (doc.parent / link.split("#", 1)[0]).resolve()
            if not target.is_relative_to(root):
                raise SkillError(f"Reference leaves skill folder: {doc}: {raw}")
            if not target.exists():
                raise SkillError(f"Broken reference: {doc}: {raw}")
    return name


def catalog(repo, names=()):
    base = repo / "skills"
    if names:
        return [base / valid_name(n) for n in dict.fromkeys(names)]
    return sorted(p for p in base.iterdir() if not p.name.startswith(".")) if base.exists() else []


def link_state(dest, source):
    if dest.is_symlink():
        return "linked" if dest.resolve() == source.resolve() else "conflict"
    return "conflict" if dest.exists() else "missing"


def status(repo, home, names=()):
    rows = []
    for source in catalog(repo, names):
        check_skill(source)
        for harness, root in harnesses(home).items():
            dest = root / source.name
            rows.append(dict(name=source.name, harness=harness, path=str(dest),
                             source=str(source), status=link_state(dest, source)))
    return rows


@contextmanager
def locked(repo):
    with (repo / ".skills.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def backup_path(home, dest):
    root = home / ".local/state/personal-skills/backups"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return root / f"{stamp}-{dest.name}-{uuid.uuid4().hex[:8]}"


def install(repo, home, names=(), replace=False, dry_run=False):
    rows = status(repo, home, names)
    conflicts = [r for r in rows if r["status"] == "conflict"]
    if conflicts and not replace:
        raise SkillError("Conflicts; nothing changed. Inspect paths or use --replace to back them up:\n" +
                         "\n".join(r["path"] for r in conflicts))
    if dry_run:
        return rows
    # Roll back links and restore displaced entries if any operation fails.
    changes = []
    try:
        for row in rows:
            if row["status"] == "linked":
                continue
            dest, source = Path(row["path"]), Path(row["source"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            backup = None
            if row["status"] == "conflict":
                backup = backup_path(home, dest)
                dest.rename(backup)
                row["backup"] = str(backup)
            changes.append((dest, source, backup))
            dest.symlink_to(source, target_is_directory=True)
            row["status"] = "linked"
    except OSError:
        for dest, source, backup in reversed(changes):
            if dest.is_symlink() and dest.resolve() == source.resolve():
                dest.unlink()
            if backup is not None:
                backup.rename(dest)
        raise
    return rows


def uninstall(repo, home, names, dry_run=False):
    rows = status(repo, home, names)
    for row in rows:
        if row["status"] == "linked":
            if not dry_run:
                Path(row["path"]).unlink()
            row["status"] = "would unlink" if dry_run else "unlinked"
        else:
            row["status"] = "preserved " + row["status"]
    return rows


def import_skill(repo, source, name=None):
    source = source.expanduser().resolve()
    data, body = frontmatter(source / "SKILL.md")
    name = valid_name(name or data.get("name", ""))
    target = repo / "skills" / name
    if target.exists() or target.is_symlink():
        raise SkillError(f"Catalog destination already exists; compare/edit it explicitly: {target}")
    check_skill(source, expected=data["name"])
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".import-", dir=target.parent) as temp:
        staged = Path(temp) / name
        shutil.copytree(source, staged, ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store"))
        if data["name"] != name:
            old_name = data["name"]
            data["name"] = name
            (staged / "SKILL.md").write_text(
                "---\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False) + "---\n" + body,
                encoding="utf-8")
            # Codex invocation metadata must follow a renamed technical ID.
            ui = staged / "agents/openai.yaml"
            if ui.exists():
                ui.write_text(ui.read_text().replace("$" + old_name, "$" + name), encoding="utf-8")
        check_skill(staged)
        staged.rename(target)
    return dict(name=name, source=str(source), path=str(target), status="imported")


def fingerprint(path):
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file() and not item.is_symlink() and ".git" not in item.relative_to(path).parts:
            digest.update(str(item.relative_to(path)).encode())
            digest.update(b"\0")
            digest.update(item.read_bytes())
    return digest.hexdigest()


def scan(repo, home):
    roots = {**harnesses(home), "agents-shared": home / ".agents/skills", "catalog": repo / "skills"}
    rows = []
    for harness, root in roots.items():
        if not root.is_dir():
            continue
        # Follow skill-root symlinks, but never crawl symlinked containers or internal trees.
        candidates = set()
        for current, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
            if "SKILL.md" in files:
                candidates.add(Path(current))
                dirs[:] = []
            else:
                for d in list(dirs):
                    p = Path(current) / d
                    if p.is_symlink() and (p / "SKILL.md").is_file():
                        candidates.add(p)
                        dirs.remove(d)
        for path in sorted(candidates):
            try:
                data, _ = frontmatter(path / "SKILL.md")
                resolved = path.resolve()
                rows.append(dict(name=data.get("name", path.name), harness=harness, path=str(path),
                                 source=str(resolved), hash=fingerprint(resolved), status="found"))
            except (SkillError, OSError, UnicodeError) as exc:
                rows.append(dict(path=str(path), harness=harness, status="invalid", error=str(exc)))
    hashes = {}
    for row in rows:
        if "hash" in row:
            hashes.setdefault(row["name"], set()).add(row["hash"])
    for row in rows:
        if "hash" in row:
            row["diverged"] = len(hashes[row["name"]]) > 1
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--home", type=Path, default=Path.home(), help="Override harness home (also for isolated tests)")
    parser.add_argument("--json", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scan", help="Inventory skills; flag differing definitions of the same name")
    for cmd in ("status", "check", "install", "uninstall"):
        p = commands.add_parser(cmd)
        p.add_argument("names", nargs="+" if cmd == "uninstall" else "*")
        if cmd in ("install", "uninstall"):
            p.add_argument("--dry-run", action="store_true")
        if cmd == "install":
            p.add_argument("--replace", action="store_true", help="Back up conflicting destinations before linking")
    p = commands.add_parser("import", help="Copy a complete skill into the catalog; source is preserved")
    p.add_argument("source", type=Path)
    p.add_argument("--name", help="New technical name (update body/display name separately)")
    args = parser.parse_args(argv)
    repo, home = args.repo.expanduser().resolve(), args.home.expanduser().resolve()
    try:
        if args.command == "scan":
            result = scan(repo, home)
        elif args.command == "check":
            result = [dict(name=check_skill(p), status="valid") for p in catalog(repo, args.names)]
        elif args.command == "status":
            result = status(repo, home, args.names)
        else:
            with locked(repo):
                if args.command == "import":
                    result = [import_skill(repo, args.source, args.name)]
                elif args.command == "install":
                    result = install(repo, home, args.names, args.replace, args.dry_run)
                else:
                    result = uninstall(repo, home, args.names, args.dry_run)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for row in result:
                print(" | ".join(f"{k}={v}" for k, v in row.items() if k != "hash"))
        if any(r.get("status") in ("missing", "conflict", "invalid") or r.get("diverged") for r in result):
            return 2
        return 0
    except (SkillError, OSError, UnicodeError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
