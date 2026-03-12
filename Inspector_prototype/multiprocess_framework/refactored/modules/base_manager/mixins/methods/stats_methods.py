"""
StatsMethods — вспомогательный класс методов статистики.

Начиная с текущей версии методы _record_metric/_record_timing определены
непосредственно на классе ObservableMixin.

Приоритет поиска менеджера статистики: 'stats' → 'statistics'.
"""


class StatsMethods:
    """
    Вспомогательный класс для методов статистики.

    Методы _record_metric/_record_timing теперь являются методами класса
    ObservableMixin с приоритетом: 'stats' имеет приоритет над 'statistics'.
    """

    @staticmethod
    def create_stats_methods(instance, call_manager_func):
        """
        No-op: методы статистики определены на классе ObservableMixin.

        Оставлен для обратной совместимости.
        """
