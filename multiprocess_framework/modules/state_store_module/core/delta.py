"""delta.py — Delta (единица изменения) и Transaction (batch дельт).

Delta описывает одно атомарное изменение в дереве состояний.
Transaction группирует несколько Delta в один batch с единым transaction_id.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# STATE_ENVELOPE_MARKER — явный маркер конверта команды state.merge (Ф7 G.2 шаг 4)
# ---------------------------------------------------------------------------

#: Ключ-маркер: помечает dict как КОНВЕРТ команды state.merge (``{path, data,
#: source}``), а не как merge-payload. Ставится билдером (``StateProxy.merge``),
#: читается ``handle_state_merge`` — заменяет прежнюю эвристику «top-level path+data»
#: (shape-sniffing), на которой будущий отправитель с top-level ``path`` тихо
#: замержил бы конверт как payload (RS-ревью 2026-07-13).
STATE_ENVELOPE_MARKER = "_state_merge_envelope"


# ---------------------------------------------------------------------------
# MISSING — sentinel для обозначения отсутствующего значения
# ---------------------------------------------------------------------------


class _MissingSentinel:
    """Sentinel для обозначения отсутствующего значения.

    Singleton. repr = 'MISSING'. Не путать с None — None валидное значение.
    Используется в Delta.old_value (при создании узла) и
    Delta.new_value (при удалении узла).
    """

    _instance = None

    def __new__(cls) -> "_MissingSentinel":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


# Глобальный singleton — единственный экземпляр sentinel
MISSING = _MissingSentinel()

# Строка-метка для сериализации MISSING в dict (IPC-совместимо)
_MISSING_MARKER = "__MISSING__"


# ---------------------------------------------------------------------------
# Delta — иммутабельная единица изменения
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Delta:
    """Одно атомарное изменение в дереве состояний.

    Примеры:
        # Создание нового узла (old_value=MISSING)
        Delta(path="cameras.0.fps", old_value=MISSING, new_value=30, source="gui")

        # Обновление существующего узла
        Delta(path="cameras.0.fps", old_value=25, new_value=30, source="camera_0")

        # Удаление узла (new_value=MISSING)
        Delta(path="cameras.0.fps", old_value=30, new_value=MISSING, source="gui")
    """

    path: str
    """Путь к узлу в дереве, например 'cameras.0.config.fps'."""

    old_value: Any
    """Предыдущее значение. MISSING если узел создаётся впервые."""

    new_value: Any
    """Новое значение. MISSING если узел удаляется."""

    source: str
    """Источник изменения: 'gui', 'camera_0', 'recipe_engine' и т.д."""

    timestamp: float = field(default_factory=time.monotonic)
    """Момент создания дельты (time.monotonic)."""

    transaction_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    """UUID транзакции — связывает дельты одного batch."""

    revision: int = 0
    """Монотонная revision дерева на момент этой мутации (Ф4.9, ADR-SS-014).

    Проставляется TreeStore при создании Delta (глобальный счётчик,
    инкремент на каждую мутацию). Default=0 — обратная совместимость: код,
    создающий Delta напрямую (тесты, MockStore), не обязан её задавать.
    """

    # --- Классификация типа изменения ---

    @property
    def is_create(self) -> bool:
        """True если узел создаётся (old_value is MISSING)."""
        return self.old_value is MISSING

    @property
    def is_delete(self) -> bool:
        """True если узел удаляется (new_value is MISSING)."""
        return self.new_value is MISSING

    @property
    def is_update(self) -> bool:
        """True если узел обновляется (не create и не delete)."""
        return not self.is_create and not self.is_delete

    # --- Сериализация для IPC (Dict at Boundary) ---

    def to_dict(self) -> dict:
        """Сериализация в dict для передачи через IPC.

        MISSING сериализуется как строка '__MISSING__'.
        Все остальные значения передаются как есть (должны быть pickle-совместимы).
        """
        return {
            "path": self.path,
            "old_value": _MISSING_MARKER if self.old_value is MISSING else self.old_value,
            "new_value": _MISSING_MARKER if self.new_value is MISSING else self.new_value,
            "source": self.source,
            "timestamp": self.timestamp,
            "transaction_id": self.transaction_id,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Delta":
        """Десериализация из dict (обратное to_dict).

        Строка '__MISSING__' восстанавливается как MISSING singleton.
        'revision' — fail-open (Ф4.9, ADR-SS-014): дельта от старого
        отправителя, не знающего про revision, восстанавливается с revision=0
        вместо KeyError.
        """
        old_value = MISSING if d["old_value"] == _MISSING_MARKER else d["old_value"]
        new_value = MISSING if d["new_value"] == _MISSING_MARKER else d["new_value"]
        return cls(
            path=d["path"],
            old_value=old_value,
            new_value=new_value,
            source=d["source"],
            timestamp=d["timestamp"],
            transaction_id=d["transaction_id"],
            revision=d.get("revision", 0),
        )


# ---------------------------------------------------------------------------
# StateWriter — Protocol для объекта, умеющего писать в дерево
# ---------------------------------------------------------------------------


@runtime_checkable
class StateWriter(Protocol):
    """Протокол для объекта, который умеет писать в дерево состояний.

    Transaction принимает StateWriter, а не конкретный TreeStore,
    чтобы избежать циклического импорта и жёсткой зависимости.
    """

    def set(self, path: str, value: Any, source: str = "") -> "Delta | None":
        """Установить значение по пути. Возвращает Delta или None если нет изменений."""
        ...

    def merge(self, path: str, data: dict, source: str = "") -> "list[Delta]":
        """Слить dict с поддеревом по пути. Возвращает список Delta."""
        ...

    def delete(self, path: str, source: str = "") -> "Delta | None":
        """Удалить узел по пути. Возвращает Delta или None если узел не существовал."""
        ...


# ---------------------------------------------------------------------------
# Transaction — группировка дельт в batch
# ---------------------------------------------------------------------------


class Transaction:
    """Группировка нескольких Delta в один batch с единым transaction_id.

    Используется как context manager совместно с объектом StateWriter:

        with Transaction(store, label='recipe_load') as tx:
            tx.set('cameras.0.config.fps', 30)
            tx.set('cameras.0.config.type', 'webcam')
        # → все дельты получают единый transaction_id

    При исключении внутри блока — дельты сохраняются (rollback — ответственность
    вызывающего кода, не Transaction).
    """

    def __init__(self, store: StateWriter, label: str = "") -> None:
        """
        Args:
            store: объект, реализующий StateWriter (обычно TreeStore).
            label: человекочитаемая метка для отладки (не используется в логике).
        """
        self._store = store
        self._label = label
        self._transaction_id = str(uuid.uuid4())
        self._deltas: list[Delta] = []

    def __enter__(self) -> "Transaction":
        return self

    def __exit__(self, *exc: Any) -> None:
        # Дельты уже собраны. Rollback — ответственность вызывающего кода.
        pass

    # --- Проксированные методы (делегируют в store, перехватывают Delta) ---

    def set(self, path: str, value: Any) -> "Delta | None":
        """Установить значение через store, перехватить Delta.

        Возвращает Delta с transaction_id этой транзакции, или None если нет изменений.
        """
        delta = self._store.set(path, value, source="transaction")
        if delta is not None:
            # Перевыпустить Delta с transaction_id этой транзакции
            delta = self._rebind(delta)
            self._deltas.append(delta)
        return delta

    def merge(self, path: str, data: dict) -> "list[Delta]":
        """Слить dict через store, перехватить Delta.

        Возвращает список Delta с transaction_id этой транзакции.
        """
        raw_deltas = self._store.merge(path, data, source="transaction")
        bound: list[Delta] = []
        for d in raw_deltas:
            d = self._rebind(d)
            bound.append(d)
        self._deltas.extend(bound)
        return bound

    def delete(self, path: str) -> "Delta | None":
        """Удалить узел через store, перехватить Delta.

        Возвращает Delta с transaction_id этой транзакции, или None если узла не было.
        """
        delta = self._store.delete(path, source="transaction")
        if delta is not None:
            delta = self._rebind(delta)
            self._deltas.append(delta)
        return delta

    @property
    def deltas(self) -> list[Delta]:
        """Все дельты, собранные в этой транзакции."""
        return list(self._deltas)

    @property
    def transaction_id(self) -> str:
        """UUID этой транзакции."""
        return self._transaction_id

    def coalesce(self) -> list[Delta]:
        """Сжатие дельт: для каждого пути оставить одну дельту first.old → last.new.

        Алгоритм:
            1. Для каждого уникального path собираем все дельты по порядку.
            2. Берём old_value первой дельты и new_value последней.
            3. Если old_value == new_value — дельта удаляется (no-op).

        Пример:
            [25→30, 30→28] → [25→28]   # промежуточное состояние удалено
            [25→30, 30→25] → []         # no-op, итог совпадает с началом
        """
        # Сохраняем порядок путей (первое вхождение)
        path_order: list[str] = []
        # path → [delta, delta, ...]
        path_groups: dict[str, list[Delta]] = {}

        for delta in self._deltas:
            if delta.path not in path_groups:
                path_order.append(delta.path)
                path_groups[delta.path] = []
            path_groups[delta.path].append(delta)

        result: list[Delta] = []
        for path in path_order:
            group = path_groups[path]
            first = group[0]
            last = group[-1]

            old_val = first.old_value
            new_val = last.new_value

            # Пропускаем no-op: итоговое состояние совпадает с начальным
            if old_val == new_val:
                continue

            # Создаём сжатую дельту — берём метаданные первой.
            # revision — от last (Ф4.9, ADR-SS-014): сжатая дельта описывает
            # переход к состоянию, зафиксированному последней исходной мутацией.
            coalesced = Delta(
                path=path,
                old_value=old_val,
                new_value=new_val,
                source=first.source,
                timestamp=first.timestamp,
                transaction_id=first.transaction_id,
                revision=last.revision,
            )
            result.append(coalesced)

        return result

    # --- Вспомогательные методы ---

    def _rebind(self, delta: Delta) -> Delta:
        """Переиздать Delta с transaction_id этой транзакции.

        revision сохраняется как есть (Ф4.9, ADR-SS-014) — она уже
        проставлена store.set()/merge()/delete() на момент реальной мутации,
        rebind её не переиздаёт (это не новая мутация, а перепаковка метаданных).
        """
        return Delta(
            path=delta.path,
            old_value=delta.old_value,
            new_value=delta.new_value,
            source=delta.source,
            timestamp=delta.timestamp,
            transaction_id=self._transaction_id,
            revision=delta.revision,
        )
