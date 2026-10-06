//! Measure the public Trainer::feed; emit canonical word counts for exact comparison.
use serde::Deserialize;
use serde_json::json;
use std::{collections::BTreeMap, fs::File, io::{BufRead, BufReader, BufWriter}, time::Instant};
use tk_train::{BpeTrainer, Trainer};
type Error = Box<dyn std::error::Error + Send + Sync>;
#[derive(Deserialize)]
struct Job { input: String, workers: usize, output: String }
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
    let begin = Instant::now();
    let cpu_begin = cpu_seconds()?;
    trainer.feed(input.lines().map(|line| line.expect("corpus read failed")), |line| {
        Ok(line.split_whitespace().map(str::to_owned).collect())
    })?;
    let seconds = begin.elapsed().as_secs_f64();
    let cpu = cpu_seconds()? - cpu_begin;
    let hwm: u64 = std::fs::read_to_string("/proc/self/status")?.lines()
        .find(|line| line.starts_with("VmHWM:")).ok_or("missing HWM")?
        .split_whitespace().nth(1).ok_or("missing HWM value")?.parse()?;
    // Serialization and sorting are outside the measured feed boundary.
    let state = serde_json::to_value(&trainer)?;
    let words: BTreeMap<String, u64> = serde_json::from_value(state["words"].clone())?;
    serde_json::to_writer(BufWriter::new(File::create(&job.output)?), &words)?;
    println!("{}", json!({"train_seconds":seconds,"feed_seconds":seconds,
        "elapsed_seconds":seconds,"train_cpu_seconds":cpu,"cpu_seconds":cpu,
        "maxrss_kib":hwm,"actual_vocab":words.len(),"actual_merges":0,
        "phase":"public Trainer::feed; streaming whitespace callback"}));
    Ok(())
}
