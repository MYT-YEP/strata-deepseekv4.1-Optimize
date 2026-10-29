"""Fetch the eight pinned model files while preserving all incomplete files."""
import argparse
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse

PROJECT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("install_overlay", Path(__file__).with_name("install_overlay.py"))
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
digest, safe_path = module.digest, module.safe_path
ISTA = "ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF/resolve/cb02422c900df489cea5833e8a92171224059b3c"
UNSLOTH = "unsloth/DeepSeek-V4.1-Flash-1017-GGUF/resolve/f924b94f19c1fea02c06a65c8475b0a45e2b88b1"


def model_url(endpoint, filename):
    if filename.startswith("DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XS-") or filename == "DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf":
        return endpoint + "/" + ISTA + "/" + filename
    if filename in ("dspark-DeepSeek-V4.1-Flash-1017-Q8_0.gguf", "mmproj-BF16.gguf"):
        return endpoint + "/" + UNSLOTH + "/" + filename
    if filename == "DeepSeek-V4.1-Flash-1017-UD-Q8_K_XL-00001-of-00009.gguf":
        return endpoint + "/" + UNSLOTH + "/UD-Q8_K_XL/" + filename
    raise ValueError("Unexpected model name: " + filename)


@contextlib.contextmanager
def lock_models(root):
    import msvcrt
    path = safe_path(root, "data/models/.repro-download.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as f:
        if f.seek(0, os.SEEK_END) == 0:
            f.write(b"0"); f.flush()
        f.seek(0)
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("Another copy of this downloader is active.") from exc
        try:
            yield
        finally:
            f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def download_one(root, entry, endpoint):
    dest = safe_path(root, entry["path"])
    url = model_url(endpoint, dest.name)
    part = safe_path(root, entry["path"] + ".repro-part")
    source_record = safe_path(root, entry["path"] + ".repro-source.json")
    old_part = safe_path(root, entry["path"] + ".part")
    if dest.exists():
        if not dest.is_file() or dest.stat().st_size != entry["bytes"] or digest(dest) != entry["sha256"]:
            raise RuntimeError("Existing model differs; file preserved: " + str(dest))
        print("Already verified:", dest.name, flush=True)
        return
    if old_part.exists():
        raise RuntimeError("A different downloader's partial file exists; do not start a duplicate: " + str(old_part))
    expected = {"url": url, "sha256": entry["sha256"], "bytes": entry["bytes"]}
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source_record.exists():
        if json.loads(source_record.read_text(encoding="utf-8")) != expected:
            raise RuntimeError("Partial source record differs; files preserved: " + str(source_record))
    elif part.exists():
        raise RuntimeError("Partial file has no matching source record; file preserved: " + str(part))
    else:
        with source_record.open("x", encoding="utf-8") as f: json.dump(expected, f, indent=2)
    size = part.stat().st_size if part.exists() else 0
    if size > entry["bytes"]: raise RuntimeError("Partial file is too large; preserved: " + str(part))
    if size < entry["bytes"]:
        command = ["curl.exe", "--noproxy", "*", "--location", "--fail", "--retry", "3",
                   "--connect-timeout", "20", "--continue-at", "-", "--proto", "=https",
                   "--proto-redir", "=https", "--output", str(part), url]
        print("Fetching or resuming:", dest.name, flush=True)
        if subprocess.run(command, check=False).returncode:
            raise RuntimeError("Download interrupted; partial file and source record preserved: " + str(part))
    if not part.is_file() or part.stat().st_size != entry["bytes"] or digest(part) != entry["sha256"]:
        raise RuntimeError("Downloaded file failed verification; preserved: " + str(part))
    # On Windows rename fails if the destination appeared while the download was running.
    part.rename(dest)
    print("Verified:", dest.name, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(r"F:\STRATA"))
    parser.add_argument("--endpoint", default="https://hf-mirror.com")
    parser.add_argument("--dry-run", action="store_true", help="print pinned sources without downloading or writing")
    args = parser.parse_args()
    endpoint = args.endpoint.rstrip("/")
    parsed = urlparse(endpoint)
    if (parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise SystemExit("Endpoint must be an HTTPS origin without path or query.")
    if os.name != "nt" or os.path.normcase(str(args.root.absolute())) != os.path.normcase(r"F:\STRATA"):
        raise SystemExit("This model layout is fixed at F:\\STRATA on Windows.")
    if args.root.exists() and (args.root.is_symlink() or (hasattr(args.root, "is_junction") and args.root.is_junction())):
        raise SystemExit("Target root is a link; preserving it.")
    entries = json.loads((PROJECT / "reproduction/manifest.json").read_text(encoding="utf-8-sig"))["model_files"]
    if args.dry_run:
        for entry in entries:
            print(json.dumps({"path": entry["path"], "bytes": entry["bytes"],
                              "url": model_url(endpoint, Path(entry["path"]).name)}, ensure_ascii=False))
        return 0
    if not args.root.parent.is_dir(): raise SystemExit("F: is unavailable.")
    with lock_models(args.root):
        for entry in entries: download_one(args.root, entry, endpoint)
    print("All eight files verified. Run verify_models.py --write-markers before launch.", flush=True)
    return 0


if __name__ == "__main__": sys.exit(main())
