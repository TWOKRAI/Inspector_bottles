# -*- coding: utf-8 -*-
"""Task 3.5 — независимый приёмочный тест (RED, ДО реализации) на ``history_query``.

Контракт взят ДОСЛОВНО из acceptance criteria плана (К1–К8), а не из чтения
будущей реализации — на момент написания ``BackendDriver.history_query`` и
MCP-инструмент ``history_query`` в ``backend_ctl/mcp_tools.py::TOOLS`` НЕ
СУЩЕСТВУЮТ вовсе. Красный прогон — ожидаемый результат этого файла.

Две опоры, как предписано заданием:

  1. Фейковый driver (образец — ``test_mcp_full_and_rules_introspect_observability.py``):
     фиксирует вызовы ``send_command`` и отвечает заранее заданным словарём —
     ``introspect.observability`` с секцией ``history`` (``enabled``/``db_path``),
     ровно в той форме, что реально строит
     ``BuiltinCommands._history_report()`` (``multiprocess_framework/modules/
     process_module/commands/builtin_commands.py``).
  2. Настоящий ``ObservabilityStore`` (существующий модуль, НЕ предмет этой
     задачи) — им создаются временные sqlite-файлы с реальными записями, чтобы
     было что читать ``history_query``.

Тесты вызывают ЛИБО метод драйвера (``BackendDriver.history_query`` с
подменённым ``send_command``), ЛИБО хендлер из MCP-реестра
(``build_registry()["history_query"].handler``) — обе формы обязаны
существовать по К1.

**Допущение, которое я НЕ смог подтвердить кодом (контракт его не называет):**
имя ключа-конверта со списком строк ответа. Ни один явный пример в acceptance
criteria не называет его буквально (названы только ПОЛЯ строки — id/kind/…).
Выбрано ``rows`` (см. :data:`ROWS_KEY`) по аналогии со словом, уже
использованным в этом же сторе (``ObservabilityStore.purge`` → ``by_rows``/
``remaining``). Если реализация выберет другое имя — RED здесь останется
RED-ом по неверной причине (KeyError на ``rows`` вместо AttributeError на
методе), и это придётся поправить на стадии GREEN. Отмечено также в отчёте
тестера.

Комментарии и докстроки — по-русски (правило проекта).
"""

from __future__ import annotations

import copy
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.mcp_tools import build_registry
from backend_ctl.dispatch import _cap_heavy

from multiprocess_framework.modules.channel_routing_module.observability import (
    ObservabilityStore,
    resolve_default_db_path,
)

#: ДОПУЩЕНИЕ (см. докстроку модуля): имя ключа-конверта со списком строк ответа.
#: Контракт К1–К8 его не называет буквально — только форму ОДНОЙ строки (К4).
ROWS_KEY = "rows"

#: Параметры схемы, названные ДОСЛОВНО в К1.
NAMED_SCHEMA_PARAMS = (
    "kind",
    "metric",
    "process",
    "module",
    "severity",
    "min_severity",
    "since",
    "until",
    "text",
    "limit",
    "full",
    "pm_name",
    "timeout",
)


# ---------------------------------------------------------------------------
# Фейковый driver: фиксирует send_command, отвечает по сценарию.
# ---------------------------------------------------------------------------


class _FakeSendCommand:
    """Отвечает ``introspect.observability`` заранее заданным словарём.

    Любая ДРУГАЯ команда — громкий ``AssertionError`` (а не молчаливый None):
    у ``history_query`` нет причины звать что-то, кроме этой одной команды на
    ``pm_name`` (К2), и незнакомый вызов — сам по себе находка.
    """

    def __init__(self, response: Dict[str, Any]) -> None:
        self.calls: List[tuple] = []
        self._response = response

    def __call__(self, target: str, command: str, args: Optional[dict] = None, *, timeout: Optional[float] = None):
        self.calls.append((target, command, args, timeout))
        if command != "introspect.observability":
            raise AssertionError(
                f"history_query отправил незнакомую команду {command!r} процессу {target!r} "
                f"— ожидалась ровно 'introspect.observability' (К2)"
            )
        return copy.deepcopy(self._response)


def _driver_with_response(response: Dict[str, Any]) -> BackendDriver:
    """``BackendDriver`` без сокета: ``send_command`` подменён фейком (К2)."""
    drv = BackendDriver()
    fake = _FakeSendCommand(response)
    drv.send_command = fake  # type: ignore[assignment]
    drv._fake_send_command = fake  # для доступа к .calls из теста
    return drv


