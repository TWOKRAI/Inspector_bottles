# Handoff полосы Н (observability-signal-contracts) — после реализации Task 0.1–0.3

Сессия inspector-bottles-19, ветка `refactor/observability-signal-contracts` (worktree `../Inspector_bottles--lane-N`). Отчёты: стадия 0 — `docs/reports/2026-11-21_observability-signal-contracts_0.1-0.3-stage0.md`; реализация — `docs/reports/2026-11-21_observability-signal-contracts_0.1-0.3-impl.md` (там же таблица agentId). Заявка на слияние — `docs/handoffs/2026-11-21_N-merge-request.md`.

Состояние: 0.1–0.3 реализованы, ревью стадии 5 пройдено (0.2 — два раунда, APPROVED), замечания закрыты. Контракт-тесты красные по замыслу (11 штук), зелёнеют в 0.4–0.6, 0.10, 0.10b, 0.11. Рабочее дерево ветки чистое; служебные worktree `lane-N-01..03`, `-t01..03`, `-g01..03` удалять после слияния (в `-g01` остаются незакоммиченные правки GREEN, совпадающие с закоммиченным).

Дальше — только по слову координатора inspector-bottles-2b (по его указанию после 0.3 остановка на границе задачи):
1. Решение по заявке на слияние (вариант 1/2/3) и по размеру Task (`amend` заблокирован).
2. Слот писателя на 0.4–0.6, затем 0.9–0.11, 0.13. Для каждой задачи та же цепочка: INTERFACE → слепой tester один раз на механизм (дерево без `plans/` через `git sparse-checkout --no-cone '/*' '!/plans/'`) → GREEN → инъекции с предсказаниями до прогона → ревью sonnet. Субагентам: не коммитить, не пушить; `uv sync` не выполнять (подменяет CUDA-torch), тесты через `.venv` главного checkout + `PYTHONPATH` на worktree.
3. Учесть записи для следующих задач из раздела «Открыто» отчёта реализации: экспорт `count_outcome` (до 0.5), вложенный отказ в `is_refusal` и `_leaf_result` (0.11), фильтр `_fresh.*` в `read_value` (0.10b), `KeyError` в `get_subtree` (0.10); в тексте Task 0.1 таблица пробы ещё без поправки (поток `tell()`/`seek()`, `Probe(lm).initialize()` — в README уже есть).

Реестр дефектов: внесены C-102 (`test_std_logger_guard`), C-103 (`sentrux`, `no_god_files`). `plans/queue/ORDER.md` не правился.
