---
name: feedback-global-clock-patch-flake
description: Глобальный patch(time.monotonic) с конечным side_effect = флейк от чужих потоков; часы делать зависимостью объекта
metadata:
  node_type: memory
  type: feedback
  originSessionId: 93ca524e-6d89-4707-aee4-07f774e7188d
  modified: 2026-07-26T13:23:57.910Z
---

Тест, который патчит **глобальные** часы (`patch("time.monotonic", side_effect=[...])`),
в полном прогоне становится заложником соседей по процессу: чужие живые потоки
(ProcessMonitor, daemon-flusher StateStore, батч-буферы логов) читают те же патченые часы,
доедают конечный список и роняют ЧУЖОЙ тест `StopIteration`. Пойман 2026-07-26 на
`state_store_module/tests/test_throttle.py::TestLazyPrune` — 2 падения из 4 полных прогонов
`multiprocess_framework/modules`, в изоляции всегда зелено, порядок тестов ни при чём
(плагина рандомизации нет).

**Why:** симптом указывает на невиновный модуль (троттл), а настоящая причина — форма теста.
Такое падение легко списать на «флейк, перезапусти» — и потерять и доверие к сьюту, и повод
починить.

**How to apply:** часы — зависимость объекта, а не глобаль. `ThrottleMiddleware(rules,
clock=time.monotonic)`, внутри единственная точка чтения `self._now()`; тест подставляет часы
через `patch.object(mw, "_now", ...)` — их видит только испытуемый экземпляр. Приёмка — пара:
эмуляция старого чтения (`clock=lambda: time.monotonic()`) под соседним потоком падает 3/3,
часы экземпляра проходят 3/3, полный сьют зелёный 3 прогона подряд.

Связано: [[feedback_check_red_on_main_first]] (сперва проверить красноту на main — здесь main
дал зелёный с первого раза и чуть не увёл в «это не флейк, это моя правка»),
[[feedback_plausible_is_not_verified]], [[feedback_single_marker_verdict_lies]].