def _ok_response(db_path: str, *, process: str = "ProcessManager") -> Dict[str, Any]:
    """Ответ ``introspect.observability`` — история включена, путь известен.

    Форма — ровно та, что строит ``BuiltinCommands._history_report()``:
    ``{"history": {"enabled": True, "db_path": ...}}`` внутри общего конверта.
    """
    return {
        "success": True,
        "process": process,
        "history": {"enabled": True, "db_path": db_path},
    }


def _response_missing_db_path(*, process: str = "ProcessManager") -> Dict[str, Any]:
    """История включена, но ``db_path`` в ответе НЕТ (К2, первая ветка отказа)."""
    return {"success": True, "process": process, "history": {"enabled": True}}


def _response_history_disabled(*, process: str = "ProcessManager") -> Dict[str, Any]:
    """История выключена целиком (К2, вторая ветка отказа) — форма из
    ``_history_report()``, когда у процесса нет стора вовсе."""
    return {
        "success": True,
        "process": process,
        "history": {
            "enabled": False,
            "reason": "у процесса нет стора истории — он заводится вместе с hub'ом",
        },
    }


# ---------------------------------------------------------------------------
# Реальный ObservabilityStore — сеет строки, которые history_query обязан читать.
# ---------------------------------------------------------------------------


def _seed_small_store(tmp_path) -> tuple:
    """Пять разнородных записей в реальном sqlite-файле. Возвращает (db_path, now).

    ``now`` — момент посева (используется тестами для since/until без гонки:
    600-секундное окно даёт огромный запас над временем выполнения теста).
    """
    db_path = str(tmp_path / "observability.db")
    store = ObservabilityStore(db_path=db_path)
    now = time.time()
    # ВАЖНО: порядок ВСТАВКИ здесь совпадает с хронологическим порядком ts
    # (как у настоящего писателя — записи приходят по мере событий). Реальный
    # ``ObservabilityStore.list_records``/``search`` сортирует по ``id DESC``
    # (порядок ВСТАВКИ), а не пересчитывает по ``ts`` — проверено отдельным
    # sanity-прогоном против настоящего стора ДО фиксации этого файла. Если бы
    # порядок вставки был перемешан относительно ts (как в первой редакции
    # этой фикстуры), тест «свежие первыми» подтверждал бы id-порядок, выдавая
    # его за ts-порядок, — и был бы неверным в реальной, не тестовой, БД, где
    # оба порядка обычно совпадают. Совпадение здесь снимает двусмысленность
    # критерия К4 («свежие первыми» — не уточняет, по какому полю).
    records = [
        {
            "kind": "log",
            "module": "capture",
            "process": "camera_0",
            "ts": now - 3600,
            "severity": "info",
            "message": "camera boot sequence started",
            "context": {},
        },
        {
            "kind": "log",
            "module": "segmenter",
            "process": "seg",
            "ts": now - 3000,
            "severity": "critical",
            "message": "segmentation halted unexpectedly",
            "context": {},
        },
        {
            "kind": "log",
            "module": "capture",
            "process": "camera_0",
            "ts": now - 100,
            "severity": "warning",
            "message": "frame queue backpressure detected",
            "context": {},
        },
        {
            "kind": "error",
            "module": "widgets",
            "process": "gui",
            "ts": now - 50,
            "severity": "error",
            "message": "widget crash detected",
            "context": {"code": 7},
        },
        {
            "kind": "stats",
            "module": "segmenter",
            "process": "seg",
            "ts": now - 20,
            "metric": "fps",
            "value": 12.5,
            "metric_type": "gauge",
            "tags": {},
        },
    ]
    inserted = store.append_records(records)
    assert inserted == len(records), "фикстура сама не записалась — тесты будут врать"
    store.close()
    return db_path, now


def _seed_bulk_store(tmp_path, n: int = 150) -> str:
    """Сто пятьдесят одинаковых по форме записей — для проверки дефолтного лимита (К8)."""
    db_path = str(tmp_path / "bulk.db")
    store = ObservabilityStore(db_path=db_path)
    now = time.time()
    records = [
        {
            "kind": "log",
            "module": "bulk",
            "process": "bulk_proc",
            "ts": now - i,
            "severity": "info",
            "message": f"bulk record {i}",
            "context": {},
        }
        for i in range(n)
    ]
    inserted = store.append_records(records)
    assert inserted == n
    store.close()
    return db_path


