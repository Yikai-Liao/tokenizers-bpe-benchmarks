"""Small configuration tests; no runner, corpus preprocessing or timing."""

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from bench.config import identity, load, read, write
from scripts import prepare_bytelevel_matrix as matrix


class CpuSelectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.topology_root = Path(temporary.name)

    def topology(self, cpus):
        for cpu, core_key in cpus.items():
            directory = self.topology_root / f"cpu{cpu}" / "topology"
            directory.mkdir(parents=True)
            (directory / "physical_package_id").write_text(str(core_key[0]), encoding="ascii")
            (directory / "core_id").write_text(str(core_key[-1]), encoding="ascii")
            siblings = sorted(sibling for sibling, key in cpus.items() if key == core_key)
            # Exercise both sysfs single IDs and range/list syntax.
            value = (f"{siblings[0]}-{siblings[-1]}" if len(siblings) > 1
                     and siblings == list(range(siblings[0], siblings[-1] + 1))
                     else ",".join(map(str, siblings)))
            (directory / "thread_siblings_list").write_text(value, encoding="ascii")

    def select(self, workers, allowed):
        with patch.object(matrix.os, "sched_getaffinity", return_value=set(allowed)) as affinity:
            result = matrix.select_cpus(workers, topology_root=self.topology_root)
            affinity.assert_called_once_with(0)
            return result

    def test_default_uses_one_available_cpu_per_physical_core(self):
        self.topology({cpu: (0, cpu // 2) for cpu in range(8)})
        self.assertEqual(self.select([1, 4], range(8)), [0, 2, 4, 6])

    def test_noncontiguous_affinity_can_select_only_available_siblings(self):
        self.topology({0: (0, 0), 1: (0, 0), 2: (0, 1), 3: (0, 1),
                       8: (0, 2), 10: (0, 2)})
        self.assertEqual(self.select([1, 3], [10, 3, 8, 1]), [1, 3, 8])

    def test_same_core_id_on_different_packages_is_distinct(self):
        self.topology({0: (0, 0), 1: (1, 0), 2: (0, 0), 3: (1, 0),
                       4: (0, 1), 5: (1, 1)})
        self.assertEqual(self.select([4], range(6)), [0, 1, 4, 5])

    def test_insufficient_physical_cores_require_explicit_worker_choice(self):
        self.topology({cpu: (0, cpu // 2) for cpu in range(8)})
        with self.assertRaisesRegex(ValueError, "only 4 physical cores.*reduce --workers.*--cpu-set"):
            self.select([1, 4, 8], range(8))

    def test_missing_topology_does_not_assume_physical_cores(self):
        with self.assertRaisesRegex(ValueError, "physical topology.*CPU 2.*--cpu-set"):
            self.select([1], [2])

    def test_repeated_core_ids_across_dies_are_distinct(self):
        self.topology({0: (0, 0, 0), 1: (0, 0, 0),
                       2: (0, 1, 0), 3: (0, 1, 0)})
        self.assertEqual(self.select([2], range(4)), [0, 2])

    def test_invalid_or_incomplete_topology_requires_explicit_allocation(self):
        self.topology({2: (0, 1)})
        siblings = self.topology_root / "cpu2" / "topology" / "thread_siblings_list"
        for value in ["unknown", "", "3", "2-1", "-1", "2,,3", "2,2", "2-3,3"]:
            with self.subTest(value=value):
                siblings.write_text(value, encoding="ascii")
                with self.assertRaisesRegex(ValueError, "physical topology.*CPU 2.*--cpu-set"):
                    self.select([1], [2])

    def test_inconsistent_sibling_lists_require_explicit_allocation(self):
        self.topology({0: (0, 0), 1: (0, 0)})
        (self.topology_root / "cpu1" / "topology" / "thread_siblings_list").write_text("1", encoding="ascii")
        with self.assertRaisesRegex(ValueError, "physical topology.*CPU 1.*--cpu-set"):
            self.select([1], [0, 1])

    def test_missing_topology_is_checked_beyond_requested_prefix(self):
        self.topology({0: (0, 0)})
        with self.assertRaisesRegex(ValueError, "physical topology.*CPU 2.*--cpu-set"):
            self.select([1], [0, 2])

    def test_explicit_override_keeps_order_and_may_include_smt(self):
        cpus = [3, 2, 0, 1]
        with patch.object(matrix.os, "sched_getaffinity", side_effect=AssertionError("explicit set must bypass topology")):
            self.assertEqual(matrix.select_cpus([1, 4], cpus, topology_root=self.topology_root), cpus)


class BytelevelMatrixTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.builds = {}
        for name in ("baseline", "candidate", "other"):
            request = {"files": {}, "revision": name}
            path = self.root / name / "build.json"
            write(path, dict(request=request, build_id=identity(request)))
            self.builds[name] = path
        self.manifests = {}
        for language in ("zh", "en"):
            # The raw path deliberately does not exist. Default generation must
            # read metadata only and leave full content verification to run.
            record = dict(
                schema_version=1,
                kind="text",
                path=f"{language}.txt",
                sha256=language,
                bytes=42,
                line_protocol="UTF-8 lines; remove LF and optional CR",
            )
            record["input_id"] = identity(
                {key: value for key, value in record.items() if key != "path"}
            )
            path = self.root / f"{language}.json"
            write(path, record)
            self.manifests[language] = path
        self.out = self.root / "plans"

    def generate(self, **options):
        return matrix.generate(
            self.builds["baseline"].parent,
            {name: self.builds[name] for name in ("candidate", "other")},
            self.manifests["zh"],
            self.manifests["en"],
            self.out,
            cpu_set=list(range(8)),
            **options,
        )

    @patch("bench.config.os.sched_getaffinity", return_value=set(range(8)))
    @patch.object(matrix, "prepare_core_input")
    def test_standard_matrix_uses_shared_baseline_without_preparing_input(self, prepare, _):
        originals = {path: path.read_bytes() for path in self.manifests.values()}
        paths = self.generate()
        prepare.assert_not_called()
        for mode, path in paths.items():
            cfg = load(path)
            self.assertEqual(cfg["mode"], mode)
            self.assertEqual(cfg["comparison"], "exact-model")
            self.assertEqual(set(cfg["arms"]), {"baseline", "candidate", "other"})
            self.assertEqual(
                cfg["arms"]["baseline"]["build"], str(self.builds["baseline"])
            )
            self.assertEqual(cfg["execution"]["workers"], [1, 4, 8])
            self.assertEqual(cfg["execution"]["paired_blocks"], 3)
            self.assertEqual(cfg["execution"]["warmups_per_cell"], 1)
            self.assertEqual(cfg["execution"]["order"], "balanced-alternating")
            self.assertEqual(len(cfg["cases"]), 8 if mode == "core" else 6)
            for language in ("zh", "en"):
                cases = [
                    case for case in cfg["cases"]
                    if case["name"].startswith(f"{language}-vocab-")
                ]
                self.assertEqual(
                    [case["trainer"]["vocab_size"] for case in cases],
                    [32_000, 50_000, 65_536],
                )
                self.assertTrue(
                    all(case["pretokenizer"] == "bytelevel_regex" for case in cases)
                )
                expected = (
                    self.manifests[language]
                    if mode == "pipeline"
                    else self.out / "inputs" / f"{language}-bytelevel" / "manifest.json"
                )
                self.assertTrue(
                    all(case["input_manifest"] == str(expected) for case in cases)
                )
                if mode == "core":
                    affix = next(
                        case for case in cfg["cases"]
                        if case["name"] == f"{language}-affix-both-vocab-32000"
                    )
                    self.assertEqual(affix["trainer"]["prefix"], "##")
                    self.assertEqual(affix["trainer"]["suffix"], "</w>")
                    self.assertEqual(affix["input_manifest"], str(expected))
                else:
                    self.assertTrue(
                        all(
                            case["trainer"]["prefix"] is None
                            and case["trainer"]["suffix"] is None
                            for case in cfg["cases"]
                        )
                    )
        self.assertFalse((self.out / "inputs").exists())
        for path, content in originals.items():
            self.assertEqual(path.read_bytes(), content)

    @patch("bench.config.os.sched_getaffinity", return_value=set(range(8)))
    @patch.object(matrix, "select_cpus", return_value=[0, 2, 4, 6])
    def test_generated_defaults_use_the_selected_physical_allocation(self, select, _):
        paths = matrix.generate(
            self.builds["baseline"], {"candidate": self.builds["candidate"]},
            self.manifests["zh"], self.manifests["en"], self.out,
            workers=[1, 4],
        )
        select.assert_called_once_with([1, 4], None)
        for path in paths.values():
            self.assertEqual(load(path)["execution"]["cpu_set"], [0, 2, 4, 6])

    @patch("bench.config.os.sched_getaffinity", return_value=set(range(8)))
    @patch.object(matrix, "prepare_core_input")
    def test_explicit_prepare_uses_only_baseline_and_one_input_per_language(self, prepare, _):
        self.generate(prepare_core=True)
        self.assertEqual(prepare.call_count, 2)
        for language in ("zh", "en"):
            prepare.assert_any_call(
                str(self.manifests[language]),
                str(self.builds["baseline"]),
                self.out / "inputs" / f"{language}-bytelevel",
            )

    @patch.object(matrix.inputs, "prepared")
    @patch.object(
        matrix.inputs, "validate", return_value={"data_path": "/verified/text.txt"}
    )
    def test_preparation_delegates_to_canonical_input_contract(self, validate, prepare):
        matrix.prepare_core_input("text.json", "baseline.json", self.out)
        validate.assert_called_once_with("text.json", "pipeline", "bytelevel_regex")
        prepare.assert_called_once_with(
            "/verified/text.txt", "bytelevel_regex", "baseline.json", self.out
        )

    @patch("bench.config.os.sched_getaffinity", return_value=set(range(8)))
    def test_repeat_is_idempotent_and_changed_plan_does_not_overwrite(self, _):
        paths = self.generate()
        originals = {path: path.read_bytes() for path in paths.values()}
        self.generate()
        with self.assertRaisesRegex(ValueError, "configuration changed"):
            self.generate(vocab_sizes=[32_000])
        for path, content in originals.items():
            self.assertEqual(path.read_bytes(), content)

    @patch("bench.config.os.sched_getaffinity", return_value=set(range(8)))
    @patch.object(matrix, "prepare_core_input")
    def test_invalid_cpu_plan_is_rejected_before_output_or_preparation(self, prepare, _):
        with self.assertRaisesRegex(ValueError, "workers must fit"):
            self.generate(workers=[9], prepare_core=True)
        self.assertFalse(self.out.exists())
        prepare.assert_not_called()

    @patch("bench.config.os.sched_getaffinity", return_value=set(range(8)))
    def test_optional_single_affixes_use_first_target_and_shared_inputs(self, _):
        paths = self.generate(vocab_sizes=[50_000], affixes=tuple(matrix.AFFIXES))
        for mode, path in paths.items():
            cfg = load(path)
            self.assertEqual(len(cfg["cases"]), 8 if mode == "core" else 2)
            for language in ("zh", "en"):
                cases = [
                    case for case in cfg["cases"]
                    if case["name"].startswith(language)
                ]
                self.assertEqual(len({case["input_manifest"] for case in cases}), 1)
                self.assertEqual(
                    {(case["trainer"]["prefix"], case["trainer"]["suffix"])
                     for case in cases},
                    (
                        {(None, None), ("##", None), (None, "</w>"), ("##", "</w>")}
                        if mode == "core" else {(None, None)}
                    ),
                )
                self.assertTrue(
                    all(case["trainer"]["vocab_size"] == 50_000 for case in cases)
                )

    def test_stale_input_metadata_is_rejected_without_reading_raw_text(self):
        manifest = self.manifests["zh"]
        record = read(manifest)
        record["bytes"] += 1
        write(manifest, record)
        with self.assertRaisesRegex(ValueError, "input manifest identity mismatch"):
            matrix.text_reference(manifest)

    def test_stale_build_metadata_is_rejected(self):
        build = self.builds["baseline"]
        record = read(build)
        record["request"]["revision"] = "changed"
        write(build, record)
        with self.assertRaisesRegex(ValueError, "build provenance identity mismatch"):
            matrix.build_reference(build)

    @patch.object(matrix, "generate", return_value={})
    def test_cli_combines_candidate_with_named_arms(self, generate):
        with redirect_stdout(StringIO()):
            matrix.main([
                "--baseline", str(self.builds["baseline"]),
                "--candidate", str(self.builds["candidate"]),
                "--arm", f"other={self.builds['other']}",
                "--zh-manifest", str(self.manifests["zh"]),
                "--en-manifest", str(self.manifests["en"]),
                "--out", str(self.out),
                "--workers", "1", "4",
                "--cpu-set", "0", "1", "2", "3",
            ])
        args, options = generate.call_args
        self.assertEqual(
            args[1], {name: self.builds[name] for name in ("candidate", "other")}
        )
        self.assertEqual(options["workers"], [1, 4])
        self.assertEqual(options["cpu_set"], [0, 1, 2, 3])
        self.assertFalse(options["prepare_core"])


if __name__ == "__main__":
    unittest.main()
