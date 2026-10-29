"""Check the actual target model bytes against the recorded pinned model hashes."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

spec = importlib.util.spec_from_file_location("install_overlay", Path(__file__).with_name("install_overlay.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
digest, safe_path = module.digest, module.safe_path

PROJECT = Path(__file__).resolve().parent.parent


def verify(root, entries):
    failures = []
    for index, entry in enumerate(entries, 1):
        path = safe_path(root, entry["path"])
        print(f"[{index}/{len(entries)}] {entry['path']}", flush=True)
        if not path.is_file():
            failures.append({"path": entry["path"], "error": "missing"})
        elif path.stat().st_size != entry["bytes"]:
            failures.append({"path": entry["path"], "error": "size_mismatch"})
        elif digest(path) != entry["sha256"]:
            failures.append({"path": entry["path"], "error": "sha256_mismatch"})
    return failures


def markers(root, entries):
    pending = []
    for entry in entries:
        marker = safe_path(root, entry["path"] + ".done")
        expected = "sha256 " + entry["sha256"]
        if marker.exists():
            if not marker.is_file() or marker.read_text(encoding="utf-8-sig").strip().lower() != expected:
                raise RuntimeError("Existing marker differs; preserved: " + str(marker))
        else:
            pending.append((marker, expected))
    for marker, expected in pending:
        with marker.open("x", encoding="utf-8", newline="\n") as f: f.write(expected + "\n")
    return len(pending)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(r"F:\STRATA"))
    parser.add_argument("--write-markers", action="store_true")
    args = parser.parse_args()
    if os.name != "nt" or os.path.normcase(str(args.root.absolute())) != os.path.normcase(r"F:\STRATA"):
        raise SystemExit("The model layout is fixed at F:\\STRATA on Windows.")
    manifest = json.loads((PROJECT / "reproduction" / "manifest.json").read_text(encoding="utf-8-sig"))
    started = time.monotonic()
    errors = verify(args.root, manifest["model_files"])
    count = markers(args.root, manifest["model_files"]) if not errors and args.write_markers else 0
    print(json.dumps({"passed": not errors, "errors": errors, "markers_created": count,
                      "elapsed_seconds": round(time.monotonic() - started, 2)}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__": sys.exit(main())