def _rows(result: Dict[str, Any]) -> Optional[list]:
    return result.get(ROWS_KEY)


def _messages(result: Dict[str, Any]) -> list:
    rows = _rows(result)
    assert rows is not None, f"в ответе нет ключа {ROWS_KEY!r}: доступные ключи {sorted(result.keys())}"
    return [r["message"] for r in rows]


# ===========================================================================
# К1 — инструмент существует в ОБЕИХ формах, схема закрыта и полна.
# ===========================================================================


class TestK1Existence:
    def test_driver_method_exists_and_returns_dict(self, tmp_path) -> None:
        """Смоук: метод есть и отвечает dict'ом (форма, не свойства ответа)."""
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query()
        assert isinstance(result, dict), f"history_query обязан вернуть dict, получено {type(result)}"

    def test_tool_is_registered_in_mcp_registry(self) -> None:
        registry = build_registry()
        assert "history_query" in registry, (
            "history_query отсутствует в реестре MCP-инструментов backend_ctl/mcp_tools.py::TOOLS"
        )

    def test_mcp_schema_is_closed(self) -> None:
        spec = build_registry()["history_query"]
        assert spec.input_schema.get("additionalProperties") is False, (
            "схема history_query обязана быть закрытой (additionalProperties: false)"
        )

    def test_mcp_schema_declares_every_named_param(self) -> None:
        spec = build_registry()["history_query"]
        props = spec.input_schema.get("properties", {})
        missing = [p for p in NAMED_SCHEMA_PARAMS if p not in props]
        assert missing == [], f"схема history_query не объявляет параметры К1: {missing}"

    def test_full_param_is_boolean_in_schema(self) -> None:
        spec = build_registry()["history_query"]
        assert spec.input_schema["properties"]["full"]["type"] == "boolean"


# ===========================================================================
# К2 — путь к БД из readback (introspect.observability), без запасного пути.
# ===========================================================================


