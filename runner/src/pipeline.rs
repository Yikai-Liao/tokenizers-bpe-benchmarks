use crate::{
    adapters::tk_train_v1::{Processor, trainer},
    model_output,
    protocol::{Error, Job, cpu_seconds, hwm},
};
use serde_json::{Value, json};
use std::{
    fs::File,
    io::{BufRead, BufReader},
    time::Instant,
};
use tk_train::Trainer;
pub fn run(job: &Job) -> Result<Value, Error> {
    let mut trainer = trainer(job);
    let processor = Processor::new(&job.pretokenizer)?;
    let input = BufReader::new(File::open(&job.input)?);
    let begin = Instant::now();
    let cpu = cpu_seconds()?;
    // Lazy line reading, public preprocessing and aggregation all belong to feed.
    trainer.feed(
        input.lines().map(|line| line.expect("input read failed")),
        |line| processor.process(line),
    )?;
    let feed_seconds = begin.elapsed().as_secs_f64();
    let feed_unique_words = trainer.get_word_count();
    let train_begin = Instant::now();
    let train_cpu = cpu_seconds()?;
    let (vocab, merges, special) = trainer.train_vocab()?;
    let train_seconds = train_begin.elapsed().as_secs_f64();
    let train_cpu_seconds = cpu_seconds()? - train_cpu;
    let pipeline_seconds = begin.elapsed().as_secs_f64();
    let pipeline_cpu_seconds = cpu_seconds()? - cpu;
    let process_hwm_kib_before_validation = hwm()?;
    let feed_unique_utf8_bytes = crate::feed_stats::measure(&trainer, feed_unique_words)?;
    model_output::write(&job.output, &vocab, &merges)?;
    Ok(
        json!({"metrics":{"feed_seconds":feed_seconds,"train_seconds":train_seconds,
        "pipeline_seconds":pipeline_seconds,"pipeline_cpu_seconds":pipeline_cpu_seconds,
        "train_cpu_seconds":train_cpu_seconds,"process_hwm_kib_before_validation":process_hwm_kib_before_validation,
        "feed_unique_words":feed_unique_words,"feed_unique_utf8_bytes":feed_unique_utf8_bytes},
        "output":{"model_path":job.output,"actual_vocab":vocab.len(),"actual_merges":merges.len(),"special_tokens":special.len()},
        "timing_boundary":"public-feed-and-train-before-serialization"}),
    )
}
