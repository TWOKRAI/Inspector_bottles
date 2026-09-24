# Task 1.2 (lifecycle-stop-ownership) — ревью

- **Дата:** 2026-09-24 · **Ревьюер:** `reviewer` (Opus), синхронно, 2 итерации
- **Вердикты:** итерация 1 — REQUEST_CHANGES; итерация 2 — APPROVE_WITH_NITS (ниты закрыты ведущим в ADR-PMM-030)
- **Файлы:** `core/process_registry.py`, `process/process_manager_process.py`, `queues/core/reader_gone.py`,
  тесты `test_pm_marks_gone_reader_{acceptance,hazards}.py`, ADR-PMM-030

## Итерация 1 — REQUEST_CHANGES

1. **Блокер — TOCTOU в `restart_process`.** Отказ после системного стопа проверялся один раз, на входе. Спавн шёл
   после `stop_process` (0.1–7 с). Сценарий: `restart_process("Reader")` в потоке (старый ребёнок игнорирует stop,
   `stop_process_timeout=0.5`), через 0.1 с `sys_stop.set()` + `registry.stop_all(0.5)` параллельно (как `shutdown()`).
   Результат 3/3: `restart_process returned: True`, `new incarnation spawned after system stop: True alive: True`,
   `stop_all results: {'Reader': True}` при живом Reader; метка встала на переиспользуемую очередь живого преемника:
   `before_create False → after_stop_all True`. **Закрыто итерацией 3:** отказ перенесён в `create_and_register`.
2. **Метка по имени, а не по воплощению** (`confirmed_dead`). **Закрыто:** `_mark_confirmed_dead(name, observed)`;
   ведущий добавил случай незапущенного преемника (`pid is None`).
3. **ADR-абзац про переиспользование очередей в switch/rollback неверен.** `unregister → register` → новый объект
   (`same object: False | old marked: True | new marked: False`); с `reuse_queues=True` объект тот же. **Закрыто.**

Ответы на вопросы брифа: расхождения `Process.name` и имени в реестре очередей нет; `_boot_create_and_start` безопасен
(идёт до run/shutdown); опрос через `is_alive()` → `waitpid(WNOHANG)` забирает детей, побочные эффекты `join` не теряются,
≤ 20 `waitpid`/с на ожидающего; шпион в тесте тестера держит только аргумент вызова, свойство держит авторский
`test_restart_never_exposes_mark_on_reused_queue` (инъекция «restart marks» его роняет).

Инъекции ревьюера (pytest-плагин, дерево не тронуто), обе совпали с предсказанием: последовательный `join` вместо
опроса → красный только `[reader-exits-on-stop-listed-last]` (exitcode=-15); без try/except в `_set_reader_gone` → только
`test_marking_failure_does_not_break_stop`.

## Итерация 2 — APPROVE_WITH_NITS

- Репро блокера 3/3: `restart_process returned: False`, `new incarnation spawned after system stop: False alive: None`,
  `stop_all results: {'Reader': True}`, `final is_reader_gone: True`. (`refusal warnings: []` — артефакт скрипта: у реестра
  там `logger=None`.)
- Регресса нет: радиус `1202 passed, 25 skipped`; два файла Task 1.2 — `19 passed` 3 раза подряд; файл тестера не менялся.
- Нит 1 (п.5 ADR): текст «или зарегистрированный не жив» шире кода (`pid is not None and not is_alive()`). **Исправлено.**
- Нит 2 (п.4 ADR): проверка на входе `start_process` — не «ранний отказ», а единственная защита пути `_topology_create` →
  (стоп) → `_topology_start` → `start_process`, мимо `create_and_register`; держит её тест 7(b). **Исправлено.**

## Не проверено / ненадёжно (ревьюер)

- Инъекции ведущего по итерации 3 приняты по брифу, не повторены.
- Отказ `create_and_register` посреди switch на системном стопе уводит его в rollback, в boot — в cleanup: ожидаются шумные
  ERROR-строки, живьём не проверено.
- `restart_reuse_queues: false` — брошенные старые очереди метку не получают; не проверено.
