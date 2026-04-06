# 📋 Progress Plan: Phase 7 — İkinci Review Düzeltmeleri

> Created: 2026-03-04 | Status: ✅ Complete | Completed: 14/14

## 🎯 Objective
İkinci multi-perspective code review'dan çıkan consensus sorunlarını ve yüksek öncelikli bulguları düzeltmek.
4 reviewer'ın (Architect, Hacker, Perfectionist, Pragmatist) bulgularından öncelik sırasıyla işleniyor.

## 📊 Progress Overview
- Total tasks: 14
- Completed: 14
- In Progress: 0
- Remaining: 0

---

## Tasks

### Phase 1: Gerçek Bug'lar (🔴)

- [x] **Task 1.1**: L2 normalize DRY ihlali — inline kopya `is_finite()` kontrolü eksik
  - Files: `crates/qex-core/src/search/embedding.rs`
  - Details: Inline L2 normalize kodunu `l2_normalize(pooled)` çağrısıyla değiştirildi. NaN/Inf guard artık tek noktada.
  - Tests: ✅ `cargo test --features dense` — 48 passed

- [x] **Task 1.2**: Typed retry logic — string matching yerine `ureq::Error` varyantları
  - Files: `crates/qex-core/src/search/openai_embedder.rs`
  - Details: `call_api` + `call_api_once` → `call_api` + `process_response` + `is_retryable_error` + `sanitize_error`. `ureq::Error::StatusCode(code)`, `Timeout`, `ConnectionFailed`, `Io` ile typed matching. Ayrıca `sanitize_error` ile güvenli hata mesajları.
  - Tests: ✅ `cargo test --features openai` — 50 passed

- [x] **Task 1.3**: `to_str().unwrap()` → proper error handling
  - Files: `crates/qex-core/src/search/dense.rs`
  - Details: Satır 61 ve 106'daki `to_str().unwrap()` → `.context("Dense index path contains non-UTF-8 characters")?`
  - Tests: ✅ `cargo test --features dense` — 48 passed

### Phase 2: Güvenlik (🔴)

- [x] **Task 2.1**: Base URL şema doğrulaması (SSRF koruması)
  - Files: `crates/qex-core/src/search/openai_embedder.rs`
  - Details: `validate_base_url()` metodu eklendi. Sadece `https://` veya `http://localhost|127.0.0.1|[::1]` kabul ediyor. IPv6 bracket syntax destekleniyor. 4 yeni test eklendi.
  - Tests: ✅ `cargo test --features openai` — 50 passed

- [x] **Task 2.2**: API key sanitizasyonunu güçlendir
  - Files: `crates/qex-core/src/search/openai_embedder.rs`
  - Details: Task 1.2'de çözüldü. `sanitize_error()` metodu: typed matching ile güvenli mesajlar. `sk-` pattern'i de kontrol ediliyor.
  - Tests: ✅ `cargo test --features openai` — 50 passed

### Phase 3: Robustness (🟡)

- [x] **Task 3.1**: `encode()` — `unwrap()` → `.context()?`
  - Files: `crates/qex-core/src/search/embedding.rs`
  - Details: `unwrap()` → `.context("ONNX model returned empty results for single text")`
  - Tests: ✅ `cargo test --features dense` — 48 passed

- [x] **Task 3.2**: Tüm embedding'lerin boyut doğrulaması
  - Files: `crates/qex-core/src/search/openai_embedder.rs`
  - Details: Task 1.2'de çözüldü. `process_response()` tüm `data` elemanlarını `for item in &data` ile doğruluyor.
  - Tests: ✅ `cargo test --features openai` — 50 passed

- [x] **Task 3.3**: Atomic write pattern — dense index save
  - Files: `crates/qex-core/src/search/dense.rs`
  - Details: `dense_mapping.json` → `dense_mapping.json.tmp` + `rename` pattern.
  - Tests: ✅ `cargo test --features dense` — 48 passed

- [x] **Task 3.4**: Corrupt mapping dosyasında açık hata
  - Files: `crates/qex-core/src/search/dense.rs`
  - Details: Her iki format da parse edilemezse `bail!("Failed to parse dense_mapping.json")` fırlatılıyor.
  - Tests: ✅ `cargo test --features dense` — 48 passed

- [x] **Task 3.5**: `max_len == 0` guard ekle
  - Files: `crates/qex-core/src/search/embedding.rs`
  - Details: `max_len == 0` durumunda zero vector döndürüyor, `j.min(max_len - 1)` underflow önleniyor.
  - Tests: ✅ `cargo test --features dense` — 48 passed

### Phase 4: Code Quality (🟡/🔵)

