# Performance

## Benchmarks

Measured on Apple Silicon (M-series):

| Operation | BM25-only | With Dense |
|-----------|-----------|------------|
| Full index (~400 chunks) | ~2s | ~20s |
| Incremental index (no changes) | <100ms | <100ms |
| BM25 search | <5ms | <5ms |
| Dense search | — | ~50ms |
| Hybrid search (BM25 + dense) | — | ~50ms |

## Binary Size

| Build | Size |
|-------|------|
| BM25-only (default) | ~19 MB |
| BM25 + dense | ~36 MB |

## Embedding Model

| Property | Value |
|----------|-------|
| Model size | 33 MB (INT8 quantized) |
| Embedding dimensions | 384 |
| Batch size | 64 chunks/batch |
| Per-query embedding | ~45ms |

## What Makes It Fast

**Incremental indexing** — Merkle DAG comparison gives O(1) "anything changed?" check. Unchanged codebases return in <100ms.

**Parallel chunking** — Tree-sitter parsing is parallelized across files via `rayon`.

**Tantivy** — High-performance BM25 engine written in Rust. Sub-5ms query latency.

**HNSW** — usearch provides approximate nearest neighbor search with sub-linear query time.

**Quantized model** — INT8 quantization reduces the embedding model from ~130 MB to 33 MB with minimal accuracy loss.

## BM25 vs Dense vs Hybrid

| Mode | Strengths | Weaknesses |
|------|-----------|------------|
| BM25-only | Fast (<5ms), no model needed, good for exact matches | Misses semantic similarity |
| Dense-only | Understands meaning, finds conceptually similar code | Slower (~50ms), requires model download |
| Hybrid | Best of both, RRF fusion merges results | ~50ms latency, larger binary |

**Recommendation**: Start with BM25-only (default). It handles most code search tasks well. Switch to hybrid if you frequently search for conceptual patterns rather than specific symbols.

## Comparison

| Tool | Approach | Size | Latency |
|------|----------|------|---------|
| grep/ripgrep | Regex text search | System tool | <1ms |
| Claude Code (default) | grep + glob | System tools | <1ms per call, many calls |
| Cursor | Cloud embeddings | ~3.5 GB | Network-dependent |
| **qex (BM25)** | Tantivy BM25 | 19 MB | <5ms |
| **qex (hybrid)** | BM25 + HNSW | 36 MB + 33 MB model | ~50ms |

qex trades <5ms extra latency per search for significantly better result relevance and fewer wasted tokens compared to raw grep.
