use crate::protocol::Error;
use std::{
    fs::File,
    io::{BufWriter, Write},
};
use tk_encode::models::bpe::Vocab;
pub fn write(path: &str, vocab: &Vocab, merges: &[(String, String)]) -> Result<(), Error> {
    let mut entries: Vec<_> = vocab.iter().collect();
    entries.sort_unstable_by_key(|(_, id)| **id);
    let mut writer = BufWriter::new(File::create(path)?);
    serde_json::to_writer(&mut writer, &(entries, merges))?;
    writer.flush()?;
    Ok(())
}
