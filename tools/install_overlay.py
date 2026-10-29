"""Install the pinned public configuration and scripts without overwriting conflicts."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys

PROJECT = Path(__file__).resolve().parent.parent
PUBLIC = PROJECT / "reproduction"


def safe_path(root, name):
    item = PurePosixPath(name)
    if item.is_absolute() or not item.parts or any(x in (".", "..") or ":" in x or "\\" in x for x in item.parts):
        raise ValueError("Unexpected manifest path: " + name)
    path = root.joinpath(*item.parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path escapes its root: " + name)
    return path


def digest(path):
    with path.open("rb") as f: return hashlib.file_digest(f, "sha256").hexdigest()


def plan(source, destination, entries):
    conflicts, missing = [], []
    for entry in entries:
        src = safe_path(source, entry["path"])
        dst = safe_path(destination, entry["path"])
        if not src.is_file() or src.stat().st_size != entry["bytes"] or digest(src) != entry["sha256"]:
            raise RuntimeError("Source snapshot is missing or damaged: " + entry["path"])
        if dst.exists():
            if not dst.is_file() or dst.stat().st_size != entry["bytes"] or digest(dst) != entry["sha256"]:
                conflicts.append(entry["path"])
        else:
            missing.append(entry)
    return conflicts, missing


def install(source, destination, entries, check_only=False):
    conflicts, missing = plan(source, destination, entries)
    if conflicts:
        return {"ok": False, "conflicts": conflicts, "written": 0}
    if not check_only:
        for entry in missing:
            src = safe_path(source, entry["path"])
            dst = safe_path(destination, entry["path"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            with src.open("rb") as inp, dst.open("xb") as out:
                shutil.copyfileobj(inp, out, 4 * 1024 * 1024)
            if digest(dst) != entry["sha256"]:
                raise RuntimeError("Copy checksum failed; file preserved: " + str(dst))
    return {"ok": True, "checked": len(entries), "missing": len(missing),
            "written": 0 if check_only else len(missing), "check_only": check_only}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(r"F:\STRATA"))
    parser.add_argument("--check", action="store_true", help="show conflicts without writing")
    args = parser.parse_args()
    if os.name != "nt" or os.path.normcase(str(args.root.absolute())) != os.path.normcase(r"F:\STRATA"):
        raise SystemExit("This snapshot has fixed Windows F:\\STRATA paths.")
    root = args.root.absolute()
    if not root.parent.is_dir(): raise SystemExit("F: is unavailable.")
    if root.exists() and (root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction())):
        raise SystemExit("Target root is a link; preserving it.")
    manifest = json.loads((PUBLIC / "manifest.json").read_text(encoding="utf-8-sig"))
    result = install(PUBLIC / "overlay", root, manifest["runtime_files"], args.check)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__": sys.exit(main())
