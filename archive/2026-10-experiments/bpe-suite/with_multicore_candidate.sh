#!/bin/sh
# Run a command with the retained, measured Full candidate configuration.
set -eu
if [ "$#" -eq 0 ]; then
    echo "usage: with_multicore_candidate.sh COMMAND [ARG ...]" >&2
    exit 64
fi
export TK_SINGLE_PRODUCER_FAST=1
export TK_SINGLE_DIRECT=1
export TK_PAIR_LAYOUT=whole
export TK_COMMIT_GROUP_FUSION=1
export TK_FAST_SHARD_ROUTER=1
export TK_LOGICAL_OWNERS=0
export TK_COMMIT_DIRECT_COLD=0
export TK_COMMIT_SCATTER=0
export TK_REMOVAL_ENTRY=0
export TK_REMOVAL_REDUCE=0
export TK_REMOVAL_SELECTIVE=0
export TK_REMOVAL_STATS=0
export TK_BATCH_LIMIT=256
export TK_RAYON_IDLE_SPIN=4096
export TK_RAYON_IDLE_PAUSE=1
export TK_SINGLE_DIAG=0
export TK_SINGLE_DIAG_TIMELINE=0
exec "$@"
