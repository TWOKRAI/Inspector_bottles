# MEMORY — index

> **Status: empty by design.** Пусто на старте, заполняется автоматически по
> правилам `auto memory` из системного промпта (или вручную через `/core:memory:init`).

## Что это

Project-local memory store — `.claude/memory/`, git-tracked, портативна вместе
с репо. Каждая запись — отдельный `.md` файл с frontmatter (`name`,
`description`, `metadata.type`, опц. `metadata.last-verified: YYYY-MM-DD`).
Этот файл — только индекс (одна строка на запись).

Правила записи/чтения, типы (`user`/`feedback`/`project`/`reference`), capture
rail — `.claude/CLAUDE.md` → «Memory (OVERRIDE)». Механический контроль —
`.claude/plugins/core/scripts/memory_lint.py`.

## Формат строки

```
- [Title in ~50 chars](filename.md) — one-line hook (whole line ≤ 150 chars)
```

Строка целиком — ≤ 150 символов (порог `line-too-long` линта). Например:

```
- [Russian-only user-facing output](feedback_russian.md) — все ответы и docs на русском
- [User is solo dev](user_role.md) — single maintainer, no team conventions
```

## Команды

- `/core:memory:init` — создать первый каркас (только в новом проекте).
- `/core:memory:status` — что сейчас лежит в `.claude/memory/`.
- `/core:memory:search <query>` — найти запись по содержанию.
- `/core:memory:remember [урок]` — захватить урок вручную.

## Секции

### Feedback
- [Собирать из фреймворка как конструктор](feedback_build_from_framework_as_constructor.md) — процессы, воркеры, роутер, recipe; фронт тоже
- [Сигнал «отпусти соседа» — в момент факта](feedback_unblocking_signal_at_the_moment_of_fact.md) — 13 тестов зелёные, живой стоп как до правки
- [Новый план — среди соседей](feedback_a_new_plan_must_be_placed_among_its_neighbours.md) — таблица владения + обратные ссылки в чужие планы
- [Имена отчётов — с префиксом плана](feedback_review_file_names_need_plan_prefix.md) — task-1.2-* заняты параллельным планом
- [Bash heredoc схлопывает обратные слеши](feedback_bash_heredoc_collapses_backslashes.md) — `\xff` в литерале → байт; такие файлы — через Write
- [ctypes setattr по чужому имени молчит](feedback_ctypes_setattr_unknown_field_is_silent.md) — тест подаёт нули и зеленеет; проверять _fields_
- [Страховка маскирует основную правку](feedback_safety_net_masks_primary_fix.md) — ломать основное при живой страховке
- [Общий откат синглтона ломает импорт-состояние](feedback_global_rollback_breaks_import_time_state.md) — мерить против main
- [Радиус слияния мимо контракт- и живых тестов](feedback_merge_radius_skips_live_and_contract_tests.md) — без --backend-live живые в skipped
- [Лог из shutdown() не доходит до стора](feedback_shutdown_logs_miss_the_store.md) — stop() снимает store-tap раньше; kwargs в extra.context
- [Инъекции — только по закоммиченному коду](feedback_injection_scripts_on_committed_code.md) — checkout съел фикс; zsh не бьёт $VAR
- [Харнесс страницы слеп к браузеру](feedback_node_page_harness_blind_to_browser_defaults.md) — B1: пробел жал кнопку в фокусе; в VS Code браузер — через @browser
- [Широкий except в кадровом цикле прячет мёртвый механизм](feedback_broad_except_in_frame_loop_hides_dead_mechanism.md) — лента едет, объектов нет, тесты зелёные
- [Стенд и тесты: протокол между сессиями](feedback_shared_stand_and_tests_protocol.md) — stand.lock measure/functional, замер по SHA, A/B
- [Слияние: тип feat, не merge](feedback_merge_commit_needs_feat_type.md) — хук режет merge(...), -F - не читает stdin

### User
_(empty)_

### Project
- [Порядок работ: plans/queue/ORDER.md, робот → слои сима](project_work_order_2026_09_22_line_sim_then_pult.md) — приоритет владельца 09-26
- [GUI: рецепт и auth — бэкенд, Пульт — сервис](project_gui_services_composition_2026_09_23.md) — сборка из сервисов, 09-23
- [Железо владельца и роли машин](project_hardware_roles_2026_09_23.md) — RTX 3050 4 ГБ = симулятор, Orin NX 16 = линия
- [ГЛАВНАЯ ЦЕЛЬ: выявлять требования к мощности](project_capacity_planning_goal.md) — не успевает → чей этап и во что упёрлись: код → язык → железо → несколько ПК, до бюджета
- [Бенч мощности — одна команда на любом железе](project_portable_capacity_bench.md) — Orin NX/Linux, паспорт машины, самопроверка часов
- [GUI-конструктор: слои и эталоны](project_gui_constructor_layers_2026_09_26.md) — fw=конструктор, прототип тонкий, minimal_gui, 09-26

### Reference
- [Мануалы Delta RL/CVT и факты из них](reference_delta_rl_manual.md) — ось «RZ», 0x3000 retained, TimerRead, Lua≥5.2

---

> Не путать с `~/.claude/projects/<project>/memory/` (нативный путь Claude
> Code) — мы намеренно переопределяем его на `.claude/memory/` ради
> портативности. Per-project, не входит в seed.
- [CTO: pass model fable explicitly](feedback_cto_spawn_explicit_fable.md) — frontmatter alone ran cto on Opus
- [Windows CPU: psutil is tick-sampled](feedback_windows_cpu_psutil_tick_sampled.md) — use QueryProcessCycleTime; monotonic has 15.6 ms steps
- [line_sim stand: preset.commit from a worktree](feedback_line_sim_stand_preset_from_worktree.md) — temp .yaml + catalog beside it; revert via sed, restore CRLF
- [cv_threads: OpenCV pool per process](feedback_cv_threads_tuning.md) — tune per recipe by measurement; default 2, not our workers
- [Fake without the attribute the rule reads](feedback_fake_missing_attribute_vacuous_test.md) — earlier branch rejects it, test green for the wrong reason; assert the reason
