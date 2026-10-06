use crate::{
    adapters::tk_train_v1::{Processor, trainer},
    model_output,
    protocol::{Error, Job, PreparedWords, cpu_seconds, hwm},
};
use ahash::{AHashMap, RandomState};
use compact_str::CompactString;
use serde_json::{Value, json};
use std::{
    fs::File,
    io::{BufRead, BufReader, BufWriter, Write},
    time::Instant,
};

pub fn prepare(job: &Job) -> Result<Value, Error> {
    let begin = Instant::now();
    let cpu = cpu_seconds()?;
    let processor = Processor::new(&job.pretokenizer)?;
    let mut counts = AHashMap::<CompactString, u64>::new();
    for line in BufReader::new(File::open(&job.input)?).lines() {
        for word in processor.process(&line?)? {
            *counts.entry(word.into()).or_default() += 1;
        }
    }
    // A fixed lexical reconstruction order gives every arm the same caller map.
    let mut ordered_words: Vec<_> = counts.into_iter().collect();
    ordered_words.sort_unstable_by(|a, b| a.0.cmp(&b.0));
    let data = PreparedWords {
        schema_version: 1,
        pretokenizer: job.pretokenizer.clone(),
        ordered_words,
        hash_seeds: [11, 13, 17, 19],
    };
    let preprocessing_seconds = begin.elapsed().as_secs_f64();
    let preprocessing_cpu_seconds = cpu_seconds()? - cpu;
    let mut writer = BufWriter::new(File::create(&job.output)?);
    serde_json::to_writer(&mut writer, &data)?;
    writer.flush()?;
    Ok(json!({"unique_words":data.ordered_words.len(),
        "preprocessing_seconds":preprocessing_seconds,
        "preprocessing_cpu_seconds":preprocessing_cpu_seconds}))
}
pub fn run(job: &Job) -> Result<Value, Error> {
    let load = Instant::now();
    let prepared: PreparedWords = serde_json::from_reader(BufReader::new(File::open(&job.input)?))?;
    if prepared.schema_version != 1
        || prepared.pretokenizer != job.pretokenizer
        || prepared.hash_seeds != [11, 13, 17, 19]
    {
        return Err("prepared input protocol mismatch".into());
    }
    let mut words = AHashMap::with_hasher(RandomState::with_seeds(11, 13, 17, 19));
    let mut previous: Option<CompactString> = None;
    for (word, count) in prepared.ordered_words {
        if previous.as_ref().is_some_and(|p| p >= &word) {
            return Err("prepared words not strictly ordered".into());
        }
        previous = Some(word.clone());
        words.insert(word, count);
    }
    let load_seconds = load.elapsed().as_secs_f64();
    let trainer = trainer(job);
    let begin = Instant::now();
    let cpu = cpu_seconds()?;
    let (vocab, merges, special) = trainer.do_train(&words)?;
    let train_seconds = begin.elapsed().as_secs_f64();
    let train_cpu_seconds = cpu_seconds()? - cpu;
    let process_hwm_kib_before_validation = hwm()?;
    model_output::write(&job.output, &vocab, &merges)?;
    Ok(
        json!({"metrics":{"load_seconds":load_seconds,"train_seconds":train_seconds,
        "train_cpu_seconds":train_cpu_seconds,"process_hwm_kib_before_validation":process_hwm_kib_before_validation},
        "output":{"model_path":job.output,"actual_vocab":vocab.len(),"actual_merges":merges.len(),"special_tokens":special.len()},
        "timing_boundary":"public-do-train-before-serialization"}),
    )
}
