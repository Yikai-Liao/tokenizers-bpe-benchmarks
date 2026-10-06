//! Common, streaming feed and one public do_train call for every source arm.
use ahash::{AHashMap, RandomState};
use compact_str::CompactString;
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::{
    collections::hash_map::Entry,
    fs::File,
    io::{BufRead, BufReader, BufWriter, Write},
    time::Instant,
};
use tk_encode::{
    models::bpe::Vocab,
    pipeline::{Normalizer, PreTokenizer, PreTokenizerScratch, Span},
    pre_tokenizers::{
        byte_level::ByteLevel,
        split::{Split, SplitPattern},
        whitespace::WhitespaceSplit,
    },
    tokenizer::SplitDelimiterBehavior,
    utils::byte_level::GPT2_REGEX_STR,
};
use tk_train::BpeTrainer;

type Error = Box<dyn std::error::Error + Send + Sync>;
#[derive(Deserialize)]
struct Job {
    input: String,
    split: String,
    vocab_size: usize,
    min_frequency: u64,
    workers: usize,
    output: String,
    prefix: Option<String>,
    suffix: Option<String>,
    max_token_length: Option<usize>,
}

/// Exploration cache preserves first insertion order as well as final counts.
/// The normal streaming input remains the formal feed+training boundary.
#[derive(Deserialize, Serialize)]
struct WordCountsCache {
    version: u32,
    input: String,
    input_bytes: u64,
    split: String,
    lines: u64,
    occurrences: u64,
    ordered_words: Vec<(CompactString, u64)>,
}

