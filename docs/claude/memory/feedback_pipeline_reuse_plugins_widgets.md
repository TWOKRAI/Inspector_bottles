---
name: feedback-pipeline-reuse-plugins-widgets
description: Pipeline node inspector must reuse Plugins-tab per-plugin config widgets (DRY), resolve fields by plugin_name
metadata:
  type: feedback
---

Pipeline-вкладка должна переиспользовать виджеты конфигурации плагина из вкладки
Plugins для карточки выбранной ноды — НЕ дублировать рендер полей.

**Why:** прямая директива владельца (2026-05-30): «в pipeline должны использоваться
виджеты из вкладки плагинов для каждого плагина чтобы не повторять код».

**How to apply:**
- Поля плагина резолвятся по `plugin_name` (= имя регистра), НЕ по `process_name`.
  `RegistersManager.get_fields(plugin_name)` — тот же путь, что `PluginsPresenter.
  get_register_fields` (`tabs/plugins/_sections.py`).
- Редакторы строит `CardsFieldFactory.create(field_info)` (`frontend/forms/factory.py`),
  как `RegisterView` в Plugins-вкладке.
- В `NodeInspectorPanel.show_plugin_node` передавать `plugin_name` (из `plugins[0]`),
  значения — из `PluginInstance.config`; `_current_process` остаётся process_name
  (цель `SetPluginConfig`).
- Связано: [[feedback-mvp-pattern]], [[feedback-constructor-modularity]].

Также по Pipeline-редактору (та же сессия): граф НЕ показывает protected-процессы
(`gui` из base.yaml — фильтр в `presenter._topology_to_graph`); auto-layout
применяется при старте (`tab._load_topology`); дисплеи доступны в палитре отдельной
секцией с drag → display-бокс.
