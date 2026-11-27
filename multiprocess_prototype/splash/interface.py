"""Контракты пакета заставки. Импортирует только ``typing``: модуль грузится в процессе заставки."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SplashLinkProtocol(Protocol):
    """Связь лончера с процессом заставки."""

    process: Any

    def report(self, leaf: dict) -> None:
        """Отдать лист этапа ``launch``.

        Pre: ``leaf`` — dict листа прогресса (есть ``percent``).
        Post: не бросает. Порт известен — лист отправлен; ещё нет — хранится только последний и уходит,
        когда порт придёт; после ``close`` вызов пустой.
        """
        ...

    def publish_port(self, environ: Any, wait_s: float = ...) -> bool:
        """Дождаться порта заставки и записать его в ``environ``.

        Pre: главный поток, до spawn системы; ``environ`` — изменяемое отображение строк.
        Post: не бросает. ``True`` — порт записан в ``environ``. ``False`` — ``environ`` не тронут; если
        порта не дождались, заставка погашена без паузы. Главный поток не держится секундами.
        """
        ...

    def close(self) -> None:
        """Закрыть заставку.

        Pre: нет.
        Post: процесс получил EOF на stdin и дождан (или убит); держатель освобождён; повтор пустой.
        """
        ...


@runtime_checkable
class SplashControllerProtocol(Protocol):
    """Причина закрытия окна заставки."""

    def request_close(self, reason: str) -> None:
        """Поставить причину закрытия.

        Pre: любой поток, включая обработчик сигнала.
        Post: поставлен только флаг (Qt не тронут); первая причина остаётся.
        """
        ...

    def poll(self) -> str | None:
        """Причина закрытия или ``None``.

        Pre: только Qt-поток.
        Post: не блокирует; запрошенная причина старше ``gui_done`` и ``timeout``. Причина уже запрошена —
        возвращается сразу, посылки из сокета не читаются; иначе принятые посылки применены к окну.
        """
        ...


@runtime_checkable
class LeafSender(Protocol):
    """Отправитель листа прогресса в заставку. Не бросает."""

    def __call__(self, progress_id: str, leaf: dict) -> object:
        """Отправить лист.

        Pre: ``progress_id`` — непустая строка без точек; ``leaf`` — dict листа прогресса.
        Post: не бросает и не блокирует; доставка не гарантируется.
        """
        ...