fn cpu_seconds() -> Result<f64, Error> {
    let mut usage = std::mem::MaybeUninit::<libc::rusage>::uninit();
    // SAFETY: getrusage initializes the complete output on success, checked here.
    if unsafe { libc::getrusage(libc::RUSAGE_SELF, usage.as_mut_ptr()) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    // SAFETY: the successful call above initialized usage.
    let usage = unsafe { usage.assume_init() };
    Ok((usage.ru_utime.tv_sec + usage.ru_stime.tv_sec) as f64
        + (usage.ru_utime.tv_usec + usage.ru_stime.tv_usec) as f64 / 1e6)
}

fn peak_rss_kib() -> Result<u64, Error> {
    Ok(std::fs::read_to_string("/proc/self/status")?
        .lines()
        .find(|line| line.starts_with("VmHWM:"))
        .and_then(|line| line.split_whitespace().nth(1))
        .ok_or("VmHWM is unavailable")?
        .parse()?)
}

fn write_model(path: &str, vocab: &Vocab, merges: &[(String, String)]) -> Result<(), Error> {
    let mut entries: Vec<_> = vocab.iter().collect();
    entries.sort_unstable_by_key(|(_, id)| **id);
    let mut writer = BufWriter::new(File::create(path)?);
    serde_json::to_writer(&mut writer, &(entries, merges))?;
    writer.flush()?;
    Ok(())
}

fn main() -> Result<(), Error> {
    let job_path = std::env::args()
        .nth(1)
        .ok_or("usage: bpe-suite-runner JOB.json")?;
    let job: Job = serde_json::from_reader(File::open(job_path)?)?;
    if job.workers == 0 {
        return Err("workers must be positive".into());
    }
    if !matches!(
        job.split.as_str(),
        "none" | "whitespace" | "bytelevel_regex"
    ) {
        return Err("unknown pretokenizer".into());
    }
    tk_encode::parallelism::set_num_threads(job.workers);
    tk_encode::parallelism::set_parallelism(true);
    let split = if job.split == "bytelevel_regex" {
        Some(Split::native(
            SplitPattern::Regex(GPT2_REGEX_STR.to_owned()),
            SplitDelimiterBehavior::Isolated,
            false,
        )?)
    } else {
        None
    };
    let mut builder = BpeTrainer::builder()
        .show_progress(false)
        .min_frequency(job.min_frequency)
        .vocab_size(job.vocab_size);
    if job.split == "bytelevel_regex" {
        builder = builder.initial_alphabet(ByteLevel::alphabet().into_iter().collect());
    }
    if let Some(prefix) = &job.prefix {
        builder = builder.continuing_subword_prefix(prefix.clone());
    }
    if let Some(suffix) = &job.suffix {
        builder = builder.end_of_word_suffix(suffix.clone());
    }
    builder = builder.max_token_length(job.max_token_length);
    let trainer = builder.build();
    // Every arm receives the same insertion history and caller-owned hash table.
    // Trainer-internal maps retain their native random seeds.
    let mut words: AHashMap<CompactString, u64> =
        AHashMap::with_hasher(RandomState::with_seeds(11, 13, 17, 19));
    let mut scratch = PreTokenizerScratch::default();
    let mut spans = Vec::<Span>::new();
    let mut line = String::new();
    let read_cache = std::env::var("TK_WORD_COUNTS_CACHE").ok();
    let write_cache = std::env::var("TK_WRITE_WORD_COUNTS_CACHE").ok();
    if read_cache.is_some() && write_cache.is_some() {
        return Err("cache read and generation are separate runs".into());
    }
    let mut first_seen = write_cache.as_ref().map(|_| Vec::new());
    let begin = Instant::now();
    let cpu_begin = cpu_seconds()?;
    eprintln!("BPE_SUITE_PHASE=feed");
    let mut lines = 0_u64;
    let mut occurrences = 0_u64;
    if let Some(path) = &read_cache {
        let cached: WordCountsCache = serde_json::from_reader(BufReader::new(File::open(path)?))?;
        if cached.version != 1
            || cached.input != job.input
            || cached.split != job.split
            || cached.input_bytes != std::fs::metadata(&job.input)?.len()
        {
            return Err("word-count cache does not describe this corpus/split".into());
        }
        lines = cached.lines;
        occurrences = cached.occurrences;
        let mut counted = 0_u64;
        for (word, count) in cached.ordered_words {
            counted = counted
                .checked_add(count)
                .ok_or("cached word count overflow")?;
            if count == 0 || words.insert(word, count).is_some() {
                return Err("cached word entry is zero or duplicated".into());
            }
        }
        if counted != occurrences {
            return Err("cached word occurrence total differs".into());
        }
    } else {
        let mut reader = BufReader::new(File::open(&job.input)?);
        while reader.read_line(&mut line)? != 0 {
            lines += 1;
            spans.clear();
            match job.split.as_str() {
                "whitespace" => WhitespaceSplit.pre_tokenize(&line, &mut scratch, &mut spans)?,
                "bytelevel_regex" => split.as_ref().expect("validated splitter").pre_tokenize(
                    &line,
                    &mut scratch,
                    &mut spans,
                )?,
                "none" => {}
                _ => unreachable!(),
            }
            let mut add = |piece: &str| -> Result<(), Error> {
                let text = if job.split == "bytelevel_regex" {
                    tk_encode::normalizers::byte_level::ByteLevel::new()
                        .normalize(piece, 0)?
                        .into_owned()
                } else {
                    piece.to_owned()
                };
                match words.entry(CompactString::from(text)) {
                    Entry::Occupied(mut entry) => {
                        *entry.get_mut() =
                            entry.get().checked_add(1).ok_or("word count overflow")?;
                    }
                    Entry::Vacant(entry) => {
                        if let Some(order) = &mut first_seen {
                            order.push(entry.key().clone());
                        }
                        entry.insert(1);
                    }
                }
                occurrences += 1;
                Ok(())
            };
            if job.split == "none" {
                add(&line)?;
            } else {
                for span in &spans {
                    add(&line[span.range()])?;
                }
            }
            line.clear();
        }
    }
    if let Some(path) = &write_cache {
        let cached = WordCountsCache {
            version: 1,
            input: job.input.clone(),
            input_bytes: std::fs::metadata(&job.input)?.len(),
            split: job.split.clone(),
            lines,
            occurrences,
            ordered_words: first_seen
                .take()
                .expect("cache writer records insertion order")
                .into_iter()
                .map(|word| {
                    let count = words[&word];
                    (word, count)
                })
                .collect(),
        };
        let mut writer = BufWriter::new(File::create(path)?);
        serde_json::to_writer(&mut writer, &cached)?;
        writer.flush()?;
    }
    let feed_seconds = begin.elapsed().as_secs_f64();
    eprintln!("BPE_SUITE_PHASE=train");
    let train_begin = Instant::now();
    let train_cpu_begin = cpu_seconds()?;
    let (vocab, merges, special_tokens) = trainer.do_train(&words)?;
    let train_seconds = train_begin.elapsed().as_secs_f64();
    let elapsed_seconds = begin.elapsed().as_secs_f64();
    let train_cpu_seconds = cpu_seconds()? - train_cpu_begin;
    let cpu_seconds = cpu_seconds()? - cpu_begin;
    // This HWM stops at the same feed+training boundary as the wall/CPU metrics.
    // The supervisor also samples whole-process RSS, including validation.
    let maxrss_kib = peak_rss_kib()?;
    eprintln!("BPE_SUITE_PHASE=validation");
    let mut symbols = 0_u64;
    let mut edges = 0_u64;
    for word in words.keys() {
        let length = word.chars().count() as u64;
        symbols += length;
        edges += length.saturating_sub(1);
    }
    write_model(&job.output, &vocab, &merges)?;
    println!(
        "{}",
        json!({
            "input_bytes": std::fs::metadata(&job.input)?.len(),
            "split": job.split, "workers": job.workers,
            "vocab_size": job.vocab_size, "min_frequency": job.min_frequency,
            "feed_seconds": feed_seconds, "train_seconds": train_seconds,
            "elapsed_seconds": elapsed_seconds, "cpu_seconds": cpu_seconds,
            "train_cpu_seconds": train_cpu_seconds, "maxrss_kib": maxrss_kib,
            "lines": lines, "pretoken_occurrences": occurrences,
            "unique_words": words.len(), "unique_symbols": symbols, "initial_edges": edges,
            "actual_vocab": vocab.len(), "actual_merges": merges.len(),
            "special_tokens": special_tokens.len(), "model_output": job.output,
            "word_hash_seeds": [11,13,17,19], "internal_hash_seeds": "native_random",
            "allocation_counters_enabled": false,
            "feed_mode": if read_cache.is_some() { "cached_word_counts_exploration" } else if write_cache.is_some() { "streaming_with_cache_generation" } else { "streaming" },
            "word_counts_cache": read_cache,
        })
    );
    Ok(())
}
