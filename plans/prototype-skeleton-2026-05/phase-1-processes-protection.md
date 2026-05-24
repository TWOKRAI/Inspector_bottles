# Phase 1 — Защита системных процессов

> **Master plan**: [plan.md](plan.md)
> **Branch**: `feat/processes-protection`
> **Дней**: 1
> **Зависимости**: Phase 0
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-1-processes-protection.md, plans/prototype-skeleton-2026-05/plan.md`

## Цель

В ProcessesTab нельзя удалить/остановить GUI и orchestrator.

## Файлы

- `multiprocess_prototype/frontend/widgets/tabs/processes/_panels.py` — `AllProcessesPanel`
- `multiprocess_prototype/frontend/widgets/tabs/processes/presenter.py` — `ProcessesPresenter`
- Process-схема (data_schema) — добавить `protected: bool = False`

## Шаги

1. В blueprint для `gui` и `orchestrator` (process_manager) выставить `protected: true`.
2. Presenter: `can_delete(name) → not protected`. View disable кнопок «Удалить»/«Остановить» для protected.
3. Action-handler — early return + toast «системный процесс защищён».

## Acceptance

- На GUI и orchestrator кнопки disabled с тултипом.
- Остальные процессы управляются как раньше.
- 3-5 unit-тестов.