class TestK2ReadbackNotGuess:
    def test_default_pm_name_targets_process_manager(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path, process="ProcessManager"))
        drv.history_query()
        calls = drv._fake_send_command.calls
        assert calls, "history_query ни разу не позвал send_command"
        target, command, _args, _timeout = calls[0]
        assert target == "ProcessManager", f"дефолтный pm_name обязан быть 'ProcessManager', адресовано {target!r}"
        assert command == "introspect.observability"

    def test_custom_pm_name_is_used_as_the_readback_target(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path, process="OtherPM"))
        drv.history_query(pm_name="OtherPM")
        target, _command, _args, _timeout = drv._fake_send_command.calls[0]
        assert target == "OtherPM", f"pm_name='OtherPM' проигнорирован, ушло на {target!r}"

    def test_missing_history_db_path_is_a_named_failure(self) -> None:
        drv = _driver_with_response(_response_missing_db_path(process="ProcessManager"))
        result = drv.history_query()
        assert result.get("success") is False, f"отсутствие history.db_path обязано провалить вызов: {result}"
        error_text = str(result.get("error", ""))
        assert "ProcessManager" in error_text, f"ошибка не называет опрошенный процесс: {error_text!r}"
        assert "db_path" in error_text or "history" in error_text.lower(), (
            f"ошибка не называет ЧЕГО не хватает (db_path/history): {error_text!r}"
        )

    def test_history_disabled_is_a_named_failure(self) -> None:
        drv = _driver_with_response(_response_history_disabled(process="ProcessManager"))
        result = drv.history_query()
        assert result.get("success") is False, f"history.enabled=False обязано провалить вызов: {result}"
        error_text = str(result.get("error", ""))
        assert "ProcessManager" in error_text, f"ошибка не называет опрошенный процесс: {error_text!r}"
        assert "enabled" in error_text.lower() or "стор" in error_text.lower(), (
            f"ошибка не называет ПРИЧИНУ (history.enabled=False / нет стора): {error_text!r}"
        )

    def test_missing_db_path_never_opens_sqlite(self, monkeypatch) -> None:
        """К2: «sqlite при этом не открывается вовсе» — фейк, падающий при любом connect()."""

        def _boom(*_a, **_kw):
            raise AssertionError("sqlite3.connect вызван, хотя history.db_path отсутствует в ответе")

        monkeypatch.setattr(sqlite3, "connect", _boom)
        drv = _driver_with_response(_response_missing_db_path())
        result = drv.history_query()
        assert result.get("success") is False

    def test_disabled_history_never_opens_sqlite(self, monkeypatch) -> None:
        def _boom(*_a, **_kw):
            raise AssertionError("sqlite3.connect вызван, хотя history.enabled=False")

        monkeypatch.setattr(sqlite3, "connect", _boom)
        drv = _driver_with_response(_response_history_disabled())
        result = drv.history_query()
        assert result.get("success") is False

    def test_missing_db_path_does_not_fall_back_to_resolve_default_db_path(self, tmp_path, monkeypatch) -> None:
        """«Запасного пути (вроде resolve_default_db_path()) НЕТ» — проверено ПОВЕДЕНИЕМ,
        а не чтением кода: реальный дефолтный файл существует, непуст и узнаваем по
        сигнальной записи; если бы реализация тихо подставляла его, ответ пришёл бы
        успешным с этой самой строкой внутри — вместо этого он ОБЯЗАН провалиться.
        """
        fallback_dir = tmp_path / "fallback_logs"
        fallback_dir.mkdir()
        monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(fallback_dir))
        expected_default_path = str(fallback_dir / "observability.db")
        assert resolve_default_db_path() == expected_default_path, "sanity: env не резолвится туда, куда я думаю"

        fallback_store = ObservabilityStore(db_path=expected_default_path)
        fallback_store.append_records(
            [
                {
                    "kind": "log",
                    "module": "ghost",
                    "process": "ghost",
                    "ts": time.time(),
                    "severity": "critical",
                    "message": "СИГНАЛ: сюда лезть было нельзя — запасной путь сработал",
                    "context": {},
                }
            ]
        )
        fallback_store.close()

        drv = _driver_with_response(_response_missing_db_path())
        result = drv.history_query()
        assert result.get("success") is False, (
            f"при отсутствующем history.db_path и РАБОТАЮЩЕМ resolve_default_db_path() "
            f"вызов обязан провалиться, а не тихо подставить дефолтный путь: {result}"
        )


# ===========================================================================
# К3 — соединение только на чтение (file:...?mode=ro).
# ===========================================================================


class TestK3ReadOnlyConnection:
    def test_connection_uses_a_readonly_uri(self, tmp_path, monkeypatch) -> None:
        """Шпион на sqlite3.connect (реальный вызов, не подмена поведения) —
        проверяет ФАКТИЧЕСКИЕ параметры соединения, а не имя метода."""
        db_path, _ = _seed_small_store(tmp_path)
        captured: Dict[str, Any] = {}
        real_connect = sqlite3.connect

        def _spy(database, *args, **kwargs):
            captured["database"] = database
            captured["kwargs"] = kwargs
            return real_connect(database, *args, **kwargs)

        monkeypatch.setattr(sqlite3, "connect", _spy)
        drv = _driver_with_response(_ok_response(db_path))
        drv.history_query()

        assert captured, "history_query ни разу не вызвал sqlite3.connect — БД не читалась вовсе"
        database = captured["database"]
        kwargs = captured["kwargs"]
        assert isinstance(database, str) and database.startswith("file:"), (
            f"соединение открыто не URI-формой file:...: {database!r}"
        )
        assert "mode=ro" in database, f"URI не содержит mode=ro: {database!r}"
        assert kwargs.get("uri") is True, f"connect() вызван без uri=True: {kwargs}"

    def test_readonly_uri_actually_refuses_writes(self, tmp_path, monkeypatch) -> None:
        """Эффект, а не имя: РЕАЛЬНАЯ попытка INSERT через параметры, которые
        history_query фактически использовал, обязана отказать (К3а)."""
        db_path, _ = _seed_small_store(tmp_path)
        captured: Dict[str, Any] = {}
        real_connect = sqlite3.connect

        def _spy(database, *args, **kwargs):
            captured["database"] = database
            captured["kwargs"] = kwargs
            return real_connect(database, *args, **kwargs)

        monkeypatch.setattr(sqlite3, "connect", _spy)
        drv = _driver_with_response(_ok_response(db_path))
        drv.history_query()
        assert captured, "history_query ни разу не вызвал sqlite3.connect"

        # Реальное (не мокнутое) соединение с ТЕМИ ЖЕ параметрами.
        conn2 = real_connect(captured["database"], **captured["kwargs"])
        try:
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                conn2.execute("INSERT INTO records (kind, module, ts) VALUES ('log', 'intruder', 0)")
        finally:
            conn2.close()

    def test_nonexistent_db_path_is_a_named_error_and_creates_no_file(self, tmp_path) -> None:
        ghost = str(tmp_path / "does_not_exist_yet.sqlite3")
        assert not os.path.exists(ghost), "sanity: путь не должен существовать ДО вызова"
        drv = _driver_with_response(_ok_response(ghost))
        result = drv.history_query()
        assert result.get("success") is False, f"несуществующий путь обязан провалить вызов: {result}"
        error_text = str(result.get("error", ""))
        assert "does_not_exist_yet" in error_text, f"ошибка не называет путь: {error_text!r}"
        assert not os.path.exists(ghost), (
            "history_query СОЗДАЛ файл на несуществующем пути — соединение было НЕ read-only (К3б)"
        )


