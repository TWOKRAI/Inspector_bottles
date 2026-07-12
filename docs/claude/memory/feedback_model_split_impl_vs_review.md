---
name: model-split-impl-vs-review
description: "Реализацию делегировать агентам на Sonnet 5 / Opus 4.8 (model override в Agent tool); Fable — только план, оркестрация и ревью"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 768c4056-8d38-4ee3-a3f1-d58bf502abff
---

Правило владельца (2026-07-12): агенты-исполнители (developer/teamlead/tester) запускать с `model: "opus"` или `model: "sonnet"`, НЕ на дефолтном Fable. Fable (main loop) оставляет себе декомпозицию, брифы, Fable-ревью до merge и merge-оркестрацию.

**Why:** Fable-агенты жгут лимит сессии (реальный случай: NEW-D1 агент умер на «session limit» посреди разведки); ревью-качество Fable ценнее на ревью, чем на наборе кода.

**How to apply:** в каждом `Agent`-вызове для реализации указывать `model: "opus"` (Senior/M-задачи) или `model: "sonnet"` (S-задачи, тесты, docs); брифовать подробнее — меньшая модель требует более полного контекста. Ревью-verify-агентов (Explore) можно оставлять на дефолте. См. [[formal-review-before-merge]], [[worktree-stale-base]].