- [x] **Task 4.1**: Hybrid search'ü ayrı metoda çıkar
  - Files: `crates/qex-core/src/index/mod.rs`
  - Details: `try_hybrid_search()` metodu eklendi. 5 seviye iç içe `if let` → flat early-return. Her hata `warn!` ile loglanıyor.
  - Tests: ✅ `cargo test --features dense` — 48 passed

- [x] **Task 4.2**: Magic numbers → named constants
  - Files: `embedding.rs`, `dense.rs`, `openai_embedder.rs`
  - Details: `384` → `ARCTIC_EMBED_S_DIMENSIONS`, `8` → `EMBED_BATCH_SIZE`, `1536` tekrarı → `DEFAULT_DIMENSIONS`.
  - Tests: ✅ `cargo test --features "dense,openai"` — 55 passed

### Phase 5: Testing & Verification

- [x] **Test 5.1**: Tüm feature kombinasyonlarında test + build
  - `cargo test` → 41 passed ✅
  - `cargo test --features dense` → 48 passed ✅
  - `cargo test --features openai` → 50 passed ✅
  - `cargo test --features "dense,openai"` → 55 passed ✅
  - `cargo build --release --features "dense,openai"` → ✅

- [x] **Test 5.2**: PROGRESS.md'yi tamamla
  - Details: Tüm sayaçlar güncellendi, completion summary yazıldı.

---

## 📝 Notes & Decisions
| # | Note | Date |
|---|------|------|
| 1 | ureq 3: `Error::StatusCode(u16)`, `Timeout(TimeoutKind)`, `ConnectionFailed`, `Io(io::Error)` varyantları ile typed matching yapıldı. | 2026-03-04 |
| 2 | `thread::sleep` blocking async sorunu deferred — qex-core tamamen sync, MCP layer async. Daha büyük refactor gerektirir. | 2026-03-04 |
| 3 | Embedder caching deferred — `IncrementalIndexer`'a `OnceLock` eklemek `&mut self` gerektiren `Embedder` trait'i ile uyumsuz (`Mutex` lazım). | 2026-03-04 |
| 4 | `call_api_once` kaldırıldı. Yeni yapı: `call_api` (retry loop + `ureq::Error` match) → `process_response` (JSON parse + validation). | 2026-03-04 |
| 5 | IPv6 loopback URL'lerde bracket syntax: `http://[::1]:8080` — host parse'da `[` prefix kontrolü eklendi. | 2026-03-04 |

## 🐛 Issues Encountered
| # | Issue | Status | Resolution |
|---|-------|--------|------------|
| 1 | `ARCTIC_EMBED_S_DIMENSIONS as u64` — shape `Vec<i64>` kullanıyor | ✅ Fixed | `as i64` kullanıldı |
| 2 | IPv6 `[::1]:8080` URL parse — `split(':')` yanlış sonuç veriyor | ✅ Fixed | `starts_with('[')` kontrolü + `split(']')` kullanıldı |

## ➕ Added Tasks (discovered during execution)
- None

---

## ✅ Completion Summary
- **Started**: 2026-03-04
- **Completed**: 2026-03-04
- **Total tasks**: 14 (14 original + 0 added)
- **Issues encountered**: 2 (both resolved)
- **Tests passing**: ✅ All (41 base, 48 dense, 50 openai, 55 both)

### Key Changes Made
1. `embedding.rs`: Inline L2 normalize → `l2_normalize()` çağrısı (NaN guard fix), `encode()` unwrap kaldırıldı, `max_len == 0` guard, `ARCTIC_EMBED_S_DIMENSIONS` sabiti
2. `openai_embedder.rs`: Typed retry (`ureq::Error` matching), `sanitize_error()`, `validate_base_url()` (SSRF), `process_response()` ile tüm boyut doğrulaması, `DEFAULT_DIMENSIONS` kullanımı, 4 yeni test
3. `dense.rs`: `to_str().unwrap()` → `.context()`, atomic write (tmp+rename), corrupt mapping `bail!`, `EMBED_BATCH_SIZE` sabiti
4. `index/mod.rs`: `try_hybrid_search()` metodu (flat early-return + `warn!` logging)

### Remaining TODOs (deferred — low priority)
- [ ] Embedder caching in `IncrementalIndexer` (OnceLock + Mutex pattern)
- [ ] `thread::sleep` → async-aware sleep (requires sync/async boundary redesign)
- [ ] `EmbeddingRequest.dimensions` field for OpenAI API
- [ ] Default provider based on enabled features (`cfg!(feature = "dense")`)
- [ ] ONNX model dimension runtime validation (hardcoded 384)
- [ ] `auto_index` MerkleDAG double-build optimization
- [ ] HTTP response body size limit (`with_max_size`)
