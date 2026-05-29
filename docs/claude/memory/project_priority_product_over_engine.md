---
name: project-priority-product-over-engine
description: Owner's current priority (2026-05-29) — run prototype + use functions + build pipeline chains, NOT engine-architecture polish
metadata:
  type: project
---

Владелец явно расставил приоритеты (2026-05-29): цель — **быстрее запустить прототип, использовать его функции и продолжать строить pipeline-цепочки**. Архитектурную «красоту движка» (план `constructor-maturity` P1–P6: примирение command-engine, domain-driven Inspector, granular events, вынос во framework) можно доводить **позже**.

**Why:** прототип — рабочий инструмент инспекции дефектов; ценность сейчас в работающих функциях и цепочках, а не в чистоте внутренней архитектуры. Движок (domain-dispatch) уже признан правильным фундаментом — допиливание не срочно.

**How to apply:** при выборе задач отдавать приоритет продуктовой работе (запуск прототипа, новые функции/плагины, построение цепочек, баги, блокирующие использование). Рефакторинги движка/архитектуры предлагать только если они **блокируют** функциональность, иначе помечать как deferred polish. Не толкать в constructor-maturity план без явного запроса.

**Контекст аудита:** P1.1 command-engine audit сделан и сохранён ([[project-command-engine-audit]] / `docs/refactors/2026-05_command_engine_audit.md`) — готовая разведка на будущее. Вердикт: ActionBus в проде мёртв (0 исполняющих потребителей), domain-dispatch — единственный живой движок; «двух конкурирующих систем» нет. Найдена узкая RBAC-дыра (field-edit `SetPluginConfig` не гейтится `tabs.pipeline.edit`) — не блокер для single-user usage.
