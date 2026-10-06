//! Measure the public Trainer::feed; emit canonical word counts for exact comparison.
use serde::Deserialize;
use serde_json::json;
use std::{fs::File, io::{BufRead, BufReader, BufWriter}, time::Instant};
use tk_train::{BpeTrainer, Trainer};
type Error = Box<dyn std::error::Error + Send + Sync>;
#[derive(Deserialize)]
struct Job { input: String, workers: usize, output: String, split: String, vocab_size: usize, min_frequency: u64 }
fn cpu_seconds() -> Result<f64, Error> {
    let mut usage = std::mem::MaybeUninit::<libc::rusage>::uninit();
    // SAFETY: getrusage initializes the output on successful return.
    if unsafe { libc::getrusage(libc::RUSAGE_SELF, usage.as_mut_ptr()) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    let usage = unsafe { usage.assume_init() };
    Ok((usage.ru_utime.tv_sec + usage.ru_stime.tv_sec) as f64
       + (usage.ru_utime.tv_usec + usage.ru_stime.tv_usec) as f64 / 1e6)
}
fn main() -> Result<(), Error> {
    let job: Job = serde_json::from_reader(File::open(std::env::args().nth(1).ok_or("job required")?)?)?;
    tk_encode::parallelism::set_num_threads(job.workers);
    tk_encode::parallelism::set_parallelism(true);
    let mut trainer = BpeTrainer::builder().vocab_size(job.vocab_size).min_frequency(job.min_frequency).show_progress(false).build();
    let input = BufReader::new(File::open(&job.input)?);
    let split = job.split.clone();
    use tk_encode::{pipeline::{PreTokenizer, PreTokenizerScratch, Span, Normalizer}, pre_tokenizers::{whitespace::{Whitespace, WhitespaceSplit}, split::{Split, SplitPattern}}, tokenizer::SplitDelimiterBehavior, utils::byte_level::GPT2_REGEX_STR};
    let regex = Split::native(SplitPattern::Regex(GPT2_REGEX_STR.to_owned()), SplitDelimiterBehavior::Isolated, false)?;
    if !matches!(split.as_str(), "Whitespace" | "WhitespaceSplit" | "ByteLevel") { return Err("unknown repository pretokenizer".into()); }
    thread_local! { static SCRATCH: std::cell::RefCell<(PreTokenizerScratch, Vec<Span>)> = std::cell::RefCell::new((PreTokenizerScratch::default(), Vec::new())); }
    let begin = Instant::now();
    let cpu_begin = cpu_seconds()?;
    trainer.feed(input.lines().map(|line| line.expect("corpus read failed")), |line| {
        SCRATCH.with(|buffers| {
            let mut buffers = buffers.borrow_mut();
            let (scratch, spans) = &mut *buffers;
            spans.clear();
            match split.as_str() {
                "Whitespace" => Whitespace.pre_tokenize(line, scratch, spans)?,
                "WhitespaceSplit" => WhitespaceSplit.pre_tokenize(line, scratch, spans)?,
                "ByteLevel" => regex.pre_tokenize(line, scratch, spans)?,
                _ => unreachable!(),
            }
            spans.iter().map(|span| {
                let piece = &line[span.range()];
                if split == "ByteLevel" {
                    tk_encode::normalizers::byte_level::ByteLevel::new().normalize(piece, 0).map(|word| word.into_owned())
                } else { Ok(piece.to_owned()) }
            }).collect()
        })
    })?;
    let feed_seconds = begin.elapsed().as_secs_f64();
    let train_begin = Instant::now();
    let train_cpu_begin = cpu_seconds()?;
    let (vocab, merges, _) = trainer.train_vocab()?;
    let seconds = train_begin.elapsed().as_secs_f64();
    let train_cpu = cpu_seconds()? - train_cpu_begin;
    let elapsed_seconds = begin.elapsed().as_secs_f64();
    let cpu = cpu_seconds()? - cpu_begin;
    let status = std::fs::read_to_string("/proc/self/status")?;
    let rss: u64 = status.lines().find(|line| line.starts_with("VmRSS:")).ok_or("missing RSS")?.split_whitespace().nth(1).ok_or("missing RSS value")?.parse()?;
    let hwm: u64 = status.lines()
        .find(|line| line.starts_with("VmHWM:")).ok_or("missing HWM")?
        .split_whitespace().nth(1).ok_or("missing HWM value")?.parse()?;
    let mut entries: Vec<_> = vocab.iter().collect();
    entries.sort_unstable_by_key(|(_, id)| **id);
    serde_json::to_writer(BufWriter::new(File::create(&job.output)?), &(entries, &merges))?;
    println!("{}", json!({"train_seconds":seconds,"feed_seconds":feed_seconds,
        "elapsed_seconds":elapsed_seconds,"train_cpu_seconds":train_cpu,"cpu_seconds":cpu,
        "maxrss_kib":hwm,"retained_rss_kib":rss,"actual_vocab":vocab.len(),"actual_merges":merges.len(),
        "phase":"public Trainer::feed + train_vocab; repository pretokenizer", "pretokenizer":split}));
    Ok(())
}
