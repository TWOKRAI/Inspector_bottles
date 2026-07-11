---
name: project-arch-boundaries-plan
description: "Чистка границ/дублей модулей ВНЕДРЕНА в constructor-master как Ф5-добор (C1-C8) + КЛЮЧЕВОЙ разворот: движок миграций 4.5 идёт в модуль recipe, НЕ generic doc_migration_module"
metadata:
  type: project
---

Сессия 2026-07-10 (9 Fable-агентов + sentrux DSM): разбор ответственности всех модулей + реестр дублирования. Решения **внедрены в governing-план** `plans/2026-07-06_constructor-master/plan.md` как секция **«Ф5-добор — границы и дубли» (задачи C1-C8)** + переформулированы 4.5/5.3. Отдельного плана НЕТ (был удалён, чтобы не плодить governing). Карты-референсы: `docs/audits/2026-07-10_module-responsibility-duplication-map.md` (реестр дублей D/N/V) + `plans/2026-07-06_constructor-master/document-versioning-architecture.md` (миграции, «version ×3»).

**КЛЮЧЕВОЙ разворот по 4.5:** движок миграций dict-документов идёт в **модуль `recipe`** (framework-консолидация RecipeEngine+RecipeManager+migrations+detect), НЕ в отдельный generic `doc_migration_module`. Причина: рецепт — единственный реальный клиент миграций (у config нет, манифест 4.4 не построен) → generic YAGNI. Раннер строим извлекаемым. Задачи C1-C3 закрывают разом D5/D6 + 4.5 + 4.6 + 5.3 (recipe-carve).

**Дубли (в C4-C8):** D1 один CRM-нормализатор (C4) · D2 chain→пул worker_module (C6) · D3 один deep-merge (C5) · D4 единый pipeline — домен из process_module/generic→Plugins, SystemBlueprint→process_manager, механика→chain runnables; дизайн сначала (C6) · D7 actions_module freeze · D8 статистика УЖЕ на месте (hub=персистентность записей, не агрегация — в statistics не тащить; C7) · D9 плагин=коннектор Service↔app, ADR+один дом (C7) · docs-sync (C8).

**Границы:** Q1 EventManager НЕ в event_module (cross-proc; вектор — сворачивание в router, ADR-COMM-001; C7) · Q2 display_module оставить (здоровый leaf).

**Находки-факты:** chain_module 0 живых потребителей (pipeline реально в process_module/generic); frontend_module ~47% дремлющего (v2-зеркала переписанного прототипом); честность MODULES_RESPONSIBILITY_MAP ≈75-80%; LOC в MODULES_STATUS раздуты тестами ×1.5-2. Мёртвый код НЕ трогаем. Связано: [[project-constructor-master-progress]] [[feedback-freeze-over-kill]].
