---
name: no-qt-popups-offscreen
description: "Все агентские/фоновые прогоны тестов и харнесса — с QT_QPA_PLATFORM=offscreen: всплывающие Qt-окна (LoginDialog и т.п.) вешают агентов и мешают владельцу"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 0930f3cb-ce11-4c8b-94d5-186f9a19db5e
---

Правило владельца (2026-07-13): «всплывающих окон я бы старался избегать». Реальный случай: G.1-агент дважды застревал «жду фоновый прогон тестов» — prototype-сьют/харнесс спавнил Qt-окна поверх рабочего стола (известно с Ф0.4: BACKEND_CTL=1 ≠ headless, gui-процесс всё равно поднимал LoginDialog).

**Why:** окно блокирует прогон (модальный диалог ждёт человека) и всплывает поверх работы владельца.

**How to apply:** каждый запуск pytest/BackendHarness/replay из агента или фона — с env `QT_QPA_PLATFORM=offscreen`; в брифы исполнителей включать это явно; perf-рецепты собирать без gui-процесса (strip_gui/headless-ядро). Честный headless — Ф1.3 BackendHarness. См. [[backend-ctl-for-agents]].
