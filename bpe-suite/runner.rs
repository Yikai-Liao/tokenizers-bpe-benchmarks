//! Common, streaming feed and one public do_train call for every source arm.
use ahash::{AHashMap, RandomState};
use compact_str::CompactString;
use serde::Deserialize;
use serde_json::json;
use std::{
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
    let mut reader = BufReader::new(File::open(&job.input)?);
    let begin = Instant::now();
    let cpu_begin = cpu_seconds()?;
    eprintln!("BPE_SUITE_PHASE=feed");
    let mut lines = 0_u64;
    let mut occurrences = 0_u64;
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
            let count = words.entry(CompactString::from(text)).or_default();
            *count = count.checked_add(1).ok_or("word count overflow")?;
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
        })
    );
    Ok(())
}
