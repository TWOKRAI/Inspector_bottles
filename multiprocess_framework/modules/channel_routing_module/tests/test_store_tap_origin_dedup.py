# -*- coding: utf-8 -*-
"""Дедуп ПУТЕЙ в store-tap: кто владеет строкой стора (Task 1.3a, тесты автора).

Приёмка тестера (``test_error_plane_one_connector_tap_dedup_acceptance.py``)
держит главное: tap пропускает запись с маркером ``origin=error_manager`` и
принимает обычную. Здесь — АСИММЕТРИЯ, которую вводит правка и которую тот
набор увидеть не мог: tap'ов ДВА, и одинаковый маркер обязан значить для них
разное.

* tap, висящий НА плоскости ошибок (``owns_error_plane=True``), — единственный
  писатель таких строк; пропусти он их, инцидент исчез бы из стора целиком;
* любой другой tap их пропускает: у инцидента строка уже есть.

Ошибка в любую сторону выглядит одинаково правдоподобно снаружи — «в сторе одна
строка», — поэтому проверяются ОБА исхода, а не только удобный.
"""

from __future__ import annotations

from typing import Any, Dict

from ..observability import ObservabilityStore, StoreTapChannel


def _log_record_dict(level: str = "ERROR", message: str = "boom", **extra: Any) -> Dict[str, Any]:
    """Форма ``LogRecord.to_dict()`` — та же, что у соседа ``test_store_tap.py``."""
    return {
        "timestamp": 12.5,
        "level": level,
        "scope": "system",
        "message": message,
        "module": "worker_module",
        "extra": dict(extra),
    }


class TestTheErrorPlaneTapKeepsWhatOthersSkip:
    def test_error_plane_tap_writes_its_own_marked_record(self, tmp_path) -> None:
        """Пропусти он маркер — инцидент не попал бы в стор НИКУДА."""
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        tap = StoreTapChannel(store, name="tap_err", process="camera_0", owns_error_plane=True)
        try:
            tap.write(_log_record_dict(message="инцидент", origin="error_manager"))
            tap.flush(timeout=2.0)  # Task 3.3: дожать очередь перед чтением своих же строк
            rows = store.list_records(process="camera_0")
            assert len(rows) == 1, f"tap плоскости ошибок потерял свою же запись: {rows}"
            assert rows[0]["kind"] == "error", rows[0]
        finally:
            store.close()

    def test_a_plain_tap_skips_the_same_record(self, tmp_path) -> None:
        """Контроль к тесту выше: тот же вход, другой владелец — другой исход."""
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        tap = StoreTapChannel(store, name="tap_log", process="camera_0")
        try:
            result = tap.write(_log_record_dict(message="инцидент", origin="error_manager"))
            # Task 3.3: БЕЗ этого дожатия утверждение об отсутствии стало бы
            # вакуумным — стор пуст просто потому, что очередь ещё не слита.
            tap.flush(timeout=2.0)
            assert store.list_records(process="camera_0") == []
            # Пропуск — успех, а не отказ, и это утверждение о СМЫСЛЕ возврата,
            # а не о счётчике: раздача tap'ам судит только факт исключения и
            # возврат ``write()`` не читает (ревью Task 1.3a; прежний довод
            # «``status="error"`` поднял бы ``tap_write_errors``» опровергнут
            # запуском — ``accepted=1, tap_write_errors=0``).
            assert result["status"] == "success", result
        finally:
            store.close()

    def test_a_foreign_origin_value_is_not_swallowed(self, tmp_path) -> None:
        """Дедуп смотрит на ЗНАЧЕНИЕ маркера, а не на наличие поля ``origin``.

        Иначе любой сайт, положивший в контекст своё ``origin=…``, молча терял
        бы записи — и потеря выглядела бы как «событий не было».
        """
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        tap = StoreTapChannel(store, name="tap_log", process="camera_0")
        try:
            tap.write(_log_record_dict(message="чужой origin", origin="modbus_driver"))
            tap.flush(timeout=2.0)  # Task 3.3
            rows = store.list_records(process="camera_0")
            assert len(rows) == 1, f"запись с чужим origin проглочена дедупом: {rows}"
            assert (rows[0].get("extra") or {}).get("origin") == "modbus_driver", rows[0]
        finally:
            store.close()

    def test_the_marker_is_readable_at_the_top_of_the_stored_row(self, tmp_path) -> None:
        """Маркер поднят на верхний уровень строки, а не оставлен на дне контекста.

        Нормализатор стора кладёт весь контекст записи ОДНИМ значением внутрь
        ``extra``; без подъёма «кто владеет строкой» читалось бы только через
        два уровня вложенности, и запрос по нему написать было бы нечем.
        """
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        tap = StoreTapChannel(store, name="tap_err", process="camera_0", owns_error_plane=True)
        try:
            tap.write(_log_record_dict(message="инцидент", origin="error_manager", context="grab_frame"))
            tap.flush(timeout=2.0)  # Task 3.3
            row = store.list_records(process="camera_0")[0]
            assert (row.get("extra") or {}).get("origin") == "error_manager", row
        finally:
            store.close()
