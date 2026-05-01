"""persistence — автоматическое сохранение config-ветвей StateStore на диск.

Экспортирует PersistenceManager — основной класс пакета.
Подключается к StateStoreManager через:
    manager.use(persistence_manager.middleware)
"""
from .persistence_manager import PersistenceManager

__all__ = ["PersistenceManager"]
