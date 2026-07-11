"""Plugins — vocabulary плагинов уровня проекта.

Каждый плагин — переиспользуемая единица, не привязанная к конкретному
приложению. Импортирует только framework + Services. Hard-ban на
импорт application-слоя (multiprocess_prototype/...) — enforced правилом
``Plugins/* → multiprocess_prototype/*`` в ``.sentrux/rules.toml``.

Автообнаружение: ``PluginRegistry.discover(str(PROJECT_ROOT / "Plugins"))``
из ``multiprocess_prototype/main.py``.

Побочный эффект импорта (C6 шаг b): подтягивает ``_shared.fanin`` → регистрирует
доменную фабрику inspector'ов в framework-реестре. Любой процесс, грузящий плагин из
``Plugins.*``, исполняет этот ``__init__`` → фабрика доступна ``GenericProcess`` ДО
``_init_data_pipeline`` (плагины бутятся раньше). Framework сам Plugins не импортирует.
"""

from . import _shared as _shared  # noqa: F401 — self-register fanin-фабрики (C6 b)
from ._shared import fanin as _fanin  # noqa: F401
