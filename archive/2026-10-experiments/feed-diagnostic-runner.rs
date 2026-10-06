//! Measure the public Trainer::feed; emit canonical word counts for exact comparison.
use serde::Deserialize;
use serde_json::json;
use std::{fs::File, io::{BufRead, BufReader, BufWriter}, time::Instant};
use tk_train::{BpeTrainer, Trainer};
use std::sync::atomic::{AtomicU64, Ordering};
struct TimedInput<'a, I> { inner: I, read_ns: &'a AtomicU64 }
impl<I: Iterator> Iterator for TimedInput<'_, I> {
    type Item = I::Item;
    fn next(&mut self) -> Option<Self::Item> {
        let begin = Instant::now();
        let result = self.inner.next();
        self.read_ns.fetch_add(begin.elapsed().as_nanos() as u64, Ordering::Relaxed);
        result
    }
}
type Error = Box<dyn std::error::Error + Send + Sync>;
#[derive(Deserialize)]
struct Job { input: String, workers: usize, output: String, split: String }
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
    let mut trainer = BpeTrainer::builder().show_progress(false).build();
    let input = BufReader::new(File::open(&job.input)?);
    let split = job.split.clone();
    use tk_encode::{pipeline::{PreTokenizer, PreTokenizerScratch, Span, Normalizer}, pre_tokenizers::{whitespace::{Whitespace, WhitespaceSplit}, split::{Split, SplitPattern}}, tokenizer::SplitDelimiterBehavior, utils::byte_level::GPT2_REGEX_STR};
    let regex = Split::native(SplitPattern::Regex(GPT2_REGEX_STR.to_owned()), SplitDelimiterBehavior::Isolated, false)?;
    if !matches!(split.as_str(), "Whitespace" | "WhitespaceSplit" | "ByteLevel") { return Err("unknown repository pretokenizer".into()); }
    thread_local! { static SCRATCH: std::cell::RefCell<(PreTokenizerScratch, Vec<Span>)> = std::cell::RefCell::new((PreTokenizerScratch::default(), Vec::new())); }
    let read_ns = AtomicU64::new(0);
    let timed = TimedInput { inner: input.lines().map(|line| line.expect("corpus read failed")), read_ns: &read_ns };
    let process_ns = AtomicU64::new(0);
    let begin = Instant::now();
    let cpu_begin = cpu_seconds()?;
    trainer.feed(timed, |line| {
        let begin = Instant::now();
        let result = SCRATCH.with(|buffers| {
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
        });
        process_ns.fetch_add(begin.elapsed().as_nanos() as u64, Ordering::Relaxed);
        result
    })?;
    let seconds = begin.elapsed().as_secs_f64();
    let cpu = cpu_seconds()? - cpu_begin;
    eprintln!("INPUT_PHASES {}", json!({"read_next_seconds_sum":read_ns.load(Ordering::Relaxed) as f64 / 1e9, "process_seconds_sum":process_ns.load(Ordering::Relaxed) as f64 / 1e9,"feed_wall_seconds":seconds,"feed_cpu_seconds":cpu}));
    let hwm: u64 = std::fs::read_to_string("/proc/self/status")?.lines()
        .find(|line| line.starts_with("VmHWM:")).ok_or("missing HWM")?
        .split_whitespace().nth(1).ok_or("missing HWM value")?.parse()?;
    // Serialization and sorting are outside the measured feed boundary.
    let state = serde_json::to_value(&trainer)?;
    let mut words: Vec<_> = state["words"].as_object().ok_or("missing word table")?.iter().collect();
    words.sort_unstable_by(|left, right| left.0.cmp(right.0));
    serde_json::to_writer(BufWriter::new(File::create(&job.output)?), &words)?;
    println!("{}", json!({"train_seconds":seconds,"feed_seconds":seconds,
        "elapsed_seconds":seconds,"train_cpu_seconds":cpu,"cpu_seconds":cpu,
        "maxrss_kib":hwm,"actual_vocab":words.len(),"actual_merges":0,
        "phase":"public Trainer::feed; repository pretokenizer", "pretokenizer":split}));
    Ok(())
}
