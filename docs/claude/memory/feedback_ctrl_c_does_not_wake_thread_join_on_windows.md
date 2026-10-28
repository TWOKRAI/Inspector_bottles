---
name: feedback_ctrl_c_does_not_wake_thread_join_on_windows
description: "Ctrl+C на Windows не будит Thread.join (scope.close): KeyboardInterrupt поднимается после ожидания и пропускает аварийный шаг в finally / Ctrl+C does not wake Thread.join on Windows; unguarded close in finally skips the restore"
module: [services/code_reader, base_manager]
mechanism: [concurrency, windows-env]
metadata:
  type: feedback
---

**Ловушка.** C-13 (3): зонд `thread_split_probe` перевели с голого `Thread` на `open_scope`/`spawn`.
`finish()` вызывал `self.scope.close()` без защиты, а после него шёл аварийный возврат режимов
камеры. На Windows (Python 3.12.12) Ctrl+C не прерывает `Thread.join` внутри `close`:
`KeyboardInterrupt` поднимается только когда `join` выходит по сроку. Исключение уходило из
`finish()` и из `finally` в `main()` мимо возврата.

**Замер (ревью Sonnet, 2026-10-21):**
- Скрипт `join(4.0)` + `_thread.interrupt_main()` на 1,0 с → `KI raised after 4.00s`.
- Фейк, время ×10, зависший `stop_grabbing`, Ctrl+C на 8,0 с (внутри `close`) → `main() RAISED KeyboardInterrupt`, камера 1/7/40 вместо 0/0/300.
- Старый код в том же сценарии возвращал 0/0/300.
- Зелёные 41 тест и три инъекции лида (I1–I3) этого не видели: ни одна не била в окно `close`.

**Правило.**
- Блокирующее ожидание (`join`, `scope.close`, `Event.wait` без таймаута) на пути аварийной очистки оборачивать тем же защитным шагом, что и остальные шаги (`_step`, глотает BaseException).
- Бюджет ожидания держать коротким: окно, где Ctrl+C «глух», равно бюджету.
- Инъекция «голый close» → красный тест, где `KeyboardInterrupt` бросается из настоящего `close` (тест H3 в `Services/code_reader/tests/test_thread_split_probe_scope.py`).

**Триггер.** Поток переводят под `IScope.spawn` (daemon) или добавляют `scope.close()`/`join()` в `finally`/`finish()` перед возвратом состояния железа.
