//! Inspect the public serialized trainer without materializing another word map.
//! This runs after the measured Feed/Train interval and pre-validation HWM.
use crate::protocol::Error;
use serde::Serialize;
use serde_json::ser::{CharEscape, Formatter, Serializer};
use std::io::{self, Write};

#[derive(Default)]
struct WordBytes {
    depth: usize,
    key: bool,
    field: String,
    pending_words: bool,
    words_depth: Option<usize>,
    words: u64,
    bytes: u64,
}

impl Formatter for &mut WordBytes {
    fn begin_object<W: ?Sized + Write>(&mut self, _writer: &mut W) -> io::Result<()> {
        self.depth += 1;
        if self.pending_words {
            self.words_depth = Some(self.depth);
            self.pending_words = false;
        }
        Ok(())
    }

    fn end_object<W: ?Sized + Write>(&mut self, _writer: &mut W) -> io::Result<()> {
        if self.words_depth == Some(self.depth) {
            self.words_depth = None;
        }
        self.depth -= 1;
        Ok(())
    }

    fn begin_object_key<W: ?Sized + Write>(
        &mut self,
        _writer: &mut W,
        _first: bool,
    ) -> io::Result<()> {
        self.key = true;
        if self.depth == 1 {
            self.field.clear();
        }
        if self.words_depth == Some(self.depth) {
            self.words += 1;
        }
        Ok(())
    }

    fn end_object_key<W: ?Sized + Write>(&mut self, _writer: &mut W) -> io::Result<()> {
        self.key = false;
        if self.depth == 1 && self.field == "words" {
            self.pending_words = true;
        }
        Ok(())
    }

    fn write_string_fragment<W: ?Sized + Write>(
        &mut self,
        _writer: &mut W,
        fragment: &str,
    ) -> io::Result<()> {
        if self.key && self.words_depth == Some(self.depth) {
            self.bytes += fragment.len() as u64;
        } else if self.key && self.depth == 1 {
            self.field.push_str(fragment);
        }
        Ok(())
    }

    fn write_char_escape<W: ?Sized + Write>(
        &mut self,
        _writer: &mut W,
        _escape: CharEscape,
    ) -> io::Result<()> {
        if self.key && self.words_depth == Some(self.depth) {
            // JSON's escapes here represent one original ASCII byte, including
            // controls, quote and backslash; UTF-8 fragments are counted above.
            self.bytes += 1;
        }
        Ok(())
    }
}

pub fn measure(trainer: &impl Serialize, expected_words: usize) -> Result<u64, Error> {
    let mut stats = WordBytes::default();
    {
        let mut serializer = Serializer::with_formatter(io::sink(), &mut stats);
        trainer.serialize(&mut serializer)?;
    }
    if stats.words != expected_words as u64 {
        return Err("serialized Feed word count does not match public get_word_count".into());
    }
    Ok(stats.bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    #[derive(Serialize)]
    struct Trainer {
        unrelated: Vec<String>,
        words: BTreeMap<String, u64>,
    }

    #[test]
    fn counts_distinct_word_bytes_without_frequencies_or_json_escapes() {
        let trainer = Trainer {
            unrelated: vec!["ignored".into()],
            words: [("中文".into(), 500), ("\"\\\n\0".into(), 9)]
                .into_iter()
                .collect(),
        };
        assert_eq!(measure(&trainer, 2).unwrap(), 10);
        assert!(measure(&trainer, 3).is_err());
    }
}
