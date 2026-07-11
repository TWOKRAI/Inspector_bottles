"""test_delta.py — тесты для Delta, MISSING и Transaction.

Запуск:
    cd .../multiprocess_prototype
    python -m pytest state_store/tests/test_delta.py -v
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.state_store_module.core.delta import (
    MISSING,
    Delta,
    Transaction,
    _MissingSentinel,
    StateWriter,
)


# ---------------------------------------------------------------------------
# Вспомогательный mock-store, реализующий StateWriter
# ---------------------------------------------------------------------------


class MockStore:
    """Минимальный mock TreeStore для тестирования Transaction.

    Хранит плоский dict path→value. Возвращает Delta как настоящий store.
    """

    def __init__(self) -> None:
        self._data: dict[str, object] = {}
        # Монотонный счётчик revision (Ф4.9) — как у настоящего TreeStore,
        # чтобы тесты Transaction._rebind/coalesce могли проверять, что
        # revision не переиздаётся, а сохраняется от исходной мутации.
        self._revision = 0

    def _next_revision(self) -> int:
        self._revision += 1
        return self._revision

    def set(self, path: str, value: object, source: str = "") -> Delta | None:
        """Установить значение. Возвращает Delta или None если значение не изменилось."""
        old = self._data.get(path, MISSING)
        if old == value:
            return None
        self._data[path] = value
        return Delta(path=path, old_value=old, new_value=value, source=source, revision=self._next_revision())

    def merge(self, path: str, data: dict, source: str = "") -> list[Delta]:
        """Слить dict в хранилище по префиксу пути."""
        deltas: list[Delta] = []
        for key, val in data.items():
            full_path = f"{path}.{key}" if path else key
            delta = self.set(full_path, val, source=source)
            if delta is not None:
                deltas.append(delta)
        return deltas

    def delete(self, path: str, source: str = "") -> Delta | None:
        """Удалить узел. Возвращает Delta или None если узла не было."""
        if path not in self._data:
            return None
        old = self._data.pop(path)
        return Delta(path=path, old_value=old, new_value=MISSING, source=source, revision=self._next_revision())


# ---------------------------------------------------------------------------
# Тесты MISSING sentinel
# ---------------------------------------------------------------------------


class TestMissingSentinel:
    def test_singleton(self) -> None:
        """MISSING является singleton — два вызова дают один объект."""
        a = _MissingSentinel()
        b = _MissingSentinel()
        assert a is b

    def test_missing_is_missing(self) -> None:
        """Глобальный MISSING is MISSING → True."""
        assert MISSING is MISSING

    def test_missing_is_sentinel_instance(self) -> None:
        """MISSING — экземпляр _MissingSentinel."""
        assert isinstance(MISSING, _MissingSentinel)

    def test_missing_repr(self) -> None:
        """repr(MISSING) == 'MISSING'."""
        assert repr(MISSING) == "MISSING"

    def test_missing_bool_false(self) -> None:
        """bool(MISSING) is False."""
        assert not MISSING

    def test_missing_is_not_none(self) -> None:
        """MISSING — не None."""
        assert MISSING is not None


# ---------------------------------------------------------------------------
# Тесты Delta — базовые свойства
# ---------------------------------------------------------------------------


class TestDeltaProperties:
    def test_is_create(self) -> None:
        """Delta с old_value=MISSING — is_create=True."""
        d = Delta(path="x.y", old_value=MISSING, new_value=42, source="gui")
        assert d.is_create is True
        assert d.is_delete is False
        assert d.is_update is False

    def test_is_delete(self) -> None:
        """Delta с new_value=MISSING — is_delete=True."""
        d = Delta(path="x.y", old_value=42, new_value=MISSING, source="gui")
        assert d.is_delete is True
        assert d.is_create is False
        assert d.is_update is False

    def test_is_update(self) -> None:
        """Delta без MISSING — is_update=True."""
        d = Delta(path="x.y", old_value=25, new_value=30, source="camera_0")
        assert d.is_update is True
        assert d.is_create is False
        assert d.is_delete is False

    def test_frozen_immutable(self) -> None:
        """Delta — frozen dataclass, поля нельзя менять."""
        d = Delta(path="x.y", old_value=1, new_value=2, source="gui")
        with pytest.raises((AttributeError, TypeError)):
            d.path = "other"  # type: ignore[misc]

    def test_default_timestamp_set(self) -> None:
        """Delta автоматически заполняет timestamp через time.monotonic."""
        d = Delta(path="x", old_value=1, new_value=2, source="gui")
        assert isinstance(d.timestamp, float)
        assert d.timestamp > 0

    def test_default_transaction_id_is_uuid(self) -> None:
        """Delta автоматически генерирует transaction_id (UUID строка)."""
        d = Delta(path="x", old_value=1, new_value=2, source="gui")
        assert isinstance(d.transaction_id, str)
        assert len(d.transaction_id) == 36  # стандартный UUID формат

    def test_two_deltas_have_different_transaction_ids(self) -> None:
        """Каждая Delta получает уникальный transaction_id по умолчанию."""
        d1 = Delta(path="x", old_value=1, new_value=2, source="gui")
        d2 = Delta(path="x", old_value=2, new_value=3, source="gui")
        assert d1.transaction_id != d2.transaction_id

    def test_default_revision_is_zero(self) -> None:
        """Delta(...) без явной revision — 0 (Ф4.9, ADR-SS-014, обратная совместимость)."""
        d = Delta(path="x", old_value=1, new_value=2, source="gui")
        assert d.revision == 0

    def test_explicit_revision_preserved(self) -> None:
        """Явно переданная revision сохраняется как есть."""
        d = Delta(path="x", old_value=1, new_value=2, source="gui", revision=7)
        assert d.revision == 7


# ---------------------------------------------------------------------------
# Тесты сериализации/десериализации Delta
# ---------------------------------------------------------------------------


class TestDeltaSerialization:
    def test_roundtrip_normal_values(self) -> None:
        """Delta с обычными значениями: to_dict → from_dict → равный объект."""
        original = Delta(
            path="cameras.0.fps",
            old_value=25,
            new_value=30,
            source="gui",
            timestamp=1234.5,
            transaction_id="test-tx-id",
        )
        d = Delta.from_dict(original.to_dict())
        assert d.path == original.path
        assert d.old_value == original.old_value
        assert d.new_value == original.new_value
        assert d.source == original.source
        assert d.timestamp == original.timestamp
        assert d.transaction_id == original.transaction_id

    def test_roundtrip_missing_old_value(self) -> None:
        """Delta(old_value=MISSING): MISSING сериализуется и восстанавливается."""
        original = Delta(
            path="x",
            old_value=MISSING,
            new_value=42,
            source="gui",
            timestamp=100.0,
            transaction_id="tx-1",
        )
        d = Delta.from_dict(original.to_dict())
        assert d.old_value is MISSING
        assert d.new_value == 42

    def test_roundtrip_missing_new_value(self) -> None:
        """Delta(new_value=MISSING): MISSING сериализуется и восстанавливается."""
        original = Delta(
            path="x",
            old_value=42,
            new_value=MISSING,
            source="gui",
            timestamp=100.0,
            transaction_id="tx-2",
        )
        d = Delta.from_dict(original.to_dict())
        assert d.new_value is MISSING
        assert d.old_value == 42

    def test_to_dict_missing_marker_string(self) -> None:
        """to_dict заменяет MISSING строкой '__MISSING__'."""
        d = Delta(path="x", old_value=MISSING, new_value=5, source="gui", timestamp=1.0, transaction_id="tx")
        data = d.to_dict()
        assert data["old_value"] == "__MISSING__"
        assert data["new_value"] == 5

    def test_none_value_not_confused_with_missing(self) -> None:
        """None — валидное значение, не путается с MISSING при roundtrip."""
        original = Delta(
            path="optional_field",
            old_value=None,
            new_value=42,
            source="gui",
            timestamp=1.0,
            transaction_id="tx",
        )
        d = Delta.from_dict(original.to_dict())
        assert d.old_value is None  # None сохранён как None, не MISSING
        assert d.old_value is not MISSING

    def test_roundtrip_string_values(self) -> None:
        """Delta со строковыми значениями корректно сериализуется."""
        original = Delta(
            path="cameras.0.type",
            old_value="usb",
            new_value="gige",
            source="recipe_engine",
            timestamp=50.0,
            transaction_id="tx-3",
        )
        d = Delta.from_dict(original.to_dict())
        assert d.old_value == "usb"
        assert d.new_value == "gige"

    def test_roundtrip_revision(self) -> None:
        """Ф4.9, ADR-SS-014: revision участвует в to_dict/from_dict roundtrip."""
        original = Delta(
            path="cameras.0.fps",
            old_value=25,
            new_value=30,
            source="gui",
            timestamp=1234.5,
            transaction_id="test-tx-id",
            revision=42,
        )
        d = Delta.from_dict(original.to_dict())
        assert d.revision == 42

    def test_to_dict_includes_revision_key(self) -> None:
        """to_dict() всегда несёт ключ 'revision' (аддитивное поле IPC-конверта)."""
        d = Delta(path="x", old_value=1, new_value=2, source="gui", revision=3)
        assert d.to_dict()["revision"] == 3

    def test_from_dict_missing_revision_defaults_to_zero(self) -> None:
        """Fail-open (Ф4.9a): dict от старого отправителя без 'revision' → revision=0, не KeyError."""
        legacy_dict = {
            "path": "x",
            "old_value": 1,
            "new_value": 2,
            "source": "gui",
            "timestamp": 1.0,
            "transaction_id": "tx-legacy",
            # намеренно без "revision"
        }
        d = Delta.from_dict(legacy_dict)
        assert d.revision == 0


# ---------------------------------------------------------------------------
# Тесты Transaction — сбор дельт
# ---------------------------------------------------------------------------


class TestTransactionDeltas:
    def test_transaction_collects_set_deltas(self) -> None:
        """Transaction.set() собирает дельты в self.deltas."""
        store = MockStore()
        with Transaction(store, label="test") as tx:
            tx.set("cameras.0.fps", 30)
            tx.set("cameras.0.type", "usb")

        assert len(tx.deltas) == 2
        paths = {d.path for d in tx.deltas}
        assert "cameras.0.fps" in paths
        assert "cameras.0.type" in paths

    def test_transaction_same_transaction_id(self) -> None:
        """Все дельты транзакции получают одинаковый transaction_id."""
        store = MockStore()
        with Transaction(store) as tx:
            tx.set("a", 1)
            tx.set("b", 2)

        tx_id = tx.transaction_id
        for delta in tx.deltas:
            assert delta.transaction_id == tx_id

    def test_transaction_delete_delta(self) -> None:
        """Transaction.delete() перехватывает Delta с new_value=MISSING."""
        store = MockStore()
        store.set("x.y", 100, source="init")

        with Transaction(store) as tx:
            tx.delete("x.y")

        assert len(tx.deltas) == 1
        assert tx.deltas[0].is_delete
        assert tx.deltas[0].new_value is MISSING

    def test_transaction_merge_deltas(self) -> None:
        """Transaction.merge() собирает несколько дельт из словаря."""
        store = MockStore()
        with Transaction(store) as tx:
            tx.merge("cameras.0.config", {"fps": 30, "width": 1920, "height": 1080})

        assert len(tx.deltas) == 3

    def test_transaction_context_manager_returns_self(self) -> None:
        """__enter__ возвращает объект Transaction."""
        store = MockStore()
        tx = Transaction(store)
        result = tx.__enter__()
        assert result is tx
        tx.__exit__()

    def test_rebind_preserves_revision(self) -> None:
        """Ф4.9, ADR-SS-014: _rebind() не переиздаёт revision — сохраняет от store."""
        store = MockStore()
        with Transaction(store) as tx:
            d1 = tx.set("a", 1)
            d2 = tx.set("b", 2)

        # MockStore инкрементирует revision на каждый set() — 1, затем 2.
        assert d1.revision == 1
        assert d2.revision == 2


# ---------------------------------------------------------------------------
# Тесты Transaction.coalesce()
# ---------------------------------------------------------------------------


class TestTransactionCoalesce:
    def _make_deltas(self, store: MockStore, changes: list[tuple]) -> Transaction:
        """Вспомогательный метод: применить список (path, value) через транзакцию."""
        tx = Transaction(store)
        for path, value in changes:
            tx.set(path, value)
        return tx

    def test_coalesce_two_updates_same_path(self) -> None:
        """[25→30, 30→28] → [25→28]: промежуточное состояние удаляется."""
        store = MockStore()
        store.set("fps", 25, source="init")

        tx = Transaction(store)
        tx.set("fps", 30)
        tx.set("fps", 28)

        coalesced = tx.coalesce()
        assert len(coalesced) == 1
        assert coalesced[0].old_value == 25
        assert coalesced[0].new_value == 28

    def test_coalesce_noop_returns_empty(self) -> None:
        """[25→30, 30→25] → []: no-op (итог = начало) удаляется."""
        store = MockStore()
        store.set("fps", 25, source="init")

        tx = Transaction(store)
        tx.set("fps", 30)
        tx.set("fps", 25)

        coalesced = tx.coalesce()
        assert coalesced == []

    def test_coalesce_revision_is_last(self) -> None:
        """Ф4.9, ADR-SS-014: сжатая дельта несёт revision ПОСЛЕДНЕЙ исходной мутации.

        [25→30 (rev=2), 30→28 (rev=3)] → [25→28 (rev=3)]: сжатая дельта
        описывает переход дерева к состоянию revision=3, не revision=2.
        """
        store = MockStore()
        store.set("fps", 25, source="init")  # rev=1 (не входит в транзакцию)

        tx = Transaction(store)
        tx.set("fps", 30)  # rev=2
        tx.set("fps", 28)  # rev=3

        coalesced = tx.coalesce()
        assert len(coalesced) == 1
        assert coalesced[0].revision == 3

    def test_coalesce_single_delta_preserved(self) -> None:
        """Одиночная дельта без повторений не изменяется."""
        store = MockStore()
        tx = Transaction(store)
        tx.set("x.y", 42)

        coalesced = tx.coalesce()
        assert len(coalesced) == 1
        assert coalesced[0].new_value == 42

    def test_coalesce_different_paths_independent(self) -> None:
        """Разные пути сжимаются независимо."""
        store = MockStore()
        store.set("a", 1, source="init")
        store.set("b", 10, source="init")

        tx = Transaction(store)
        tx.set("a", 2)
        tx.set("a", 3)
        tx.set("b", 20)
        tx.set("b", 10)  # no-op для b

        coalesced = tx.coalesce()
        # a: 1→3 (сжато из 1→2, 2→3)
        # b: 10→10 = no-op, удалено
        assert len(coalesced) == 1
        assert coalesced[0].path == "a"
        assert coalesced[0].old_value == 1
        assert coalesced[0].new_value == 3

    def test_coalesce_preserves_path_order(self) -> None:
        """coalesce() сохраняет порядок путей по первому вхождению."""
        store = MockStore()
        tx = Transaction(store)
        tx.set("z", 1)
        tx.set("a", 2)
        tx.set("m", 3)

        coalesced = tx.coalesce()
        paths = [d.path for d in coalesced]
        assert paths == ["z", "a", "m"]

    def test_coalesce_does_not_mutate_original_deltas(self) -> None:
        """coalesce() не изменяет исходный список дельт."""
        store = MockStore()
        store.set("fps", 25, source="init")

        tx = Transaction(store)
        tx.set("fps", 30)
        tx.set("fps", 28)

        original_count = len(tx.deltas)
        tx.coalesce()
        # После coalesce() в tx.deltas должно остаться столько же дельт
        assert len(tx.deltas) == original_count


# ---------------------------------------------------------------------------
# Тест StateWriter Protocol
# ---------------------------------------------------------------------------


class TestStateWriterProtocol:
    def test_mock_store_implements_protocol(self) -> None:
        """MockStore удовлетворяет StateWriter Protocol."""
        store = MockStore()
        assert isinstance(store, StateWriter)
