---
name: project-command-engine-audit
description: P1.1 command-engine audit verdict (2026-05-29) — ActionBus dead in prod, domain-dispatch is the only live engine; "two engines" premise false. Owner keeps actions_module (2026-07-08), ADR-COMM-002 removal not executed
metadata:
  type: project
---

P1.1 command-engine audit сделан 2026-05-29 → `docs/refactors/2026-05_command_engine_audit.md`. Вердикт **A** (один движок = domain-dispatch + pluggable middleware).

**Неочевидная находка (главное):** премиса плана constructor-maturity P1 о «двух конкурирующих движках команд/undo» — **неверна по факту кода**. В проде живёт ОДИН движок (domain-dispatch). `ActionBus` осиротел:
- `_legacy_action_bus` создаётся в app.py, но никуда не передаётся (0 исполняющих потребителей)
- AuditMiddleware и `set_log_writer` в проде НЕ подключены → `Services/sql/action_log` построен, но никогда не работал (audit «потеря» = потеря того, чего не было)
- ROLE_UPDATE через ActionBus мёртв (`RolesPanel(auth_ctx, None)`)
- глобальный undo/redo и History-вкладка — на domain `app_services.commands`
- framework-forms (`FormContext.write→ActionBus`) обходятся прототипом (`form_ctx=None` везде) → связка P1↔P2

**Узкая RBAC-дыра:** field-edit (`SetPluginConfig` через `presenter._on_inspector_field_changed`) НЕ гейтится `tabs.pipeline.edit` — в отличие от toolbar/drop/wire. Не блокер для single-user; точечный фикс ~пара строк.

**Why:** избежать повторного расследования и не строить middleware-машинерию P1 впрок. Сам план отложен — см. [[project-priority-product-over-engine]].

**How to apply:** при возврате к движку — стартовать с этого вердикта (P1.1 закрыт). Перед P1.3 владельцу нужны 2 ответа: нужен ли persistent action_log (комплаенс)? и формат RBAC-фикса. Память может устареть — сверяться с кодом (call-sites дрейфуют).

**Обновление 2026-07-08 (решение владельца):** `actions_module` **не удалять** — «может пригодится», сохраняем как переиспользуемый framework building-block (ActionBus PATCH + SnapshotHistory SNAPSHOT). Значит ADR-COMM-002 (удаление `actions_module`) де-факто **отложен/не исполняется**; при следующем ревью коммуникаций обновить его статус. В доках модулей (`MODULES_RESPONSIBILITY_MAP.md` §2/§4, OVERVIEW, STATUS, CONTRACTS) это зафиксировано: прод-undo = domain `CommandDispatcherOrchestrator`, `actions_module` = сохраняемый building-block, не прод-путь.
