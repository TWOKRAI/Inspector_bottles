# Task 1.2 — REDS и стражи — план [2026-10-13_tooling-machine-gate-hook](../2026-10-13_tooling-machine-gate-hook.md)

Файл тестов: `scripts/machine_gate_tests/test_machine_gate_lock.py` (пишет `tester` вслепую). Ожидаемые значения — литералы отсюда.

- **REDS (`scripts/machine_gate_tests/test_machine_gate_lock.py`):**
  1. `test_grant_writes_window_and_drops_waiting` — замок `coordinator: c1 | since x` / `waiting: s2 | heavy | a | ~3 min` /
     `waiting: s3 | heavy | b | ~80 min` / `stand: free`; `grant c1 s2 heavy 20 T3.9 tests` → код 0; строки ровно:
     `coordinator: c1 | since x`, `window: s2 | heavy | T3.9 tests | until ~HH:MM` (regex `\d\d:\d\d`),
     `waiting: s3 | heavy | b | ~80 min`, `stand: free`
  2. `test_grant_refuses` (параметры: `second_window`, `non_coordinator` — `grant s9 …`, `bad_kind` — `fast`,
     `medium_kind` — `medium` (класс команды, не вид окна), `bad_minutes` — `0` и `601`, `pipe_in_what` — `a | b`,
     `no_lock`) → код 2, файл неизменен (сравнение байтов); `no_lock` — файл так и не появился
  3. `test_close_removes_own_window` → код 0, строки `window:` нет, прочее на месте в прежнем порядке
  4. `test_close_refuses` (параметры: `foreign_window` — окно у `s3`, `close c1 s2`; `no_window`; `non_coordinator` —
     `close s9 s2` при окне `s2`) → код 2, файл неизменен
  5. `test_malformed_lock_exit_2` (замки: `window:s2 | heavy` без пробела; `windw: …`; две строки `window:`;
     `window: s2 | fast | x | until ~1`; `window: s2 | medium | x | until ~1`; нет строки `coordinator:`; `window` с 3 полями;
     режимы `heavy s2 echo RAN`, `medium s2 echo RAN`, `--timed medium s2 echo RAN`, `light s2 echo RAN`,
     `grant c1 s2 heavy 5 x`, `close c1 s2`) → код 2, stderr содержит `malformed machine.lock:`, `RAN` в stdout нет;
     для `grant`/`close` файл неизменен
  6. `test_status_prints_lock_and_metrics` (с замком и без) → код 0, есть строки `ram_free_mb: \d+|n/a` и `cpu_load_pct: \d+|n/a`;
     с замком — его строки на месте; без — `machine.lock: none`
  Стражи: `test_live_sample_lock_is_valid` — дословный живой замок 2026-10-13:
  ```
  coordinator: inspector-bottles-84 | since 2026-10-13 12:00
  waiting: inspector-bottles-3e | heavy | T3.9 post-merge Services/robot_comm/tests on main (after owner's word in its session) | ~3 min
  waiting: inspector-bottles-a4 | heavy | qex full reindex — only after the .ignore cause is found, evening | ~80 min
  stand: free
  ```
  `heavy inspector-bottles-3e echo RAN` → код 75 (проверка формата пройдена, окна нет);
  `test_crlf_lock_is_valid` — тот же замок с `\r\n` → тоже 75, не 2.
