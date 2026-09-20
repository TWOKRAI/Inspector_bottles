---
name: windowed-voice-is-a-process-wide-singleton
description: logger_module.core.windowed_voice.process_voices() is a module-level singleton shared by the whole pytest process — reset it in an autouse fixture, and never assert a per-key suppressed count against the shared windowed_suppressed counter (it sums ALL keys/holders).
metadata:
  type: feedback
---

`multiprocess_framework/modules/logger_module/core/windowed_voice.py` provides the
project's shared "fact always, voice windowed" mechanism (`WindowedVoices.take`,
`process_voices()`, `voice_counters()["windowed_suppressed"]`). Two traps found
writing acceptance tests against it (2026-08-31, observability-closure Task 1.3a,
worktree D:/wt13a):

1. **`process_voices()` is one instance per Python process, not per test.** If the
   code under test ends up using the process-wide default holder (rather than its
   own `WindowedVoices()`, the pattern `ObservableMixin._voices()` uses), keys from
   unrelated test files in the same pytest run can collide. Always add an
   `autouse=True` fixture that calls `reset_process_voices()` before and after each
   test, defensively, even if you don't yet know which holder the implementation
   will pick.

2. **`windowed_suppressed` is a SUM across every key and every holder in the
   process.** A test that does `noise_key suppressed 5x` + `our_key suppressed 3x`
   and then checks "our suppressed count" against the delta of this counter gets
   8, not 3 — the counter cannot be decomposed by key. The only correct place to
   read a per-key suppressed count is the text of that key's own voice
   (`compose_voice_text` embeds "подавлено с прошлой записи: N"). A test that
   merely checks the key's *name* appears in the voice text is vacuous — that's
   true even under the pre-fix buggy code (the context string is always in the
   message), so it proves nothing about the new suppressed-count feature. Assert
   the actual number, and prove divergence from the global counter with two
   differently-sized noise sources so the two numbers can't accidentally match.

See also [[feedback_dedicated_breaker_threshold_avoids_confound]].
