---
name: feedback-pipeline-reuse-plugins-widgets
description: Pipeline node inspector must reuse Plugins-tab per-plugin config widgets (DRY), resolve fields by plugin_name
metadata:
  type: feedback
---

Правило перенесено в `.rules/gui.md` (2026-10-04).

**Why:** прямая директива владельца (2026-05-30): «в pipeline должны использоваться
виджеты из вкладки плагинов для каждого плагина чтобы не повторять код».


Также по Pipeline-редактору (та же сессия): граф НЕ показывает protected-процессы
(`gui` из base.yaml — фильтр в `presenter._topology_to_graph`); auto-layout
применяется при старте (`tab._load_topology`); дисплеи доступны в палитре отдельной
секцией с drag → display-бокс.
