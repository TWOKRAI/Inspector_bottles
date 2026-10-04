---
name: feedback_all_components_base_manager
description: Owner prefers ALL components inherit BaseManager+ObservableMixin (uniformity over minimalism)
metadata:
  type: feedback
---

Владелец (2026-06-07, при Phase 2 recipe-orchestrator-unify) выбрал: **все компоненты наследуют `BaseManager + ObservableMixin`** для доступа к logger/error/stats менеджерам — даже чистые стратегии (FullReplacePlanner), где side-effects нет.

**Why:** предсказуемость «все компоненты одинаковые, исключений нет» важнее минимализма. Принял осознанно lifecycle-церемонию (initialize/shutdown) как цену единообразия — после честного разбора, что ObservableMixin даёт observability и без наследования.

**How to apply:** новый долгоживущий компонент → паттерн `ProcessModule`: `class X(BaseManager, ObservableMixin)`, `BaseManager.__init__(self, name)` + `ObservableMixin.__init__(self, managers={'logger': pm.logger_manager, 'error': pm.error_manager, 'stats': pm.stats_manager})` + реализовать `initialize`/`shutdown`. PM держит менеджеры как `self.logger_manager/error_manager/stats_manager`. Исключение — чистые трансформеры уже в проде (BlueprintAssembler): не ретрофитить, ошибки через исключение ловит вызывающий. Балансирует с [[feedback_fewer_layers]] (владелец явно перевесил в сторону единообразия здесь) и [[feedback_logger_error_stats_managers]].