# ===========================================================================
# К4 — фильтры сужают, строка распакована, порядок — свежие первыми.
# ===========================================================================


class TestK4FiltersAndRowShape:
    def test_rows_are_ordered_newest_first(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(limit=10)
        assert _messages(result) == [
            "fps",
            "widget crash detected",
            "frame queue backpressure detected",
            "segmentation halted unexpectedly",
            "camera boot sequence started",
        ], "порядок строк не «свежие первыми» (ts убывает)"

    def test_row_carries_all_named_fields_with_literal_values(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(process="gui")
        rows = _rows(result)
        assert rows is not None and len(rows) == 1
        row = rows[0]
        assert row["kind"] == "error"
        assert row["process"] == "gui"
        assert row["module"] == "widgets"
        assert row["severity"] == "error"
        assert row["severity_number"] == 17
        assert row["message"] == "widget crash detected"
        assert set(row.keys()) >= {
            "id",
            "kind",
            "process",
            "module",
            "ts",
            "severity",
            "severity_number",
            "message",
            "extra",
        }

    def test_row_extra_is_an_unpacked_dict_not_a_json_string(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(process="gui")
        row = _rows(result)[0]
        assert isinstance(row["extra"], dict), (
            f"extra обязан быть dict, получено {type(row['extra'])}: {row['extra']!r}"
        )
        assert row["extra"] == {"context": {"code": 7}}

    def test_kind_filter_returns_only_matching_kind(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(kind="error")
        assert _messages(result) == ["widget crash detected"]

    def test_kind_filter_absent_includes_other_kinds(self, tmp_path) -> None:
        """Парная проверка достижимости к предыдущему тесту: без фильтра
        видны и log, и stats — иначе «kind=error сузил» доказывал бы вхолостую."""
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(limit=10)
        messages = _messages(result)
        assert "camera boot sequence started" in messages  # kind=log
        assert "fps" in messages  # kind=stats

    def test_process_filter_returns_only_matching_process(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(process="gui")
        assert _messages(result) == ["widget crash detected"]

    def test_process_filter_absent_includes_other_processes(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(limit=10)
        messages = _messages(result)
        assert "camera boot sequence started" in messages  # process=camera_0
        assert "segmentation halted unexpectedly" in messages  # process=seg

    def test_module_filter_returns_only_matching_module(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(module="segmenter", limit=10)
        assert _messages(result) == ["fps", "segmentation halted unexpectedly"]

    def test_module_filter_absent_includes_other_modules(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(limit=10)
        assert "frame queue backpressure detected" in _messages(result)  # module=capture

    def test_severity_membership_filter_returns_only_named_severities(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(severity=["error", "critical"], limit=10)
        assert _messages(result) == ["widget crash detected", "segmentation halted unexpectedly"]

    def test_severity_membership_filter_absent_includes_other_severities(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(limit=10)
        messages = _messages(result)
        assert "camera boot sequence started" in messages  # info
        assert "frame queue backpressure detected" in messages  # warning

    def test_min_severity_threshold_returns_only_at_or_above(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(min_severity=17, limit=10)  # ERROR и выше
        assert _messages(result) == ["widget crash detected", "segmentation halted unexpectedly"]

    def test_since_absolute_positive_narrows_to_recent(self, tmp_path) -> None:
        db_path, now = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(since=now - 200, limit=10)
        assert _messages(result) == ["fps", "widget crash detected", "frame queue backpressure detected"]

    def test_until_absolute_positive_narrows_to_old(self, tmp_path) -> None:
        db_path, now = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(until=now - 1000, limit=10)
        assert _messages(result) == ["segmentation halted unexpectedly", "camera boot sequence started"]

    def test_limit_is_honored(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(limit=2)
        assert len(_rows(result)) == 2

    def test_success_envelope_carries_db_path_literally_matching_readback_and_count(self, tmp_path) -> None:
        """Н-1 (добор ревью 2026-09-04): конверт К4 дословно — «db_path в ответе
        обязателен, иначе К2 нечем сверить снаружи» — не был застрахован НИ ОДНИМ
        тестом; мутационный прогон ревьюера снял оба поля из успешного ответа и
        получил 48/48 зелёных. Проверяется дословное равенство с ПУТЁМ ИЗ READBACK
        (не просто «есть строка»), и count как ИМЕННО len(rows), а не число сбоку."""
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(limit=10)
        assert result.get("success") is True
        assert result.get("db_path") == db_path, (
            f"db_path ответа разошёлся с путём из readback: {result.get('db_path')!r} != {db_path!r}"
        )
        rows = _rows(result)
        assert rows is not None
        assert result.get("count") == len(rows), (
            f"count={result.get('count')!r} не равен len(rows)={len(rows)} — числа разошлись"
        )


# ===========================================================================
# К5 — отрицательные since/until — относительные секунды от «сейчас»; 0 — абсолют.
# ===========================================================================


class TestK5RelativeSinceUntil:
    def test_negative_since_is_a_window_of_the_last_n_seconds(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(since=-600, limit=10)  # окно последних 600 с
        assert _messages(result) == ["fps", "widget crash detected", "frame queue backpressure detected"]

    def test_negative_until_is_a_window_ending_n_seconds_ago(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(until=-1800, limit=10)  # всё, что старше 1800 с
        assert _messages(result) == ["segmentation halted unexpectedly", "camera boot sequence started"]

    def test_until_zero_is_absolute_epoch_zero_not_now(self, tmp_path) -> None:
        """Критерий дословно: «0 — абсолютный ноль, а не «сейчас»».
        Реальные ts записей — огромные положительные числа (unix-время), поэтому
        ``until=0`` (ts <= 0) обязан дать ПУСТУЮ выдачу, если 0 читается буквально."""
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(until=0, limit=10)
        assert _rows(result) == [], (
            f"until=0 обязан значить «до эпохи 0», а не «сейчас» — иначе строки бы приехали: {_messages(result)}"
        )


# ===========================================================================
# К6 — text ищет через FTS (не подстрокой); отказ поиска назван и отличим от «не нашлось».
# ===========================================================================


class TestK6TextSearchIsFTS:
    def test_text_search_finds_the_exact_word(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(text="crash")
        assert _messages(result) == ["widget crash detected"]

    def test_text_search_does_not_match_as_a_plain_substring(self, tmp_path) -> None:
        """«ash» — буквальная подстрока слова «crash», но НЕ отдельное слово.
        LIKE-скан её бы нашёл; FTS5 (токен целиком) — нет. Разница и есть
        доказательство того, что поиск не подстрочный (К6)."""
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(text="ash")
        assert _rows(result) == [], (
            f"text='ash' (подстрока слова 'crash') нашёл строки — поиск похож на LIKE, не на FTS: {_messages(result)}"
        )

    def test_text_search_no_words_is_a_named_refusal(self, tmp_path) -> None:
        """Запрос без единой буквы/цифры — ``ObservabilitySearchError`` в сторе
        (``искать нечего``). history_query обязан поймать это и назвать отказ,
        а не уронить вызов исключением наружу."""
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(text="!!!")
        assert result.get("success") is False, f"пустой по словам запрос обязан быть НАЗВАННЫМ отказом: {result}"
        error_text = str(result.get("error", ""))
        assert "!!!" in error_text, f"ошибка не называет сам запрос: {error_text!r}"

    def test_text_search_no_match_is_success_with_empty_rows(self, tmp_path) -> None:
        """«Ничего не нашлось» и «искать было нечем» — РАЗНЫЕ факты (К6):
        настоящее слово без совпадений обязано отличаться от предыдущего теста
        отсутствием отказа."""
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(text="zzznomatchxyz")
        assert result.get("success") is not False, (
            f"настоящее слово без совпадений — это НЕ отказ поиска, а пустая выдача: {result}"
        )
        assert _rows(result) == []

    def test_text_search_combined_with_module_filter_does_not_raise_ambiguous_column(self, tmp_path) -> None:
        """Н-2 (добор ревью 2026-09-04): ветка ``text=`` JOIN'ит теневую FTS5-таблицу
        (несёт СВОИ колонки ``message``/``module``/``process``) с ``records r`` —
        WHERE-условие фильтра ``module`` обязано быть квалифицировано (``r.module``),
        иначе sqlite отвечает ``ambiguous column name: module`` вместо результата.
        Ни один из прежних 48 тестов не сочетал ``text=`` с фильтром — заплата
        (``prefix=""`` вместо ``"r."``), форсированная ревьюером, проходила молча."""
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(text="crash", module="widgets")
        assert result.get("success") is True, f"text+module дал отказ вместо результата: {result}"
        assert _messages(result) == ["widget crash detected"]

    def test_text_search_combined_with_process_filter_does_not_raise_ambiguous_column(self, tmp_path) -> None:
        """Та же дыра (Н-2), другая из ambiguous-колонок теневой таблицы — ``process``."""
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(text="crash", process="gui")
        assert result.get("success") is True, f"text+process дал отказ вместо результата: {result}"
        assert _messages(result) == ["widget crash detected"]


# ===========================================================================
# К7 — metric пока отвечает названным отказом (колонки metric в сторе ещё нет).
# ===========================================================================


class TestK7MetricNotYetSupported:
    def test_metric_filter_is_a_named_refusal_naming_reason_and_task(self, tmp_path) -> None:
        db_path, _ = _seed_small_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(metric="capture.frames")
        assert result.get("success") is False, (
            f"metric-фильтр обязан назвать отказ (колонки metric в сторе ещё нет, Task 3.1), "
            f"а НЕ тихо провалить фильтр и отдать всё подряд: {result}"
        )
        error_text = str(result.get("error", ""))
        assert "metric" in error_text.lower(), f"ошибка не называет ПРИЧИНУ (metric): {error_text!r}"
        assert "3.1" in error_text, f"ошибка не называет АДРЕС (Task 3.1): {error_text!r}"
        rows = _rows(result)
        assert not rows, f"отказ обязан быть БЕЗ строк, а не молчаливым полным дампом: {rows}"


# ===========================================================================
# К8 — кап и full: дефолтный limit=100 (не «вся БД»), full объявлен в схеме.
# ===========================================================================


class TestK8CapAndFull:
    def test_default_limit_is_100_not_the_whole_store(self, tmp_path) -> None:
        db_path = _seed_bulk_store(tmp_path, n=150)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query()
        rows = _rows(result)
        assert rows is not None
        assert len(rows) == 100, f"дефолтный limit обязан быть 100, получено {len(rows)} строк из 150"

    def test_cap_heavy_hint_promises_full_once_the_tool_is_registered(self) -> None:
        """К8 (вторая половина: «full снимает байтовый потолок») проверяется через
        РЕАЛЬНЫЙ ``backend_ctl.dispatch._cap_heavy`` — общий, уже существующий
        механизм. Сегодня history_query НЕ зарегистрирован в реестре, поэтому
        подсказка усечения обязана говорить «параметра full у этого инструмента
        нет» — и МОЯ проверка (обратное) обязана падать ИМЕННО на этом факте."""
        big_result = {"success": True, ROWS_KEY: [{"id": i, "message": "x" * 200} for i in range(200)]}
        capped = _cap_heavy("history_query", big_result, {})
        assert capped.get("_truncated") is True, f"большой ответ не усечён вовсе: ключи {sorted(capped.keys())}"
        hint = capped.get("_hint", "")
        assert "full=true — полный объём" in hint, (
            f"history_query ещё не зарегистрирован (или не объявил full) в MCP-реестре — "
            f"подсказка усечения не обещает full: {hint!r}"
        )
