---
name: store-retention-bounds-rows-not-bytes
description: ObservabilityStore purge() bounds rows, not bytes - FTS5 external-content index keeps tombstones and grows under a retention ring; optimize after purge reclaims it (192 ms at 150k rows, 0 concurrent drops)
metadata:
  type: project
---

`ObservabilityStore.purge()` deletes rows and runs `incremental_vacuum`, but never touches the FTS5
index (`records_fts`, external content). Measured 2026-09-07 (CTO verdict, phase F4 opening of
`observability-closure`):

- live `logs/prototype_2/observability.db`: **35 rows, 21.3 MiB**, `records_fts_data` = 5174 of 5203 pages;
- synthetic ring (purge to 5k every 5k inserts, 10 cycles): rows 50 000 -> 10 000 while
  `records_fts_data` pages 869 -> 2550; purge to 35 rows -> 10.4 MiB;
- `INSERT INTO records_fts(records_fts) VALUES('optimize')` + `incremental_vacuum` -> 0.06 MiB;
  at 150k live rows optimize took **192 ms** under the store lock, a concurrent writer on a second
  connection lost **0** batches (busy_timeout 2000 ms covers it).

Per-row cost split at 20k rows (dbstat, payload 571 B): table b-tree 685 (x1.20, row header + page slack,
not removable), FTS 83 (detail=none,columnsize=0 -> 46), three secondary indexes 34, compact JSON
separators -98 B, constant per-process envelope in every `extra` (proc_name/pid/fw_version/incarnation/recipe)
= 110 B. All (b)-levers together ~ -30 %, never the x13 the F3 target misses at every_mth=1.

**Why:** the plan computes horizon from `max_rows`; on bytes that math is optimistic until the sweeper
optimizes the FTS index after purge. The 745/476 = x1.57 on the stand is ~x1.2 SQLite floor plus removable rest.

**How to apply:** any horizon/MiB-per-hour claim about the store must be measured on a file that has
been through purge cycles, not on pure inserts; a retention task must add FTS optimize (or merge steps)
after purge and measure drops of concurrent writers. Related: [[f3-cut-verdict-2026-09-07]].
