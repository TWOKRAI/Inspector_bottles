"""LatestMailbox — почтовый ящик «последний элемент на ключ».

Purpose: держать НЕ БОЛЬШЕ ОДНОГО ожидающего элемента на ключ. Новый ``put`` вытесняет
старый элемент того же ключа, ключи независимы, память ограничена числом ключей, а не
частотой входа. Предназначен для «показывай только свежее» (кадры на дисплей, процесс
буфера): читатель забирает элемент по ключу, а всё, что не успел забрать, вытеснено.

Public API:
- LatestMailbox(max_keys=64, clock=time.perf_counter)
- put(key, item, nbytes=0) -> bool       — положить, вытеснив прежний элемент ключа
- take(key) -> (item, age_s) | None      — снять элемент ключа (запись удаляется)
- pending_keys() -> list[str]            — ключи с ожидающим элементом (снимок)
- clear() -> None                        — выбросить все ожидающие элементы
- stats() -> dict[str, int]              — ровно 7 счётчиков (см. ниже)

Stability: lite — сигнатуры и набор ключей ``stats()`` менять только через ADR
(ADR-PM-064). Без Qt, без IPC, без зависимостей кроме stdlib; один ``threading.Lock``.

Ключ — непрозрачная строка: ни один метод его не разбирает и не сравнивает с каким-либо
форматом. Исключения не бросаются; предусловия описаны в ``Pre:`` каждого метода.

Счётчики ``stats()``:
- ``put`` — принятые вызовы ``put`` (отвергнутые по ``max_keys`` сюда не входят);
- ``taken`` — элементы, снятые ``take``;
- ``superseded`` — вытесненные заменой + выброшенные ``clear()``;
- ``rejected`` — вызовы ``put``, отвергнутые по ``max_keys`` (всего вызовов = put + rejected);
- ``pending`` — число ключей с ожидающим элементом;
- ``bytes_held`` — сумма ``nbytes`` ожидающих элементов;
- ``max_bytes_held`` — пик ``bytes_held`` (не обнуляется ``clear()``).
Инвариант при любом чередовании вызовов: ``put == taken + superseded + pending``.
"""

import threading
import time
from collections.abc import Callable
from typing import Any

__all__ = ["LatestMailbox"]


class LatestMailbox:
    """Ящик «последний на ключ»: один ожидающий элемент на ключ, потокобезопасный."""

    def __init__(
        self,
        max_keys: int = 64,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        """Создать пустой ящик.

        Pre: ``max_keys >= 1``; ``clock`` — монотонные секунды (по умолчанию
            ``time.perf_counter``: у ``time.monotonic`` на Windows шаг 15,6 мс, и малые
            возрасты округляются в 0).
        Post: ящик пуст, все счётчики равны нулю.
        """
        self._max_keys = max_keys
        self._clock = clock
        self._lock = threading.Lock()
        # ключ -> (элемент, nbytes, время put); порядок словаря = порядок первого put ключа:
        # замена существующего ключа порядок не меняет, а take + новый put ставит ключ в конец
        self._slots: dict[str, tuple[Any, int, float]] = {}
        self._put = 0
        self._taken = 0
        self._superseded = 0
        self._rejected = 0
        self._bytes_held = 0
        self._max_bytes_held = 0

    def put(self, key: str, item: Any, nbytes: int = 0) -> bool:
        """Положить элемент под ключ, вытеснив прежний элемент того же ключа.

        Pre: ``key`` — строка (не разбирается); ``nbytes >= 0`` — размер элемента для
            учёта ``bytes_held``.
        Post: если принят (``True``) — под ключом ровно ``item``, прежний элемент учтён в
            ``superseded``, байты старого вычтены, байты нового добавлены, ``max_bytes_held``
            обновлён один раз после обмена. Замена существующего ключа принимается даже при
            заполненном ``max_keys``. Новый ключ при ``max_keys`` ожидающих ключей
            отвергается (``False``), учитывается только в ``rejected``, элемент не хранится.
        """
        now = self._clock()
        with self._lock:
            old = self._slots.get(key)
            if old is None and len(self._slots) >= self._max_keys:
                self._rejected += 1
                return False
            if old is not None:
                self._bytes_held -= old[1]
                self._superseded += 1
            self._slots[key] = (item, nbytes, now)
            self._put += 1
            self._bytes_held += nbytes
            if self._bytes_held > self._max_bytes_held:
                self._max_bytes_held = self._bytes_held
            return True

    def take(self, key: str) -> tuple[Any, float] | None:
        """Снять элемент ключа вместе с его возрастом.

        Pre: ``key`` — строка.
        Post: если под ключом был элемент — возвращает ``(item, age_s)``, запись удалена
            (``taken`` +1, слот ``max_keys`` освобождён, байты вычтены); ``age_s`` = время
            ``take`` минус время ``put`` ВОЗВРАЩЁННОГО элемента (после замены отсчёт от
            последнего ``put``). Иначе ``None``, ничего не меняется.
        """
        with self._lock:
            # часы читаются внутри замка и до pop: метка put любого элемента взята до его
            # критического участка, поэтому age_s >= 0; сбой часов не снимает элемент
            now = self._clock()
            slot = self._slots.pop(key, None)
            if slot is None:
                return None
            item, nbytes, put_at = slot
            self._taken += 1
            self._bytes_held -= nbytes
        return item, now - put_at

    def pending_keys(self) -> list[str]:
        """Перечислить ключи с ожидающим элементом.

        Pre: нет.
        Post: новый список-снимок под замком; порядок — порядок первого ``put`` ключа
            (замена порядка не меняет; после ``take`` и нового ``put`` ключ идёт как новый).
            Правка списка ящик не меняет.
        """
        with self._lock:
            return list(self._slots)

    def clear(self) -> None:
        """Выбросить все ожидающие элементы.

        Pre: нет.
        Post: ``pending`` и ``bytes_held`` равны нулю, слоты ``max_keys`` свободны;
            выброшенные элементы учтены в ``superseded``; накопительные счётчики и
            ``max_bytes_held`` не обнуляются.
        """
        with self._lock:
            self._superseded += len(self._slots)
            self._slots.clear()
            self._bytes_held = 0

    def stats(self) -> dict[str, int]:
        """Снять счётчики одним согласованным снимком.

        Pre: нет.
        Post: dict ровно из 7 ключей (``put, taken, superseded, rejected, pending,
            bytes_held, max_bytes_held``), значения ``int``; снимок взят под замком, поэтому
            ``put == taken + superseded + pending`` выполняется в любом снимке.
        """
        with self._lock:
            return {
                "put": self._put,
                "taken": self._taken,
                "superseded": self._superseded,
                "rejected": self._rejected,
                "pending": len(self._slots),
                "bytes_held": self._bytes_held,
                "max_bytes_held": self._max_bytes_held,
            }
