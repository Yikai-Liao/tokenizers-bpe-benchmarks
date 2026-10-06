// Helpers for the existing isolated thread-policy test; no new process harness.
fn feed_preserves_counts_and_replaces_previous_input() {
    use crate::{Trainer, trainers::wordpiece::WordPieceTrainer};
    let long = "a_word_longer_than_the_compact_string_inline_capacity";
    let mut trainer = BpeTrainer::default();
    trainer.feed(["first", "empty", "second"].into_iter(), |sequence| {
        Ok(match sequence {
            "first" => vec!["重复".into(), long.into(), "重复".into()],
            "empty" => vec![],
            _ => vec![long.into(), "café".into()],
        })
    }).unwrap();
    assert_eq!(trainer.words, counts(&[("重复", 2), (long, 2), ("café", 1)]));
    trainer.feed(["new"].into_iter(), |word| Ok(vec![word.into()])).unwrap();
    assert_eq!(trainer.words, counts(&[("new", 1)]));
    trainer.feed(std::iter::empty::<&str>(), |_| unreachable!()).unwrap();
    assert!(trainer.words.is_empty());

    let mut wordpiece = WordPieceTrainer::default();
    wordpiece.feed([long, long].into_iter(), |word| Ok(vec![word.into()])).unwrap();
    assert_eq!(serde_json::to_value(wordpiece).unwrap()["bpe_trainer"]["words"],
        serde_json::json!({long: 2}));
}

fn feed_errors_keep_previous_input_and_call_every_processor() {
    use crate::Trainer;
    use std::sync::atomic::{AtomicUsize, Ordering};
    let mut trainer = BpeTrainer::default();
    trainer.words = counts(&[("previous", 7)]);
    let calls = AtomicUsize::new(0);
    let error = trainer.feed(["ok", "first error", "second error", "after"].into_iter(), |word| {
        calls.fetch_add(1, Ordering::Relaxed);
        match word {
            "first error" | "second error" => Err(word.to_owned().into()),
            _ => Ok(vec![word.into()]),
        }
    }).unwrap_err().to_string();
    assert_eq!(calls.load(Ordering::Relaxed), 4);
    assert_eq!(trainer.words, counts(&[("previous", 7)]));
    if !tk_encode::parallelism::get_parallelism() {
        assert_eq!(error, "first error");
    } else {
        assert!(matches!(error.as_str(), "first error" | "second error"));
    }
}
