// Additional cross-checks kept outside the optimization PR.
fn greedy(trainer: &BpeTrainer, wc: &AHashMap<CompactString, u64>) -> Vec<(Pair, u64, u32)> {
    let mut ids = AHashMap::new();
    let mut strings = Vec::new();
    trainer.add_special_tokens(&mut ids, &mut strings);
    trainer.compute_alphabet(wc, &mut ids, &mut strings);
    let (words, weights) = trainer.tokenize_words(wc, &mut ids, &mut strings);
    let mut words: Vec<Vec<u32>> = words
        .iter()
        .map(super::super::word::Word::get_chars)
        .collect();
    let mut trace = Vec::new();
    while ids.len() < trainer.vocab_size {
        let mut counts = AHashMap::<Pair, u64>::new();
        for (word, &weight) in words.iter().zip(&weights) {
            for edge in word.windows(2) {
                *counts.entry((edge[0], edge[1])).or_default() += weight;
            }
        }
        let Some((pair, count)) = counts
            .into_iter()
            .max_by(|(a, ac), (b, bc)| ac.cmp(bc).then_with(|| b.cmp(a)))
        else {
            break;
        };
        if count == 0 || count < trainer.min_frequency {
            break;
        }
        let token = CompactString::from(format!(
            "{}{}",
            strings[pair.0 as usize], strings[pair.1 as usize]
        ));
        let id = if let Some(&id) = ids.get(&token) {
            id
        } else {
            let id = strings.len() as u32;
            strings.push(token.clone());
            ids.insert(token, id);
            id
        };
        trace.push((pair, count, id));
        for word in &mut words {
            let mut output = Vec::new();
            let mut i = 0;
            while i < word.len() {
                if i + 1 < word.len() && (word[i], word[i + 1]) == pair {
                    output.push(id);
                    i += 2;
                } else {
                    output.push(word[i]);
                    i += 1;
                }
            }
            *word = output;
        }
    }
    trace
}

#[test]
fn recomputing_greedy_oracle_without_affixes_or_length_filter() {
    let mut rng = 1400_u64;
    for _ in 0..250 {
        let mut wc = AHashMap::<CompactString, u64>::new();
        for _ in 0..12 {
            let word: String = (0..30)
                .map(|_| {
                    rng = rng.wrapping_mul(6364136223846793005).wrapping_add(1);
                    ['a', 'b', 'c', '测'][(rng >> 32) as usize % 4]
                })
                .collect();
            *wc.entry(word.into()).or_default() += 1 + (rng >> 32) % 9;
        }
        let trainer = BpeTrainer::builder()
            .vocab_size(100)
            .show_progress(false)
            .build();
        let mut trace = Vec::new();
        train(
            &trainer,
            Words::from_map(&wc),
            4,
            Some(&mut |pair, count, id| trace.push((pair, count, id))),
        )
        .unwrap();
        assert_eq!(trace, greedy(&trainer, &wc), "words={wc:?}");
    }
}

#[test]
fn planned_wave_tables_preserve_coordinates_weights_and_filtering() {
    #[derive(Debug, PartialEq, Eq)]
    struct InitialSnapshot {
        weighted_mass: u128,
        maximum_word_weight: u64,
        entries: Vec<(u64, u64, Vec<u64>)>,
    }
    fn snapshot(table: initial_pairs::InitialPairTable<'_>) -> InitialSnapshot {
        let mut entries: Vec<_> = table
            .shards
            .into_iter()
            .flat_map(|shard| shard.into_iter())
            .map(|(key, state)| {
                (
                    key,
                    state.ledger_count_bits,
                    state.positions.iter().collect(),
                )
            })
            .collect();
        entries.sort_unstable_by_key(|entry| entry.0);
        InitialSnapshot {
            weighted_mass: table.weighted_mass,
            maximum_word_weight: table.maximum_word_weight,
            entries,
        }
    }
    let words = counts(&[
        ("", 1),
        ("x", 0),
        ("ab测éab测éab", 7),
        ("ab测é", 0),
        ("baab", 2),
    ]);
    let mut trainer = BpeTrainer::builder()
        .vocab_size(100)
        .show_progress(false)
        .build();
    trainer.continuing_subword_prefix = Some("##".into());
    trainer.end_of_word_suffix = Some("</w>".into());
    trainer.limit_alphabet = Some(3);
    trainer.initial_alphabet = ['a', 'b', '测'].into();
    for workers in [1, 2, 4] {
        let execution = execution::Execution::new(workers).unwrap();
        let progress = TrainingProgress::new(false, trainer.progress_format).unwrap();
        execution.pool.install(|| {
            for wave in [2, 7, 1 << 28] {
                for minimum in [0, 2, 8] {
                    let mut retained = None;
                    let mut vocab = vocabulary::Vocabulary::initialize(
                        &trainer,
                        Words::from_map(&words),
                        workers,
                        &progress,
                        &mut retained,
                    )
                    .unwrap();
                    let plan = corpus::CorpusPlan::build(
                        Words::from_map(&words),
                        &mut vocab,
                        IdentityPolicy::AllowActiveReuse,
                        false,
                        &progress,
                    )
                    .unwrap();
                    let arena = AllocationArena::new(workers, plan.initial_edges());
                    let actual = snapshot(
                        initial_pairs::InitialPairTable::build_in_waves(
                            &plan, minimum, &execution, &arena, &progress, wave,
                        )
                        .unwrap(),
                    );
                    let corpus = plan
                        .materialize::<corpus::U32Slots>(
                            workers,
                            IdentityPolicy::AllowActiveReuse,
                            &progress,
                        )
                        .unwrap();
                    let expected = snapshot(
                        initial_pairs::InitialPairTable::build_in_waves(
                            corpus.initial_view(),
                            minimum,
                            &execution,
                            &arena,
                            &progress,
                            wave,
                        )
                        .unwrap(),
                    );
                    assert_eq!(
                        actual, expected,
                        "workers={workers} wave={wave} minimum={minimum}"
                    );
                }
            }
        });
    }
}

