# Стартовые промпты полос по дефектам приёмки α (2026-11-11)

Каждый блок — отдельный новый чат. Бриф лежит в ветке `docs/release-1.0-alpha-1.1` (не влита в `main`), поэтому в READ FIRST — абсолютный путь.

## C-87 — сим: непрерывное движение диска

```
ВКЛАДКА: Сим · C-87 · непрерывный энкодер (release-1.0, дефект приёмки α)

ROLE: лид полосы сима (Plugins/sim/scene_source, Plugins/sim/robot_host). Лид координирует и не исполняет: код — агентам по циклу ниже.
READ FIRST:
1. /Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/release-1.0-alpha/plans/release-1.0/lane-tasks/C-87_sim-encoder-extrapolation.md — бриф целиком (DESIGN, REDS, инъекции, живая приёмка).
2. тот же каталог, plans/release-1.0/amendments.md записи 18–20 — вердикт и диагноз.
3. docs/reports/2026-11-10_release-1.0_alpha-runs.md (там же) — числа прогонов.
GOAL: сим рисует диск непрерывно (досчёт энкодера между пачками раз в 0,12 с), чтобы окно §2.8 (py −344,0…−342,0) выполнялось без правки окна.
ACCEPTANCE: бриф, разделы REDS и «Приёмка живая»: замер кадров до/после (шаг 6,6 px ± 1 на каждом кадре), затем 3 прогона scripts/alpha_sim с холодного старта — число заданий в окне по каждому.
PIPELINE: ветка fix/sim-encoder-extrapolation от main; stage 0 reviewer на тексте брифа → слепой tester по REDS (worktree на коммите до правки) → developer → break-injection (предсказания записать ДО прогона) → живой стенд → reviewer. ADR в DECISIONS.md модуля.
BOUNDARIES: не трогать delta_dispatcher.py и фреймворк, line_filter, pixel_to_robot, окна §2.8, рецепты. Окно не расширять: отклонение от спеки — запись в plans/release-1.0/amendments.md.
LOAD: стенд только через bash /Users/twokrai/Project_code/Inspector_bottles/scripts/machine_gate.sh (абсолютный путь); координатора нет, окна берёшь у гейта сам.
COMMITS: feat/fix(sim): … + трейлеры Why:/Layer:/Refs: plans/release-1.0/lane-tasks/C-87_sim-encoder-extrapolation.md; в main не сливать и не пушить без слова владельца.
LIMITS: 2 итерации на цикл, на 3-й — escalation вверх. Бриф tester — с BRIEF-OVERRIDE, если линт требует.
REPORT: по-русски, docs/reports/<дата>_C-87_sim-extrapolation.md, таблица «предсказано / наблюдаемо / совпало», непустой раздел «что оставил открытым», handoff. Первая строка ответа владельцу: «Сим · C-87 · <имя сессии>».
```

## C-86(а) — word_layout: журнал на каждый диск

```
ВКЛАДКА: Полоса С · C-86(а) · журнал сброса диска (release-1.0, дефект приёмки α)

ROLE: лид полосы С (Plugins/processing/word_layout). Лид координирует и не исполняет.
READ FIRST:
1. /Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/release-1.0-alpha/plans/release-1.0/lane-tasks/C-86a_word-layout-silent-drop.md — бриф.
2. тот же worktree: plans/release-1.0/amendments.md записи 18–19; plans/release-1.0/design.md §2.3–§2.4.
GOAL: каждый диск, дошедший до word_layout, оставляет ровно одну строку журнала, включая «пропуск: уверенность ниже порога»; поведение (порог, решение, jobs_emitted) не меняется.
ACCEPTANCE: бриф, REDS 1–6 и «Приёмка живая»: на B, D, C число строк журнала layout равно числу поданных дисков.
PIPELINE: ветка fix/word-layout-silent-drop от main; stage 0 reviewer → слепой tester → developer → break-injection (предсказания ДО прогона) → стенд → reviewer.
BOUNDARIES: точность сети на «М» (C-86 б, ORDER #27) НЕ входит. Порог, ml_inference, рецепты, спеку без записи в amendments.md не менять.
LOAD: стенд через bash /Users/twokrai/Project_code/Inspector_bottles/scripts/machine_gate.sh (абсолютный путь); координатора нет.
COMMITS: fix(word-layout): … + Why:/Layer:/Refs: plans/release-1.0/lane-tasks/C-86a_word-layout-silent-drop.md; без слияния и push по своей воле.
LIMITS: 2 итерации на цикл. Урок: не доверять первому снимку status; run-state на паузе — система стартует без кнопки ЗАПУСТИТЬ.
REPORT: по-русски, docs/reports/<дата>_C-86a_silent-drop.md, непустой «что оставил открытым», handoff. Первая строка: «Полоса С · C-86а · <имя сессии>».
```

## C-88 — Ф: честный outcome у recog

```
ВКЛАДКА: Полоса Ф · C-88 · outcome стопа recog (release-1.0, дефект приёмки α)

ROLE: лид полосы Ф (lifecycle-stop-ownership, multiprocess_framework/modules/process_manager_module). Лид координирует и не исполняет.
READ FIRST:
1. /Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/release-1.0-alpha/plans/release-1.0/lane-tasks/C-88_recog-outcome.md — бриф.
2. process_manager_module/DECISIONS.md «Дополнение (Task 1.10)» D2–D4; тот же worktree: amendments.md записи 18–19, design.md §2.7.
GOAL: у каждого ребёнка после system_shutdown outcome ∈ exited|terminated|killed, у recog тоже; «предел драйвера» как PASS не принимается.
ACCEPTANCE: бриф, REDS 1–4 и «Приёмка живая»: S9 scripts/alpha_sim три раза с холодного старта — 10 детей из 10 exited, None нет.
PIPELINE: шаг 0 — диагноз (investigator, до кода); ветка fix/recog-stop-outcome от main; stage 0 reviewer → слепой tester → исполнитель → break-injection (предсказания ДО прогона) → стенд → reviewer.
BOUNDARIES: §2.7 и проверку скрипта alpha_sim не смягчать; сбой одного ребёнка не валит остальных.
LOAD: стенд через bash /Users/twokrai/Project_code/Inspector_bottles/scripts/machine_gate.sh (абсолютный путь); координатора нет.
COMMITS: fix(process-manager): … + Why:/Layer:/Refs: plans/release-1.0/lane-tasks/C-88_recog-outcome.md; без слияния и push по своей воле.
LIMITS: 2 итерации на цикл, на 3-й — вверх.
REPORT: по-русски, docs/reports/<дата>_C-88_recog-outcome.md, непустой «что оставил открытым», handoff. Первая строка: «Полоса Ф · C-88 · <имя сессии>».
```
