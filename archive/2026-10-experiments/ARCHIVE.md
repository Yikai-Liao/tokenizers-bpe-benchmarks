# Historical reproduction boundary

Moved from the root on 2026-10-06, preserving both committed files and pending
experiment material. A complete pre-migration working-tree backup also exists
outside this repository. Active code must never import this archive.

The old README and scripts describe the old layout and original host. Paths to
`source-snapshots/` now refer to `../../source-snapshots/`. Runner modes, locks and
legacy environment flags belong to each recorded experiment. Legacy core's
`feed_seconds` is a `common_serial_frontend`; it is not `Trainer::feed` timing.

Known legacy audit limitations include weak cache validation, mutable prepare
identity and incomplete failure reporting. Historical files and conclusions have
not been rewritten as new-protocol evidence, and this migration does not assert
that a particular historical measurement was affected. New experiments use
`python -m bench` from the repository root.

For executable legacy reproduction, check out the experiment's recorded benchmark
revision in a separate clone/worktree and supply its recorded source snapshot.
Archive paths are preserved evidence, not a promise that each old script can run
unchanged from the new directory. New commands do not depend on these scripts.
