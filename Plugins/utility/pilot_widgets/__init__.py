"""pilot_widgets — тестовый плагин для проверки framework-фасадов form-фабрики.

Изолированный стенд для smoke-тестов Phase 2.0+ rollout:
- Register с полями всех целевых типов (bool сначала; int/float/literal позднее).
- Worker LOOP логирует значения регистра и публикует tick-счётчик в state_proxy.
- GUI ↔ worker bidirectional binding: toggle в Plugins-tab → IPC → log;
  worker увеличивает tick → state_proxy → TopologyBridge → silent UI update.
"""
