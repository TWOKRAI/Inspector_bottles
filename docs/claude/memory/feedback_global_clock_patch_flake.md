---
name: feedback-global-clock-patch-flake
description: "Глобальный patch(time.monotonic) с конечным side_effect = флейк (flaky) от чужих потоков; часы (clock) делать зависимостью объекта; шов, что гоняется с окном драйвера по реальным часам, — тест времени, даже если ждёт событие"
module: [state_store_module, device_hub]
mechanism: [flaky-tests, test-infra]
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

**Второй случай, 2026-10-20 (T5.3c/d, ревью Opus р.7).** Сторожа `test_robot_v2_lease_log.py` должны были взять замок
или послать release раньше, чем истечёт окно удержания jog (`_HOLD_WINDOW_S = 0.2`) по реальным часам драйвера.
Сторож (а) ждал событие `stop_requested`, но успех решала гонка потока теста с окном. Вход: `time.sleep(0.3)` после
`jog_hold` → 2 failed на верном коде, с тем же текстом, что у инъекций L-I2/L-I5, — ложно указывает на продукт.
Правка: `RobotDriverV2(clock=_ManualClock().now)`, окно сдвигается `advance()` только после шага теста → 4 passed и с
задержкой. **Триггер:** шов должен «успеть раньше» короткого окна объекта — окно держать часами объекта.
