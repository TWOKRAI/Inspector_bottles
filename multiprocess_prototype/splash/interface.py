"""Контракты пакета заставки. Импортирует только ``typing``: модуль грузится в процессе заставки."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SplashLinkProtocol(Protocol):
    """Связь лончера с процессом заставки."""

    process: Any

    def report(self, leaf: dict) -> None:
        """Отдать лист этапа ``launch``. Не бросает; до прихода порта хранится последний лист."""
        ...

    def publish_port(self, environ: Any, wait_s: float = ...) -> bool:
        """Записать порт заставки в ``environ``; ``False`` — порта нет, заставка закрыта. Не бросает."""
        ...

    def close(self) -> None:
        """Закрыть заставку. Идемпотентно."""
        ...


@runtime_checkable
class SplashControllerProtocol(Protocol):
    """Причина закрытия окна заставки."""

    def request_close(self, reason: str) -> None:
        """Поставить причину закрытия. Любой поток; Qt не трогает."""
        ...

    def poll(self) -> str | None:
        """Причина закрытия или ``None``. Только Qt-поток."""
        ...


@runtime_checkable
class LeafSender(Protocol):
    """Отправитель листа прогресса в заставку. Не бросает."""

    def __call__(self, progress_id: str, leaf: dict) -> object: ...
