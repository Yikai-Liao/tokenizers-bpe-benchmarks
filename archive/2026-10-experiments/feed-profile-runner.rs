//! Measure the public Trainer::feed; emit canonical word counts for exact comparison.
use serde::Deserialize;
use serde_json::json;
use std::{fs::File, io::{BufRead, BufReader}, time::Instant};
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
    let cached = std::env::var("TK_FEED_PROFILE_INPUT").ok().as_deref() == Some("cached");
    let empty = std::env::var("TK_FEED_PROFILE_CALLBACK").ok().as_deref() == Some("empty");
    let preload_begin = Instant::now();
    let preloaded = if cached { Some(BufReader::new(File::open(&job.input)?).lines().collect::<std::io::Result<Vec<_>>>()?) } else { None };
    let preload_seconds = preload_begin.elapsed().as_secs_f64();
    let begin = Instant::now();
    let cpu_begin = cpu_seconds()?;
    let process = |line: &str| {
        if empty { Ok(Vec::new()) } else {
            Ok(line.split_whitespace().map(str::to_owned).collect())
        }
    };
    if let Some(lines) = preloaded {
        trainer.feed(lines.into_iter(), process)?;
    } else {
        trainer.feed(input.lines().map(|line| line.expect("corpus read failed")), process)?;
    }
    let seconds = begin.elapsed().as_secs_f64();
    let cpu = cpu_seconds()? - cpu_begin;
    let hwm: u64 = std::fs::read_to_string("/proc/self/status")?.lines()
        .find(|line| line.starts_with("VmHWM:")).ok_or("missing HWM")?
        .split_whitespace().nth(1).ok_or("missing HWM value")?.parse()?;
    println!("{}", json!({"feed_seconds":seconds,"feed_cpu_seconds":cpu,
        "preload_seconds":preload_seconds,"maxrss_kib":hwm,
        "unique_words":trainer.get_word_count(),"workers":job.workers,
        "input_mode":if cached {"cached"} else {"streaming"},
        "callback":if empty {"empty"} else {"whitespace"}}));
    Ok(())
}
