"""Small offline checks; they never load or alter a model."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parent.parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


overlay = load("overlay", PROJECT / "tools/install_overlay.py")
models = load("models", PROJECT / "tools/verify_models.py")
download = load("download", PROJECT / "tools/download_models.py")
svg = load("svg", PROJECT / "benchmark/extract_svg.py")


class ToolTests(unittest.TestCase):
    def test_overlay_checks_before_copy_and_preserves_conflicts(self):
        with tempfile.TemporaryDirectory(dir=PROJECT) as directory:
            root = Path(directory).resolve()
            self.assertEqual(root.parent, PROJECT.resolve())
            src = root / "source"; dst = root / "target"
            src.mkdir(); dst.mkdir()
            (src / "file.txt").write_bytes(b"abc")
            entries = [{"path": "file.txt", "bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}]
            self.assertTrue(overlay.install(src, dst, entries, True)["ok"])
            self.assertFalse((dst / "file.txt").exists())
            self.assertEqual(overlay.install(src, dst, entries)["written"], 1)
            (dst / "file.txt").write_bytes(b"xyz")
            self.assertEqual(overlay.install(src, dst, entries)["conflicts"], ["file.txt"])
            self.assertEqual((dst / "file.txt").read_bytes(), b"xyz")
            with self.assertRaises(ValueError): overlay.safe_path(dst, "../outside")

    def test_model_verification_and_markers(self):
        with tempfile.TemporaryDirectory(dir=PROJECT) as directory:
            root = Path(directory).resolve()
            self.assertEqual(root.parent, PROJECT.resolve())
            file = root / "file.gguf"; file.write_bytes(b"abc")
            entries = [{"path": file.name, "bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}]
            self.assertEqual(models.verify(root, entries), [])
            self.assertEqual(models.markers(root, entries), 1)
            self.assertEqual(models.markers(root, entries), 0)
            marker = root / "file.gguf.done"; marker.write_text("unexpected", encoding="utf-8")
            with self.assertRaises(RuntimeError): models.markers(root, entries)
            self.assertEqual(marker.read_text(encoding="utf-8"), "unexpected")
            file.write_bytes(b"xyz")
            self.assertEqual(models.verify(root, entries)[0]["error"], "sha256_mismatch")

    def test_svg_extraction_rejects_active_or_external_content(self):
        good = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="1"/></svg>'
        self.assertEqual(svg.extract("text " + good), good)
        for bad in (
            '<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/x"/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg" onload="x()"></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="url(https://example.com/x)"/></svg>',
        ):
            with self.assertRaises(ValueError): svg.extract(bad)

    def test_download_mapping_and_preservation(self):
        name = "DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XS-00001-of-00004.gguf"
        self.assertIn("cb02422c900df489cea5833e8a92171224059b3c/" + name,
                      download.model_url("https://hf-mirror.com", name))
        with self.assertRaises(ValueError): download.model_url("https://hf-mirror.com", "unknown.gguf")
        with tempfile.TemporaryDirectory(dir=PROJECT) as directory:
            root = Path(directory).resolve()
            self.assertEqual(root.parent, PROJECT.resolve())
            file = root / name
            entry = {"path": name, "bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}
            file.write_bytes(b"abc")
            download.download_one(root, entry, "https://hf-mirror.com")
            file.write_bytes(b"xyz")
            with self.assertRaises(RuntimeError): download.download_one(root, entry, "https://hf-mirror.com")
            self.assertEqual(file.read_bytes(), b"xyz")
            file.unlink()
            old_partial = root / (name + ".part"); old_partial.write_bytes(b"partial")
            with self.assertRaises(RuntimeError): download.download_one(root, entry, "https://hf-mirror.com")
            self.assertEqual(old_partial.read_bytes(), b"partial")

    def test_download_resumes_and_keeps_failed_partial(self):
        name = "DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XS-00001-of-00004.gguf"
        entry = {"path": name, "bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}
        with tempfile.TemporaryDirectory(dir=PROJECT) as directory:
            root = Path(directory).resolve()
            self.assertEqual(root.parent, PROJECT.resolve())
            part = root / (name + ".repro-part"); part.write_bytes(b"a")
            record = root / (name + ".repro-source.json")
            record.write_text(json.dumps({"url": download.model_url("https://hf-mirror.com", name),
                                          "bytes": 3, "sha256": entry["sha256"]}), encoding="utf-8")
            with patch.object(download.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
                with self.assertRaises(RuntimeError): download.download_one(root, entry, "https://hf-mirror.com")
            self.assertEqual(part.read_bytes(), b"a")
            self.assertFalse((root / name).exists())
            def resume(command, check=False):
                self.assertIn("--continue-at", command)
                with part.open("ab") as f: f.write(b"bc")
                return SimpleNamespace(returncode=0)
            with patch.object(download.subprocess, "run", side_effect=resume):
                download.download_one(root, entry, "https://hf-mirror.com")
            self.assertEqual((root / name).read_bytes(), b"abc")
            self.assertFalse(part.exists())


if __name__ == "__main__": unittest.main()
