"""
ErrorMethods — вспомогательный класс методов отслеживания ошибок.

Начиная с текущей версии метод _track_error определён непосредственно
на классе ObservableMixin.

Цепочка fallback при вызове _track_error:
    'error'.track_error → 'errors'.track_error → 'error'.record_error
"""


class ErrorMethods:
    """
    Вспомогательный класс для методов отслеживания ошибок.

    Метод _track_error теперь является методом класса ObservableMixin.
    """

    @staticmethod
    def create_error_methods(instance, call_manager_func):
        """
        No-op: метод отслеживания ошибок определён на классе ObservableMixin.

        Оставлен для обратной совместимости.
        """
