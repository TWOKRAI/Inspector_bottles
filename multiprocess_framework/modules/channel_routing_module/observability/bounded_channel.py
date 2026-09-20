# -*- coding: utf-8 -*-
"""
BoundedChannel — потокобезопасный bounded-канал с политикой переполнения.

Примитив уровня 0 для ObservabilityHub: складывает pickle-safe dict-записи в
кольцевой буфер фиксированной ёмкости. При переполнении НЕ блокирует
эмиттера (hot-path), а роняет запись по выбранной политике и растит счётчик
потерь (урок Ф3.3: «терять можно, молчать — нельзя»).

Модель доставки — pull: владелец забирает накопленное через drain() (по такту
heartbeat), а не push-flush фоновым потоком. Поэтому BoundedChannel реализует
IChannel (write/name/close/get_info), но НЕ IBufferStrategy — см. DECISIONS.md
(ADR ObservabilityHub, pull-drain vs IBufferStrategy).

Политики overflow:
    drop_oldest — при полном буфере вытесняется САМАЯ СТАРАЯ запись (deque maxlen).
    drop_newest — при полном буфере новая запись отбрасывается, старые целы.
"""

import threading
from collections import deque
from typing import Any, Deque, Dict, List

from ..interfaces import IChannel

DROP_OLDEST = "drop_oldest"
DROP_NEWEST = "drop_newest"
_OVERFLOW_POLICIES = (DROP_OLDEST, DROP_NEWEST)


class BoundedChannel(IChannel):
    """Кольцевой bounded-буфер записей с учётом потерь (thread-safe).

    Пример:
        ch = BoundedChannel("worker.log", capacity=1024)
        ch.write({"message": "hi"})
        records = ch.drain()      # [{'message': 'hi'}]; буфер пуст
        ch.dropped                # число вытесненных записей
    """

    def __init__(
        self,
        name: str,
        capacity: int = 1024,
        overflow: str = DROP_OLDEST,
    ) -> None:
        """
        Args:
            name:     Уникальное имя канала (например "worker_module.log").
            capacity: Максимум записей в буфере (>= 1).
            overflow: Политика переполнения: "drop_oldest" | "drop_newest".
        """
        if capacity < 1:
            raise ValueError(f"capacity должен быть >= 1, получено {capacity}")
        if overflow not in _OVERFLOW_POLICIES:
            raise ValueError(f"overflow должен быть одним из {_OVERFLOW_POLICIES}, получено {overflow!r}")

        self._name = name
        self._capacity = capacity
        self._overflow = overflow
        self._lock = threading.Lock()
        # drop_oldest реализуется maxlen-деком (вытеснение слева при append);
        # drop_newest — обычным деком с ручной проверкой заполнения.
        maxlen = capacity if overflow == DROP_OLDEST else None
        self._buffer: Deque[Dict[str, Any]] = deque(maxlen=maxlen)
        self._dropped = 0
        self._written = 0

    # ------------------------------------------------------------------
    # IChannel
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "memory"

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Положить запись в буфер (не блокирует при переполнении).

        Returns:
            {"status": "success", "channel": name, "dropped": <накопленный счётчик>}
        """
        with self._lock:
            if self._overflow == DROP_OLDEST:
                # deque(maxlen) сам вытеснит старейшую — считаем факт вытеснения.
                if len(self._buffer) == self._capacity:
                    self._dropped += 1
                self._buffer.append(data)
            else:  # drop_newest
                if len(self._buffer) >= self._capacity:
                    self._dropped += 1
                    return {"status": "dropped", "channel": self._name, "dropped": self._dropped}
                self._buffer.append(data)
            self._written += 1
            return {"status": "success", "channel": self._name, "dropped": self._dropped}

    def close(self) -> None:
        """Закрыть канал: остаток буфера засчитывается В ПОТЕРИ, а не исчезает.

        **Task 3.3, дефект Д-2.** Прежняя редакция звала ``clear()`` — и принятые
        записи пропадали молча: воспроизведено при ``capacity=8`` и 10 записях —
        до закрытия ``depth=8 dropped=2 written=10``, после ``depth=0 dropped=2``.
        Восемь принятых записей исчезали, и ни один счётчик этого не говорил.
        Теперь инвариант «принято = отдано + потеряно» держится и на аварийном
        пути (закрытие без слива), а не только на пути через ``drain()``.
        Владелец, который ХОЧЕТ забрать остаток, зовёт ``drain()`` до ``close()``:
        тогда буфер пуст и досчитывать нечего — двойного счёта нет.
        """
        with self._lock:
            self._dropped += len(self._buffer)
            self._buffer.clear()

    def get_info(self) -> Dict[str, Any]:
        """Снимок канала. Все четыре числа сняты ПОД ОДНИМ локом (Task 3.3, Д-3).

        Прежняя редакция читала ``depth`` под локом, а ``dropped``/``written``
        уже после его освобождения: при живом писателе снимок расходился на
        единицу, и всякий, кто сверяет по нему равенство литералом, видел флак,
        а не дефект.
        """
        with self._lock:
            depth = len(self._buffer)
            dropped = self._dropped
            written = self._written
        return {
            "name": self._name,
            "type": self.channel_type,
            "active": True,
            "capacity": self._capacity,
            "overflow": self._overflow,
            "depth": depth,
            "dropped": dropped,
            "written": written,
        }

    # ------------------------------------------------------------------
    # Расширение под pull-модель (не часть IChannel)
    # ------------------------------------------------------------------

    def drain(self) -> List[Dict[str, Any]]:
        """Атомарно забрать все накопленные записи и опустошить буфер.

        **Критическая секция — O(1), а не O(ёмкость) (Task 3.3).** Под локом
        меняется только ссылка на дек; копирование в список происходит уже
        снаружи. Это свойство КОНСТРУКЦИИ, и стережёт его тест, замеряющий
        удержание лока изнутри секции.

        **Ускорения постановки эта форма не обещает, и вот почему это сказано
        прямо.** Задача пришла с готовым объяснением «постановка ждёт копию
        буфера, отсюда её хвост» — оно **не подтвердилось ни разу**. Прогоны с
        достаточным числом повторов не показывают разницы между редакциями
        вовсе: тот же хвост писателя даёт конкурент, который лока не берёт, и
        выбросы приходятся на одни и те же повторы у всех конкурентов — то есть
        это шум машины. Прежние числа сняты на слишком коротких прогонах, а
        часть из них вдобавок сравнивала объём работы конкурента, а не факт
        взятия лока. Поэтому здесь нет ни числа, ни слова «лечение»: короткая
        критическая секция оставлена как инвариант, а не как исправление
        измеренной регрессии.

        Новый дек создаётся с тем же ``maxlen``, что и исходный, — иначе
        ``drop_oldest`` после первого же слива перестал бы вытеснять и потолок
        стал бы декоративным.
        """
        maxlen = self._capacity if self._overflow == DROP_OLDEST else None
        fresh: Deque[Dict[str, Any]] = deque(maxlen=maxlen)
        with self._lock:
            items = self._buffer
            self._buffer = fresh
        return list(items)

    @property
    def dropped(self) -> int:
        """Сколько записей потеряно из-за переполнения (монотонно растёт)."""
        return self._dropped

    @property
    def written(self) -> int:
        """Сколько записей успешно принято (без учёта потерь)."""
        return self._written

    @property
    def capacity(self) -> int:
        return self._capacity

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)
