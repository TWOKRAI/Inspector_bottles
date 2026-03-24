"""
ManagerStatsMixin — единый паттерн статистики для подменеджеров SRM.

Использование в memory, queues, events:
    class XxxManager(BaseManager, ..., ManagerStatsMixin):
        def get_stats(self) -> Dict[str, Any]:
            section_stats = {...}  # специфичные метрики
            return self._merge_stats("section_name", section_stats)
"""

from typing import Any, Dict


class ManagerStatsMixin:
    """
    Mixin для менеджеров с секционной статистикой.

    Добавляет _merge_stats(section_name, section_stats) — объединяет
    base.get_stats() от родителя с секцией под заданным ключом.
    """

    def _merge_stats(self, section_name: str, section_stats: Dict[str, Any]) -> Dict[str, Any]:
        """
        Объединить базовую статистику (super().get_stats()) с секцией.

        Args:
            section_name: ключ секции (memory, queues, events)
            section_stats: словарь метрик секции

        Returns:
            Объединённый dict для get_stats()
        """
        base = super().get_stats() if hasattr(super(), "get_stats") else {}
        if isinstance(base, dict):
            base = dict(base)
            base[section_name] = section_stats
        else:
            base = {section_name: section_stats}
        return base
