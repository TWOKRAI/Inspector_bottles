---
name: project-constructor-master-progress
description: "constructor-master: Ф0-Ф1 в main, Ф2.1 и трек F готовы; MERGE-GATE F ждёт вердикта владельца по modularity-критерию"
metadata: 
  node_type: memory
  type: project
  originSessionId: 05a29a24-fbc4-4241-8e6f-a55d2a6b5db0
---

Мастер-план `plans/2026-07-06_constructor-master/` в исполнении с 2026-07-06.

- Ф0 ЗАКРЫТ (merge f156589b); **Ф1 ЗАКРЫТ и вмержен в main 2026-07-07** (вкл. 1.6 verify-probe; 1.8 record/replay — решение на G3). Ветка Ф2 — `feat/constructor-f2`.
- **1.6 нашёл реальный баг**: driver.set_register был молчаливым no-op (слал `plugin_name`, канон — `{register, field, value}`); live-тест зеленел на чужих heartbeat-дельтах. Урок: live-acceptance без readback-проверки — ложная зелень.
- **Ф2.1 ctx.health ГОТОВ** (c9f825e3+f0fcbcb8, ADR-PM-010): схема `processes.<name>.health.*` — контракт, публикация через heartbeat self-publish, откат `INSPECTOR_HEALTH_LOG_ONLY=1`, команды `health.report/status`. Дальше 2.2 (breaker) → 2.3 → 2.4∥2.5.
- **Трек F ЗАВЕРШЁН (F.1–F.6)** в worktree `refactor/constructor-godsplit`: presenter 1860→595, factory→пакет, inspector_panel 1170→632 (+compat-швы ~180 LOC — снять при перенацеливании тестов на секции). Proto-сьют 2932 passed.
- **MERGE-GATE F: 3 из 4 критериев PASS** (pytest, контракты вкладок, qt-smoke обоих рецептов — все процессы running, gui принимает кадры). **FAIL: sentrux modularity 5650 ≈ baseline 5652 (нужно ≥5902)** — метрика считает cross-module рёбра и НЕ видит разрез god-файлов внутри пакета; критерий был некалиброван. Ждёт вердикта владельца.
- qt-smoke рецептов гонять так: из worktree/checkout `BACKEND_CTL=1 BACKEND_CTL_PORT=<уник> INSPECTOR_PID_FILE=<свой> python -c "main('recipes/<рецепт>.yaml')"` + driver.worker_status по каждому процессу; авто-логин — `multiprocess_prototype/dev_settings.py` (untracked, копировать в worktree руками); shutdown-hang — убивать SIGKILL по PID-файлу.
- Baseline: sentrux quality 7174 / modularity 5652. FPS hardware-gated (Ф7 G.1).
- Стратегия делегирования: teamlead (opus) на M-задачи, ревью на мне. Уроки live-тестов агента — `.claude/agent-memory/teamlead/feedback_live_harness_tests.md`.
- Идея app_module «рыба» — [[project-arch-refactor]], дизайн в plans/2026-07-06_constructor-master/app-template-idea.md.
