// Extended experiment; appended only in a disposable checkout.
fn extended_hf_differential_cases(cases: usize) {
    let mut rng = 2348;
    for case in 0..cases {
        let mut wc = AHashMap::<CompactString, u64>::new();
        for _ in 0..(1 + next(&mut rng) % 12) {
            let word: String = (0..next(&mut rng) % 24)
                .map(|_| ['a', 'b', 'c', '测'][next(&mut rng) as usize % 4])
                .collect();
            *wc.entry(word.into()).or_default() += 1 + next(&mut rng) % 9;
        }
        let mut trainer = BpeTrainer::builder()
            .show_progress(false)
            .vocab_size((4 + next(&mut rng) % 50) as usize)
            .min_frequency(next(&mut rng) % 6)
            .build();
        if case % 3 == 0 {
            trainer.special_tokens = ["aa", "ab", "aba", "abc", "ba", "测测"]
                .map(|s| AddedToken::from(s, true))
                .to_vec();
        }
        if case % 4 == 0 {
            trainer.continuing_subword_prefix = Some(["##", "a", "", "测"][(case / 4) % 4].into());
        }
        if case % 5 == 0 {
            trainer.end_of_word_suffix = Some(["</w>", "a", ""][case % 3].into());
        }
        if case % 2 == 0 {
            trainer.max_token_length = Some((next(&mut rng) % 10) as usize);
        }
        check_with_workers(&trainer, &wc, &[[1, 2, 4][case % 3]]);
    }
}

#[test]
#[ignore]
fn randomized_round_by_round_hf_stress() {
    extended_hf_differential_cases(1500);
}
