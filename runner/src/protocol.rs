use compact_str::CompactString;
use serde::{Deserialize, Serialize};
pub type Error = Box<dyn std::error::Error + Send + Sync>;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Job {
    pub protocol_version: u32,
    pub attempt_id: String,
    pub build_id: String,
    pub input_id: String,
    pub mode: String,
    pub input: String,
    pub output: String,
    pub workers: usize,
    pub pretokenizer: String,
    pub trainer: TrainerConfig,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TrainerConfig {
    pub vocab_size: usize,
    pub min_frequency: u64,
    pub prefix: Option<String>,
    pub suffix: Option<String>,
    pub max_token_length: Option<usize>,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PreparedWords {
    pub schema_version: u32,
    pub pretokenizer: String,
    pub ordered_words: Vec<(CompactString, u64)>,
    pub hash_seeds: [u64; 4],
}
pub fn cpu_seconds() -> Result<f64, Error> {
    let mut usage = std::mem::MaybeUninit::<libc::rusage>::uninit();
    // SAFETY: successful getrusage initializes this writable rusage structure.
    if unsafe { libc::getrusage(libc::RUSAGE_SELF, usage.as_mut_ptr()) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    let usage = unsafe { usage.assume_init() };
    Ok((usage.ru_utime.tv_sec + usage.ru_stime.tv_sec) as f64
        + (usage.ru_utime.tv_usec + usage.ru_stime.tv_usec) as f64 / 1e6)
}
pub fn hwm() -> Result<u64, Error> {
    Ok(std::fs::read_to_string("/proc/self/status")?
        .lines()
        .find(|line| line.starts_with("VmHWM:"))
        .and_then(|line| line.split_whitespace().nth(1))
        .ok_or("missing HWM")?
        .parse()?)
}
pub fn affinity() -> Result<Vec<usize>, Error> {
    let status = std::fs::read_to_string("/proc/self/status")?;
    let list = status
        .lines()
        .find(|line| line.starts_with("Cpus_allowed_list:"))
        .and_then(|line| line.split_whitespace().nth(1))
        .ok_or("missing affinity")?;
    let mut result = Vec::new();
    for piece in list.split(',') {
        if let Some((a, b)) = piece.split_once('-') {
            result.extend(a.parse::<usize>()?..=b.parse()?);
        } else {
            result.push(piece.parse()?);
        }
    }
    Ok(result)
}
