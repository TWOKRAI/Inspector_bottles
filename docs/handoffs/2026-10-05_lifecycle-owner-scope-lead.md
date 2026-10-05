# Хендофф лида lifecycle-owner-scope — после перестройки, спек T1 написан (2026-10-05, пауза по слову владельца)

## Где
- Ветка `feat/lifecycle-owner-scope`, worktree `.claude/worktrees/lifecycle`; `main` влит (`92fd0450f`, после Атласа 0.8 —
  spawn на всех ОС). В `main` НЕ влита, не запушена. Слияние — после T1, по слову владельца.
- venv основной, `PYTHONPATH=<worktree>`, pytest из `multiprocess_framework/modules`; Qt — `QT_QPA_PLATFORM=offscreen`.
  Grep-инструмент не видит worktree — `git grep`. Копии дерева для прогонов — по КОРОТКОМУ пути (`C:/tmpab/...`):
  путь scratchpad > MAX_PATH ломает сбор тестов.
- Состояние на слитом дереве: `base_manager event_module frontend_module process_module` → 4716 passed, 3 skipped, 1 xfailed.

## Сделано за 2026-10-05
- Ф0: 0.1–0.4 DONE (`dbd0d7b23` 0.2, `a3fddf721`/`db8a10cd6` 0.3, `41fc28c29`/`6b3a08a35` 0.4); ревью, слепые тестеры,
  инъекции — `docs/reviews/2026-10-05_task-0.{2,3,4}-*`. Вердикт CTO (b) `CloseReport.kind`.
- Расследование abort: корень — сборка мусора на не-главном потоке разрушает Python-владеемые Qt-объекты.
  `docs/reviews/2026-10-05_lifecycle-abort-root-cause-cto.md` (вердикт CTO, нативные стеки, репродуктор).
- План перестроен (`c42e7de9a`): одна задача T1 «политика памяти GUI-процесса»; 0.1–0.3, Ф1, Ф3, Ф4 — FREEZE;
  Ф2/Ф5 — требования в будущий мегаплан GUI (GUI — сервис-клиент по транспорту, локально и по Ethernet).
- Спек T1: `plans/2026-10-03_lifecycle-owner-scope/task-T1.md` (manager, 22.5 КБ) — ЕЩЁ НЕ РЕВЬЮИРОВАН.

## Следующее
1. Ревью спека T1 (reviewer MODE: plan, синхронно, один круг). Вопросы спека: В1 корневой conftest прототипа в T1
   (рек. да), В2 полная сборка на границе теста при цене гейта > 1.30× — CTO, В3 `FW_GC_FREEZE`.
   **Противоречие для ревью:** manager нашёл `GuiProcess(ProcessModule)` с heartbeat и `GcDiscipline` в GUI-процессе —
   CTO писал «ProcessModule в GUI нет» (`multiprocess_prototype/frontend/app.py:461`). Сверить прогоном; спек закрывает
   это правилом «`collect_scheduled` уступает слот владельцу».
2. Слепой тестер T1 в отдельном worktree (короткий путь) на коммите спека → teamlead → инъекции ведущего → одно ревью
   кода → приёмка CTO с числами (цепочка 0/20 native+offscreen, обратный порядок 0/5, полный гейт 0/5 native,
   нарушений gc 0, четыре потока 0/20) → слияние в `main` по слову владельца.
3. Задача больше порога: Brief C — 10 файлов (17 вызовов `gc.enable` в 8 тестовых файлах, не 12 как у CTO).
   Резать на два брифа при ревью спека.

## agentId (повторный вызов дешевле нового)
| Роль | agentId | Видел |
|---|---|---|
| cto (вердикты 0.3 kind, 0.4 якорь, архитектура abort) | `a24323001502ee35d` / `a170928d9286b35e1` | весь трек; второй — расследование и T1 |
| manager (спек T1) | `af68e367b963b0b71` | спек T1 |
| teamlead 0.4 | `a3b451355449b6752` | qt_lifetime (~185k — свежий на T1) |

## Открыто / ненадёжно
- Пороги T1 (пауза ≤ 50 мс, RSS ≤ 1.15×, гейт ≤ 1.30×) — гипотезы; полный гейт под политикой не прогонялся.
- Нативный стек без PDB; Linux CI без abort — причина не выяснена.
- `tests/test_module_tiers.py::test_no_test_dir_is_invisible_to_every_runner` красный на копиях дерева — не разобран.
- Незакоммичены файлы памяти teamlead/tester в `.claude/agent-memory/` этого дерева — решить при слиянии.
- Пустые заблокированные папки `.claude/worktrees/lc-inj`, `lc04-tester` (в git не зарегистрированы) — удалить вручную.
