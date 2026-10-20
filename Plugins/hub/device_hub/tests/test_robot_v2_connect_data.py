"""Тесты автора T5.3c c2: ``DeviceManager.connect`` перехватывает ошибки данных робота при создании драйвера.

Purpose:
    Фабрика ``robot`` (``delta_v2``) с хранилищем читает параметры через ``param_source`` уже в конструкторе драйвера;
    ``RobotDataInvalid``, ``StoreDocumentInvalid``, ``InvalidStoreKey`` -> ``last_error`` (постоянный текст),
    ``conn: error``, ``False``, без исключения. Драйвер не создан - следующий ``connect`` после правки файла не
    застревает на старом отказе.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

from pathlib import Path

import pytest

from Services.device_hub.manager import DeviceManager
from Services.robot_comm.store import RobotDataStore

TEXT_DATA_INVALID = "Данные робота не прошли проверку"
TEXT_NOT_YAML = "Файл данных робота не YAML-словарь"
TEXT_BAD_KEY = "Недопустимое имя данных робота"
TEXT_STORE_ERROR = "ошибка хранилища данных робота"
TEXT_WDG = "Сторож робота нельзя выключить: P_WDG_TIMEOUT_MS = 0"


def _manager(tmp_path: Path, dev_id: str, params: dict | None = None) -> tuple[DeviceManager, list[tuple[str, object]]]:
    published: list[tuple[str, object]] = []
    manager = DeviceManager(
        store=None,
        publish_cb=lambda path, data: published.append((path, data)),
        spawn=lambda *_a, **_k: None,  # до spawn не доходит: отказ приходит из конструктора драйвера
        robot_store=RobotDataStore(tmp_path / "robot"),
    )
    manager.initialize()
    entry = {
        "id": dev_id,
        "name": "r",
        "kind": "robot",
        "protocol": "delta_v2",
        "transport": {"type": "tcp", "host": "127.0.0.1", "port": 50999, "unit_id": 2},
    }
    if params is not None:
        entry["params"] = params
    manager.upsert(entry)
    return manager, published


def _refused(manager: DeviceManager, published: list, dev_id: str, text: str) -> None:
    assert manager.connect(dev_id) is False
    assert (f"devices.state.{dev_id}.last_error", text) in published
    assert (f"devices.state.{dev_id}.conn", {"conn": "error"}) in published
    assert manager.get_driver(dev_id) is None  # драйвер не создан: следующий connect снова пройдёт фабрику


def test_bad_override_refused_without_exception(tmp_path: Path) -> None:
    manager, published = _manager(tmp_path, "r1", {"robot_params": {"P_NOPE": 1}})
    _refused(manager, published, "r1", TEXT_DATA_INVALID)


def test_wdg_zero_override_refused_with_wdg_text(tmp_path: Path) -> None:
    manager, published = _manager(tmp_path, "r1", {"robot_params": {"P_WDG_TIMEOUT_MS": 0}})
    _refused(manager, published, "r1", TEXT_WDG)


def test_params_file_not_a_mapping_refused(tmp_path: Path) -> None:
    manager, published = _manager(tmp_path, "r1")
    (tmp_path / "robot" / "r1").mkdir(parents=True)
    (tmp_path / "robot" / "r1" / "params.yaml").write_text("- 1\n", encoding="utf-8")
    _refused(manager, published, "r1", TEXT_NOT_YAML)


def test_invalid_store_key_refused(tmp_path: Path) -> None:
    manager, published = _manager(tmp_path, "r" * 65)
    _refused(manager, published, "r" * 65, TEXT_BAD_KEY)


def test_params_file_oserror_refused_with_constant_text(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """G3: ``OSError`` диска при создании драйвера -> постоянный текст в ``last_error``, путь — только в лог."""
    manager, published = _manager(tmp_path, "r1")
    (tmp_path / "robot" / "r1" / "params.yaml").mkdir(parents=True)  # файл параметров — каталог
    with caplog.at_level("WARNING"):
        _refused(manager, published, "r1", TEXT_STORE_ERROR)
    texts = [str(data) for path, data in published if path.endswith(".last_error")]
    assert all("params.yaml" not in text for text in texts)
    assert any("params.yaml" in record.getMessage() for record in caplog.records)  # полный текст — в логе
