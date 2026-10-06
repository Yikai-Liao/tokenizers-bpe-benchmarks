"""Benchmark-only leaf substitutions, derived from one immutable Full source.

These recipes never modify a checkout.  Every edit checks its expected anchor;
when production interfaces change, preparation stops until the recipe is ported.
"""

from pathlib import Path

FULL_ARMS = (
    "full", "no_radix", "one_rule", "flat64", "u32_corpus",
    "eager_corpus", "no_position_arena", "scalar_weights", "dual_strings",
)


def replace(path: Path, before: str, after: str, count: int = 1) -> None:
    text = path.read_text()
    actual = text.count(before)
    if actual != count:
        raise ValueError(f"{path.name}: expected {count} anchors, found {actual}: {before[:80]!r}")
    path.write_text(text.replace(before, after))


def function_body(text: str, marker: str) -> tuple[int, int]:
    """Find a small known Rust function's body; braces in these markers are code."""
    if text.count(marker) != 1:
        raise ValueError(f"function anchor changed: {marker}")
    begin = text.index("{", text.index(marker))
    depth = 1
    end = begin + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return begin + 1, end - 1


def substitute(root: Path, arm: str, templates: Path) -> str:
    engine = root / "tk-train/src/trainers/bpe/engine"
    collections = root / "tk-collections/src"
    if arm == "full":
        return "Unchanged Full training implementation."
    if arm == "no_radix":
        replace(engine / "initial_pairs.rs", "radix::sort_by_key(records);",
                "records.sort_by_key(|record| record.key());")
        replace(engine / "initial_pairs.rs", "radix::sort_by_key(&mut records);",
                "records.sort_by_key(|record| record.key());")
        return "Stable comparison sorting; same cached full keys, records, waves, and filtering."
    if arm == "one_rule":
        replace(engine / "mod.rs", "256.min(trainer.vocab_size - vocabulary.len())", "1")
        return "At most one certified rule per round; Fresh pruning and Reusable semantics retained."
    if arm == "u32_corpus":
        replace(engine / "mod.rs", "match corpus::slot_bits(trainer.vocab_size.max(vocabulary.len())) {",
                "match { let _ = corpus::slot_bits(trainer.vocab_size.max(vocabulary.len())); 32 } {")
        return "U32 slots only; same endpoints, deferred construction, and position codec."
    if arm == "no_position_arena":
        replace(collections / "arena.rs",
                "cutoff: ((physical_items as u128 / 256).isqrt() as usize).max(256),",
                "cutoff: { let _ = physical_items; 0 },")
        return "Zero small-allocation cutoff; same leases, locks, inline lists, codec, and scratch."
    if arm == "eager_corpus":
        replace(engine / "corpus.rs",
                "#[cfg(test)]\nimpl<S: SlotStorage> InitialPairSource for &Corpus<S> {",
                "impl<S: SlotStorage> InitialPairSource for &Corpus<S> {")
        path = engine / "mod.rs"
        replace(path, "let arena = AllocationArena::new(workers, prepared_corpus.initial_edges());",
                "let arena = AllocationArena::new(workers, prepared_corpus.initial_edges());\n"
                "    let mut corpus = prepared_corpus.materialize::<S>(workers, policy, progress)?;")
        replace(path, "        &prepared_corpus,\n        if policy", "        &corpus,\n        if policy")
        replace(path, "        drop(initial);\n        drop(prepared_corpus);",
                "        drop(initial);\n        drop(corpus);")
        # Only remove the original, later materialization, retaining the insertion above.
        text = path.read_text()
        line = "    let mut corpus = prepared_corpus.materialize::<S>(workers, policy, progress)?;\n"
        if text.count(line) != 2:
            raise ValueError("eager materialization anchors changed")
        at = text.rindex(line)
        path.write_text(text[:at] + text[at + len(line):])
        return "Materialize before initialization and route from identical slots; compact layout unchanged."
    if arm == "scalar_weights":
        path = engine / "initial_pairs.rs"
        replace(path,
                "    let uniform_weight =\n        (corpus.word_weights().values().len() == 1).then(|| corpus.word_weights().values()[0]);\n",
                "")
        text = path.read_text()
        begin = text.index("                        let frequency = if let Some(weight) = uniform_weight {")
        end = text.index("                        // Resident edges times u64 weights", begin)
        reference = """                        let mut frequency = 0_u64;
                        for &record in &records[begin..end] {
                            let weight = *corpus.word_weights()
                                .get(global_position(base, record))
                                .expect("every initial edge belongs to a word interval");
                            frequency = frequency.checked_add(weight)
                                .ok_or("BPE initial pair frequency exceeds u64")?;
                        }
"""
        path.write_text(text[:begin] + reference + text[end:])
        path = engine / "corpus.rs"
        text = path.read_text()
        begin, end = function_body(text, "pub(super) fn weight(&mut self, position: u64) -> u64")
        body = """
        // Keep cursor layout, but use no constant/unit-weight fast paths.
        let _ = (self.uniform_weight, self.unit_weight);
        *self.intervals.get(position).expect("a matched edge belongs to a word")
    """
        path.write_text(text[:begin] + body + text[end:])
        path = collections / "interval_index.rs"
        text = path.read_text()
        begin, end = function_body(text, "pub fn get(&mut self, position: u64) -> Option<&'a T>")
        body = """
        // Always search the immutable index; no cached-interval shortcut.
        self.current = self.index.interval_containing(position).map(|i| {
            (self.index.starts[i], self.index.starts.get(i + 1).copied(), &self.index.values[i])
        });
        self.current.map(|(_, _, value)| value)
    """
        path.write_text(text[:begin] + body + text[end:])
        return "Scalar weight accumulation and interval searches; word order and intervals unchanged."
    if arm == "dual_strings":
        path = engine / "vocabulary.rs"
        replace(path, "use indexmap::IndexSet;", "use std::ops::Index;")
        replace(path, "tokens: IndexSet<CompactString, RandomState>,", "tokens: DualStrings,")
        replace(path, "IndexSet::with_capacity_and_hasher(trainer.vocab_size, RandomState::default())",
                "DualStrings::with_capacity_and_hasher(trainer.vocab_size, RandomState::default())")
        text = path.read_text()
        marker = "pub(super) struct Vocabulary {"
        if text.count(marker) != 1:
            raise ValueError("vocabulary type changed")
        path.write_text(text.replace(marker, (templates / "dual_strings.rs").read_text() + "\n" + marker, 1))
        return "Independent owned text keys and ID-indexed text vector, with the same hasher and ID order."
    if arm == "flat64":
        path = collections / "sorted_positions.rs"
        original = path.read_text()
        # Chain merge and replay-source decisions are identical to Full.
        start = original.index("    pub fn from_chains(")
        end = original.index("    /// Append one chain", start)
        chains = original[start:end]
        start = original.index("struct DescendingMerge<I> {")
        end = original.index("/// An independent sequential decoder", start)
        merge = original[start:end]
        tests = original[original.index("#[cfg(test)]\nmod tests {"):]
        # Allocation representation is deliberately changed. Retain the behavioral
        # suite, replacing just the test's compressed-format allocation assumption.
        tests = tests.replace("for count in [180, 2048]", "for count in [16, 2048]")
        tests = tests.replace("assert_eq!(positions.payload.addr() & ARENA != 0, count == 180);",
                              "assert_eq!(positions.arena_allocated(), count == 16);")
        template = (templates / "flat_positions.rs").read_text()
        path.write_text(template.replace("// INSERT_CHAIN_METHODS", chains)
                       .replace("// INSERT_DESCENDING_MERGE", merge)
                       .replace("// INSERT_BEHAVIORAL_TESTS", tests))
        return "Flat full-width sorted coordinates; same inline cases, chain ordering, allocator, growth and publication rules."
    raise ValueError(f"unknown Full arm {arm}")
