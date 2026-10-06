# MEMORY.md — индекс (≤ 8 КБ, грузится в каждую сессию)
Здесь правила, что срабатывают до того, как о них вспомнят, и указатели. Остальное — по триггеру.
Канон — `docs/claude/memory/` (git); локальная папка Claude Code — кэш. Правило уходит в архив, только став механизмом.
Новая сессия: порядок задач — `plans/queue/ORDER.md`, передача — `ls docs/handoffs`, архив — `_archive/INDEX.md`.

## Указатели (читать ПЕРЕД делом)
- [CRAFT-injection](CRAFT-injection.md) — инъекции, «0 красных», «зелёный под заплатой», вакуумные ассерты
- [CRAFT-tests](CRAFT-tests.md) — тест, дублёр, фикстура, сторож; гейт зелёный подозрительно
- [CRAFT-verdict](CRAFT-verdict.md) — вердикт ревью/приёмки, «не может сломаться», живой дефект
- [CRAFT-config-qt](CRAFT-config-qt.md) — конфиг, схемы Pydantic, Qt-виджеты, qt-mcp
- [CRAFT-by-module](CRAFT-by-module.md) — остальные уроки, сгруппированы по тегу `module:`
- [CRAFT](CRAFT.md) — заглушка-указатель на файлы выше
- [ARCHIVE](ARCHIVE.md) — закрытые треки и перенос 2026-10-04

## 1. Правила на каждую сессию
- qex: сначала `get_indexing_status`, `last_indexed` числом; возраст — в промпт субагента (корневой `CLAUDE.md`)
- Тесты: тестер до кода, инъекция на КАЖДОЕ свойство, ревью запуском (`.claude/CLAUDE.md` «Test authorship»)
- [Ноль наблюдений](feedback_zero_observations_looks_like_a_result.md) — ноль есть результат, когда доказано, что наблюдение шло
- [Ноль красных](feedback_injection_zero_may_mean_the_guards_were_not_collected.md) — база матрицы без `-k`, collected числом
- [Правдоподобное ≠ проверенное](feedback_plausible_is_not_verified.md) — вердикт без вход→выход = совет
- [Об ОТСУТСТВИИ](feedback_an_absence_assertion_needs_a_reachability_check.md) — с парной проверкой достижимости
- [Сторож «хоть раз» слеп](feedback_a_guard_that_counts_at_least_once_is_blind.md) — судить поимённо, не суммой
- [Дублёр верен форме, не протоколу](feedback_a_faithful_fake_still_lacks_the_protocol.md) — одно имя, две двери
- [Чужая сессия в том же дереве](feedback_a_peer_session_shares_the_tree.md) — один писатель, стейджить явные пути
- [commit берёт весь индекс](feedback_commit_takes_the_whole_index.md) — `git add -A` затягивает чужое
- [pre-commit и 2 агента](feedback_precommit_stash_collision_2plus_agents.md) — recovery `git show :path > path`
- [Merge в main](feedback_git_main_merge_hook_traps.md) — `merge: суть` + Why/Layer/Refs; нужен оформленный `/code-review`
- [Субагенты в worktree](feedback_protect_branch_blocks_worktree_subagents.md) — `model` явно; reviewer/tester синхронно
- [RU-вывод и wc врут](feedback_ru_output_encoding_and_wc.md) — cp866, `PYTHONUTF8=1`
- [uv sync сносит необъявленное](feedback_uv_sync_prunes_venv.md) — только `--inexact`
- [Глобальный taskkill](feedback_no_global_taskkill.md) — только TaskStop или PID
- [Апостроф ломает Bash](feedback_bash_tool_unbalanced_quote_breaks_command.md) — скрипты с прозой через Write
- [Хук жив, если проверен настоящим входом](feedback_a_hook_dead_on_windows_by_a_trailing_cr.md) — CR в `read < <(...)`
- [ruff сносит свежий импорт](feedback_ruff_strips_unused_import.md) — импорт и использование одним Edit
- [Посылка плана — гипотеза](feedback_a_plans_premise_expires.md) — блокер воспроизводить, не сверять номера
- [Причина из плана — гипотеза](feedback_the_plans_stated_cause_is_a_hypothesis.md) — симптом верен до числа, причина нет
- [Число без разброса](feedback_a_number_without_spread_across_repeats_is_an_observation.md) — наблюдение, не замер

## 2. Решения владельца (живые)
- [Приоритет — маятник](project_priority_engine_first.md) — порядок в `ORDER.md`
- [Жизненный цикл](project_universal_lifecycle_decision.md) — один scope-владелец подписок, потоков, процессов
- [Framework-first](feedback_framework_first.md) — fix-forward, FREEZE не KILL, меньше слоёв, конструктор
- [Флаг закрыт, когда удалён](feedback_flags_must_not_become_crutches.md) — не костыль
- [Ручки наблюдаемости](feedback_observability_knobs_switchable_at_any_boundary_zero_cost_off.md) — вкл/выкл везде, ноль нагрузки выключенной
- [Один пишущий логгер](feedback_one_log_writer.md) — остальное — вид поверх
- [Память одним модулем](project_memory_module_consolidation.md) — фасад, не размазывать
- [Стек 2026](reference_tech_stack_2026.md) — сверять при правках стека и зависимостей
- [Push, кредит, инструменты](project_owner_push_and_tools_decisions.md) — push/PR разрешены после договорённости с сессиями; serena/graphify — сделать полезными

## 3. Окружение (Windows)
- [venv держит MCP](project_venv_locked_by_mcp.md) — закрыть VS Code перед переустановкой пакетов
- [CUDA torch cu124](project_cuda_torch_setup.md) — PyPI даёт +cpu
- [monotonic 15.6 мс](project_monotonic_resolution_windows.md) — разности меньше 100 мс — на сетку
- [qex runbook](feedback_qex_full_rebuild_runbook.md) — полный реиндекс; [модель по платформам](project_qex_model.md)
- [graphify MCP](project_graphify_mcp_setup.md) — `uv tool install --with mcp`
- [Запуск qt-mcp](reference_qt_mcp_launch.md) — зонд только с env
- [GUI-стенд боевым входом](project_gui_stand_production_entry_only.md) — `INSPECTOR_GUI_UNATTENDED=1`
- [Бэкенд через backend_ctl](feedback_backend_ctl_for_agents.md) — не GUI, не qt-mcp

## 4. Как писать
Урок = ловушка + замер (вход→выход) + триггер; теги `module:` и `mechanism:` во frontmatter; `/core:memory:remember` (только лид; субагент — блок MEMORY LESSON, project-rules §8).
Состояние плана — в plan.md, не сюда. Поиск (все уроки, и ролей тоже): `python scripts/memory/search.py <3-5 слов> [--module id] [--mechanism id]`; словарь механизмов — `TAGS.yaml`.
