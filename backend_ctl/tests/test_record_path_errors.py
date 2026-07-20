# -*- coding: utf-8 -*-
"""Task 1.4 — файловые ошибки record_* не выдают себя за обрыв связи.

Находка ultra-ревью: недоступный ``BACKEND_CTL_RECORD_DIR`` (нет прав, путь занят
файлом, диск отвалился) поднимал голый ``PermissionError``/``NotADirectoryError``.
Выше по стеку ``call_tool`` ловил это веткой ``except OSError`` — «соединение с
бэкендом оборвано» — и сбрасывал ЗДОРОВЫЙ driver: обрывались живые durable-подписки
и watch-контур, а агент получал диагностику про сеть, хотя сеть была ни при чём.

Здесь стережём обе половины контракта: ошибка называет ПУТЬ и причину, а живое
соединение остаётся живым.
"""

from __future__ import annotations

import os
from typing import Any, Dict

import pytest

from backend_ctl.mcp_tools import _ArgError, _resolve_or_error
from backend_ctl.recorder import RecordingError, load_recording


def test_unwritable_record_dir_names_the_path_not_the_network(tmp_path, monkeypatch) -> None:
    """Каталог записей — на самом деле файл → обучающая ошибка про путь, не OSError."""
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("я файл, а не каталог", encoding="utf-8")
    monkeypatch.setenv("BACKEND_CTL_RECORD_DIR", str(blocker))

    with pytest.raises(_ArgError) as ei:
        _resolve_or_error("smoke", create_dir=True)

    message = str(ei.value)
    assert "BACKEND_CTL_RECORD_DIR" in message, "ошибка обязана назвать переменную, которую чинить"
    # Голый OSError здесь означал бы возврат к находке: его поймала бы ветка «обрыв связи».
    assert not isinstance(ei.value, OSError)


def test_load_recording_on_directory_raises_recording_error(tmp_path) -> None:
    """record_load по каталогу вместо файла → RecordingError с путём, не голый OSError."""
    with pytest.raises(RecordingError) as ei:
        load_recording(str(tmp_path))
    # Сверяем по basename, а не по полному пути: repr на Windows экранирует разделители
    # (C:\\Users\\...), и подстрока сырого пути в тексте не нашлась бы.
    assert os.path.basename(str(tmp_path)) in str(ei.value)


def test_load_recording_missing_file_still_raises_file_not_found(tmp_path) -> None:
    """FileNotFoundError остаётся FileNotFoundError — документированный контракт функции."""
    with pytest.raises(FileNotFoundError):
        load_recording(str(tmp_path / "нет-такого.jsonl"))


class _LiveFakeDriver:
    """Driver, который умеет замечать, что его закрыли."""

    def __init__(self) -> None:
        self.connection_lost = False
        self.closed = False

    def export_subscriptions(self) -> list:
        return [{"topic": "state.changed"}]

    def import_subscriptions(self, intents: list) -> None:
        pass

    def replay_subscriptions(self) -> list:
        return []

    def close(self) -> None:
        self.closed = True


def test_record_start_on_bad_dir_keeps_driver_alive(tmp_path, monkeypatch) -> None:
    """Сквозь dispatch_tool: битый каталог записей НЕ сбрасывает живой driver.

    Это и есть цена находки — из-за файловой ошибки рвалась работающая сессия.
    """
    from backend_ctl.mcp_driver_session import DriverSession
    from backend_ctl.mcp_tools import dispatch_tool

    blocker = tmp_path / "not_a_dir"
    blocker.write_text("файл на месте каталога", encoding="utf-8")
    monkeypatch.setenv("BACKEND_CTL_RECORD_DIR", str(blocker))

    driver = _LiveFakeDriver()
    session = DriverSession(driver_factory=lambda: driver, log=lambda _m: None)
    session.ensure()

    result: Dict[str, Any] = dispatch_tool(session, "record_start", {"name": "smoke"})

    assert result.get("success") is False, "битый путь обязан дать честный отказ"
    assert driver.closed is False, "здоровый driver не должен закрываться из-за файловой ошибки"
    assert session.ensure() is driver, "сессия обязана сохранить то же соединение"


def test_record_dir_env_is_read_fresh(tmp_path, monkeypatch) -> None:
    """Резолв читает переменную окружения на каждый вызов (иначе тесты выше лгали бы)."""
    monkeypatch.setenv("BACKEND_CTL_RECORD_DIR", str(tmp_path))
    path = _resolve_or_error("smoke", create_dir=True)
    assert os.path.dirname(path) == str(tmp_path)
