mod adapters;
mod core;
mod model_output;
mod pipeline;
mod protocol;
use protocol::{Error, Job};
fn main() -> Result<(), Error> {
    for (key, _) in std::env::vars() {
        if key.starts_with("TK_WORD_COUNTS_CACHE") || key.starts_with("TK_WRITE_WORD_COUNTS_CACHE")
        {
            return Err("exploration cache environment prohibited".into());
        }
    }
    let job: Job = serde_json::from_reader(std::fs::File::open(
        std::env::args().nth(1).ok_or("job required")?,
    )?)?;
    if job.protocol_version != 1 || job.workers == 0 {
        return Err("invalid protocol or workers".into());
    }
    tk_encode::parallelism::set_num_threads(job.workers);
    tk_encode::parallelism::set_parallelism(true);
    let mut result = match job.mode.as_str() {
        "prepare" => core::prepare(&job)?,
        "core" => core::run(&job)?,
        "pipeline" => pipeline::run(&job)?,
        _ => return Err("unknown mode".into()),
    };
    let fields = result.as_object_mut().unwrap();
    fields.insert("protocol_version".into(), 1.into());
    fields.insert("attempt_id".into(), job.attempt_id.into());
    fields.insert("build_id".into(), job.build_id.into());
    fields.insert("input_id".into(), job.input_id.into());
    fields.insert("mode".into(), job.mode.into());
    fields.insert("workers_requested".into(), job.workers.into());
    fields.insert(
        "effective_affinity".into(),
        serde_json::to_value(protocol::affinity()?)?,
    );
    println!("{result}");
    Ok(())
}
