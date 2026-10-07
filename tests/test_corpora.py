"""Batch preparation and actual Parquet extraction; no remote downloads."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bench.config import ROOT, digest, read, write
from bench.corpora import prepare
from bench.inputs import corpus

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    pa = pq = None


class BatchTests(unittest.TestCase):
    def test_exported_plan_resolves_manifests_bundled_in_image(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = root / "corpora.toml"
            plan.write_bytes((ROOT / "datasets/corpora.toml").read_bytes())
            def extract(path, size, destination, cache, allow_short):
                self.assertEqual(path.parent, ROOT / "datasets")
                destination.mkdir(parents=True)
                (destination / "text.txt").write_text("fixture\n")
                return dict(input_id="id", sha256="sha", bytes=8,
                    availability=dict(requested_bytes=size << 20, actual_bytes=8, status="source_exhausted"))
            with patch("bench.corpora.corpus", side_effect=extract) as run, patch("builtins.print"):
                prepare(plan, root / "data", root / "cache", size_mib=1)
            self.assertEqual(run.call_count, 3)

    def test_one_command_prepares_all_names_and_records_short_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dataset = root / "dataset.json"
            write(dataset, {"schema_version": 1})
            plan = root / "corpora.json"
            write(plan, dict(schema_version=1, size_mib=32769, corpora=[
                dict(name=n, dataset="dataset.json") for n in ("en", "zh", "code")]))
            def extract(path, size, destination, cache, allow_short):
                self.assertEqual(size, 2)
                self.assertTrue(allow_short)
                destination.mkdir(parents=True)
                (destination / "text.txt").write_text("fixture\n")
                return dict(input_id="id", sha256="sha", bytes=8,
                    availability=dict(requested_bytes=2 << 20, actual_bytes=8, status="source_exhausted"))
            with patch("bench.corpora.corpus", side_effect=extract), patch("builtins.print"):
                summary = prepare(plan, root / "data", root / "cache", size_mib=2)
            self.assertTrue(summary["complete"])
            self.assertEqual([r["name"] for r in summary["corpora"]], ["en", "zh", "code"])
            for name in ("en", "zh", "code"):
                self.assertEqual((root / "data" / f"{name}.txt").read_text(), "fixture\n")
            self.assertEqual(read(root / "data/corpora.json"), summary)


@unittest.skipIf(pa is None, "optional corpus dependency; exercised in Docker CI")
class ParquetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def dataset(self, name, table, **extra):
        path = self.root / f"{name}.parquet"
        pq.write_table(table, path)
        manifest = self.root / f"{name}.json"
        write(manifest, dict(schema_version=1, shards=[dict(url=path.as_uri(),
            bytes=path.stat().st_size, sha256=digest(path))], **extra))
        return manifest

    def test_short_source_is_retained_and_resumes_with_verified_identity(self):
        line = "A representative sentence with punctuation, digits 123 and enough length."
        manifest = self.dataset("en", pa.table({"text": [line]}))
        record = corpus(manifest, 1, self.root / "partial", self.root / "cache", allow_short=True)
        self.assertEqual(record["availability"]["status"], "source_exhausted")
        self.assertEqual((self.root / "partial/text.txt").read_text(), line + "\n")
        retained = corpus(manifest, 1, self.root / "partial", self.root / "cache", allow_short=True)
        self.assertEqual(retained["input_id"], record["input_id"])
        with self.assertRaisesRegex(ValueError, "cannot supply"):
            corpus(manifest, 1, self.root / "strict", self.root / "cache")

    def test_code_indentation_and_license_counts_survive_short_source(self):
        code = "def tokenize(text):\n    return text.split()  # preserve indentation\n"
        manifest = self.dataset("code", pa.table(dict(code=[code, "excluded"],
            path=["example.py", "notes.txt"], license=["mit", "unknown"])),
            transformation="code", languages={"Python": [".py"]})
        record = corpus(manifest, 1, self.root / "code", self.root / "cache", allow_short=True)
        self.assertEqual((self.root / "code/text.txt").read_text(), code)
        self.assertEqual(record["language_files"], {"Python": 1})
        self.assertEqual(record["license_files"], {"mit": 1})
        self.assertEqual(record["availability"]["status"], "source_exhausted")

    def test_target_controls_text_bytes_after_parquet_decompression(self):
        line = "A representative sentence with punctuation, digits 123 and enough length."
        manifest = self.dataset("full", pa.table({"text": [line] * 16000}))
        record = corpus(manifest, 1, self.root / "full", self.root / "cache", allow_short=True)
        self.assertLessEqual(record["bytes"], 1 << 20)
        self.assertGreaterEqual(record["bytes"], (1 << 20) - 8192)
        self.assertEqual(record["availability"]["status"], "target_reached")
        self.assertTrue((self.root / "full/text.txt").read_bytes().endswith(b"\n"))


if __name__ == "__main__":
    unittest.main()
