"""Plugins — vocabulary плагинов уровня проекта.

Каждый плагин — переиспользуемая единица, не привязанная к конкретному
приложению. Импортирует только framework + Services. Hard-ban на
импорт application-слоя (multiprocess_prototype/...) — enforced правилом
``Plugins/* → multiprocess_prototype/*`` в ``.sentrux/rules.toml``.

Автообнаружение: ``PluginRegistry.discover(str(PROJECT_ROOT / "Plugins"))``
из ``multiprocess_prototype/main.py``.
"""
