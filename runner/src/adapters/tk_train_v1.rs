//! Public API adapter and one shared preprocessing definition for both modes.
use crate::protocol::{Error, Job};
use tk_encode::{
    pipeline::{Normalizer, PreTokenizer, PreTokenizerScratch, Span},
    pre_tokenizers::{
        split::{Split, SplitPattern},
        whitespace::{Whitespace, WhitespaceSplit},
    },
    tokenizer::SplitDelimiterBehavior,
    utils::byte_level::GPT2_REGEX_STR,
};
use tk_train::BpeTrainer;
pub fn trainer(job: &Job) -> BpeTrainer {
    let cfg = &job.trainer;
    let mut builder = BpeTrainer::builder()
        .show_progress(false)
        .vocab_size(cfg.vocab_size)
        .min_frequency(cfg.min_frequency)
        .max_token_length(cfg.max_token_length);
    if let Some(value) = &cfg.prefix {
        builder = builder.continuing_subword_prefix(value.clone());
    }
    if let Some(value) = &cfg.suffix {
        builder = builder.end_of_word_suffix(value.clone());
    }
    if job.pretokenizer == "bytelevel_regex" {
        builder = builder.initial_alphabet(
            tk_encode::pre_tokenizers::byte_level::ByteLevel::alphabet()
                .into_iter()
                .collect(),
        );
    }
    builder.build()
}
pub struct Processor {
    kind: String,
    regex: Option<Split>,
}
impl Processor {
    pub fn new(kind: &str) -> Result<Self, Error> {
        if !matches!(
            kind,
            "none" | "whitespace" | "whitespace_split" | "bytelevel_regex"
        ) {
            return Err("unsupported pretokenizer".into());
        }
        let regex = if kind == "bytelevel_regex" {
            Some(Split::native(
                SplitPattern::Regex(GPT2_REGEX_STR.to_owned()),
                SplitDelimiterBehavior::Isolated,
                false,
            )?)
        } else {
            None
        };
        Ok(Self {
            kind: kind.into(),
            regex,
        })
    }
    pub fn process(&self, line: &str) -> Result<Vec<String>, Error> {
        if self.kind == "none" {
            return Ok(vec![line.to_owned()]);
        }
        thread_local! {
            static BUFFERS: std::cell::RefCell<(PreTokenizerScratch, Vec<Span>)> =
                std::cell::RefCell::new((PreTokenizerScratch::default(), Vec::new()));
        }
        BUFFERS.with(|buffers| {
            let mut buffers = buffers.borrow_mut();
            let (scratch, spans) = &mut *buffers;
            spans.clear();
            match self.kind.as_str() {
                "whitespace" => Whitespace.pre_tokenize(line, scratch, spans)?,
                "whitespace_split" => WhitespaceSplit.pre_tokenize(line, scratch, spans)?,
                _ => self
                    .regex
                    .as_ref()
                    .unwrap()
                    .pre_tokenize(line, scratch, spans)?,
            }
            spans
                .iter()
                .map(|span| {
                    let piece = &line[span.range()];
                    if self.kind == "bytelevel_regex" {
                        tk_encode::normalizers::byte_level::ByteLevel::new()
                            .normalize(piece, 0)
                            .map(|s| s.into_owned())
                    } else {
                        Ok(piece.to_owned())
                    }
                })
                .collect()
        })
    }
}
