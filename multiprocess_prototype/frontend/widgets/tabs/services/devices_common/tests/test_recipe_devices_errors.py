# -*- coding: utf-8 -*-
"""Приёмка F3 (plans/devices-tab-recipe-errors, Task 1.1): отказ записи/чтения рецепта не роняет слот.

Контракт ``RecipeDevicesStore.upsert/remove``: известные отказы файла рецепта (``RecipeLockTimeout``,
``RecipeFormatError``, ``YamlWriteRefused``, ``YamlPatchConflict``, ``OSError``) переводятся в
``RecipeDevicesError`` с литералом БЕЗ пути и содержимого файла; чужие исключения не переводятся.
Три слота (``AddDevicePage._on_commit``, ``DeviceCrudActions.on_remove_clicked`` / ``_persist_and_sync``)
показывают литерал и не роняются.

Слепой набор: пишется по REDS/ACCEPTANCE плана, реализацию хранилища не читал. Ожидаемые тексты — литералы.
Реальная цепочка (R1-R4, R9-R11): ``RecipeDevicesStore`` -> ``RecipeStoreFromManager`` -> ``RecipeManager`` ->
tmp-файл (движок-заглушка с ``recipes_dir``). Слоты (R6, R7): слот -> РЕАЛЬНЫЙ ``RecipeDevicesStore`` ->
внутренний фейк хранилища с бросающими ``read_canonical``/``save_raw``.
Всё, что может ждать лок, идёт в daemon-потоке с join-дедлайном (зависший вызов = красный, не зависший прогон).
"""

from __future__ import annotations

import copy
import logging
import os
import threading
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QMessageBox as _RealMB

from multiprocess_framework.modules.recipe import (
    RecipeConflict,
    RecipeFormatError,
    RecipeLockTimeout,
    YamlPatchConflict,
    YamlWriteRefused,
    recipe_file_lock,
)
from multiprocess_framework.modules.recipe import manager as _manager_module
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.add_page import AddDevicePage
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.crud_actions import DeviceCrudActions
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.presenter import DevicesPresenter
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.recipe_devices import (
    RecipeDevicesError,
    RecipeDevicesStore,
)

# --------------------------------------------------------------------------- #
# Литералы ожидаемых текстов (не выводятся из кода под тестом)
# --------------------------------------------------------------------------- #

LITERAL_LOCK = "Рецепт занят другим процессом — повторите через несколько секунд"
LITERAL_FORMAT = "Файл рецепта не читается или имеет неподдерживаемый формат — устройства не изменены"
LITERAL_REFUSED = "Не удалось безопасно записать рецепт — файл не изменён"
LITERAL_PATCH_CONFLICT = "Рецепт нельзя изменить точечно: общий узел YAML (якорь или алиас) — правьте файл вручную"
LITERAL_OSERROR = (
    "Не удалось прочитать или записать файл рецепта (например, нет доступа или места на диске) — устройства не изменены"
)
LITERAL_CONFLICT = "Рецепт изменён снаружи — перезагрузите его"

_SLUG = "demo"
_JOIN_DEADLINE_S = 10.0  # >= 8 с: запас над сокращённым таймаутом лока 0.1 с и над 5 с по умолчанию

_RECIPE_TEXT = (
    "name: Demo\n"
    "version: 1\n"
    "devices:\n"
    "  - id: r1\n"
    "    name: R1\n"
    "    kind: robot\n"
    "    transport:\n"
    "      type: tcp\n"
    "      host: 1.1.1.1\n"
    "      port: 502\n"
    "      unit_id: 1\n"
    "blueprint:\n"
    "  processes: []\n"
    "  wires: []\n"
)
_NEW_DEVICE = {
    "id": "r2",
    "name": "R2",
    "kind": "robot",
    "transport": {"type": "tcp", "host": "2.2.2.2", "port": 502, "unit_id": 1},
}

# --------------------------------------------------------------------------- #
# Реальная цепочка (образец: recipes/tests/test_save_noise_store.py::build_chain, скопировано)
# --------------------------------------------------------------------------- #


class _FakeEngine:
    """Минимальный движок: ``recipes_dir`` + активный slug."""

    def __init__(self, recipes_dir: Path) -> None:
        self.recipes_dir = recipes_dir
        self._active_name: str | None = None

    def get_active(self) -> str | None:
        return self._active_name

    def set_active(self, name: str) -> bool:
        self._active_name = name
        return True


def _build_store(recipes_dir: Path, yaml_patcher: Callable[..., bool] | None = None) -> RecipeDevicesStore:
    """Настоящие RecipeManager + RecipeStoreFromManager над ``recipes_dir`` + RecipeDevicesStore (активный = demo)."""
    from multiprocess_framework.modules.recipe import RecipeManager
    from multiprocess_prototype.adapters.stores.recipe_store import RecipeStoreFromManager

    engine = _FakeEngine(recipes_dir)
    engine.set_active(_SLUG)
    manager = RecipeManager(engine=engine, state_proxy=None, logger=None, yaml_patcher=yaml_patcher)
    chain = RecipeStoreFromManager(recipe_manager=manager, recipe_dir=recipes_dir)
    return RecipeDevicesStore(chain, active_provider=lambda: _SLUG)


def _put_recipe(recipes_dir: Path, content: str = _RECIPE_TEXT) -> tuple[Path, bytes]:
    path = recipes_dir / f"{_SLUG}.yaml"
    path.write_bytes(content.encode("utf-8"))
    return path, path.read_bytes()


# --------------------------------------------------------------------------- #
# Инфраструктура: daemon-поток с дедлайном, шов таймаута лока, держатель лока
# --------------------------------------------------------------------------- #


def _call_in_daemon(fn: Callable[[], Any]) -> BaseException | None:
    """Выполнить ``fn`` в daemon-потоке; вернуть брошенное исключение или ``None``. Зависание = ``pytest.fail``."""
    box: dict[str, BaseException] = {}

    def run() -> None:
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001 — тесту нужно любое исключение целиком
            box["exc"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(_JOIN_DEADLINE_S)
    if thread.is_alive():
        pytest.fail(f"вызов не завершился за {_JOIN_DEADLINE_S} с (зависание на локе?)")
    return box.get("exc")


def _short_lock_timeout(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Шов таймаута: имя ``recipe_file_lock`` в ``manager`` -> обёртка с ``timeout=0.1``. Возвращает журнал вызовов."""
    original = _manager_module.recipe_file_lock
    calls: list[Path] = []

    def short(path: Any, *, timeout: float = 5.0):
        calls.append(Path(path))
        return original(path, timeout=0.1)

    monkeypatch.setattr(_manager_module, "recipe_file_lock", short)
    return calls


@contextmanager
def _lock_held_by_stranger(path: Path):
    """Чужой держатель лока рецепта: отдельный дескриптор (в одном процессе два дескриптора конфликтуют)."""
    with recipe_file_lock(path, timeout=2.0):
        yield


def _assert_translated(exc: BaseException | None, literal: str, tmp_path: Path) -> None:
    assert isinstance(exc, RecipeDevicesError), f"ждали RecipeDevicesError, вылетело: {exc!r}"
    text = str(exc)
    assert text == literal
    assert str(tmp_path) not in text
    assert tmp_path.name not in text


def _locked_upsert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, op: str
) -> tuple[BaseException | None, Path, bytes]:
    """Реальная цепочка, лок рецепта занят чужим; ``op`` = upsert | remove. Возвращает (исключение, путь, байты до)."""
    path, before = _put_recipe(tmp_path)
    store = _build_store(tmp_path)
    seam_calls = _short_lock_timeout(monkeypatch)
    with _lock_held_by_stranger(path):
        if op == "upsert":
            exc = _call_in_daemon(lambda: store.upsert(copy.deepcopy(_NEW_DEVICE)))
        else:
            exc = _call_in_daemon(lambda: store.remove("r1"))
    assert seam_calls, "шов recipe_file_lock в manager не вызван: сценарий не дошёл до записи"
    return exc, path, before


# --------------------------------------------------------------------------- #
# Внутренний фейк хранилища для слотов и охранных тестов (RecipeDevicesStore — настоящий)
# --------------------------------------------------------------------------- #


class _FaultStore:
    """Фейк RecipeStore: ``read_canonical`` / ``save_raw`` бросают заданное исключение (``None`` — работают)."""

    def __init__(
        self,
        *,
        read_exc: BaseException | None = None,
        save_exc: BaseException | None = None,
        active: str | None = _SLUG,
    ) -> None:
        self._active = active
        self._read_exc = read_exc
        self._save_exc = save_exc
        self.save_calls = 0
        self._doc = {"devices": [{"id": "r1", "name": "R1", "kind": "robot"}]}

    def get_active(self) -> str | None:
        return self._active

    def read_raw(self, slug: str) -> dict | None:
        return copy.deepcopy(self._doc)

    def read_canonical(self, slug: str) -> tuple[dict | None, str | None]:
        if self._read_exc is not None:
            raise self._read_exc
        return copy.deepcopy(self._doc), "0"

    def save_raw(self, slug: str, data: dict, **kwargs: Any) -> str:
        self.save_calls += 1
        if self._save_exc is not None:
            raise self._save_exc
        return "1"


# --------------------------------------------------------------------------- #
# R1, R2: лок рецепта занят чужим процессом
# --------------------------------------------------------------------------- #


def test_r1_upsert_lock_busy_translated_to_literal_without_path_bytes_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exc, path, before = _locked_upsert(tmp_path, monkeypatch, "upsert")

    _assert_translated(exc, LITERAL_LOCK, tmp_path)
    assert path.read_bytes() == before


def test_r2_remove_lock_busy_translated_to_literal_without_path_bytes_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exc, path, before = _locked_upsert(tmp_path, monkeypatch, "remove")

    _assert_translated(exc, LITERAL_LOCK, tmp_path)
    assert path.read_bytes() == before


# --------------------------------------------------------------------------- #
# R3: файл рецепта не читается (не парсится / корень не mapping)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("op", ["upsert", "remove"])
@pytest.mark.parametrize("content", ["a: [\n", "- a\n"], ids=["unparseable", "root-is-list"])
def test_r3_unreadable_recipe_translated_to_format_literal_bytes_intact(tmp_path: Path, op: str, content: str) -> None:
    path, before = _put_recipe(tmp_path, content)
    store = _build_store(tmp_path)

    if op == "upsert":
        exc = _call_in_daemon(lambda: store.upsert(copy.deepcopy(_NEW_DEVICE)))
    else:
        exc = _call_in_daemon(lambda: store.remove("r1"))

    _assert_translated(exc, LITERAL_FORMAT, tmp_path)
    assert path.read_bytes() == before


# --------------------------------------------------------------------------- #
# R4: страховка/конфликт записи из yaml_patcher
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("exc_cls", "literal"),
    [
        pytest.param(YamlWriteRefused, LITERAL_REFUSED, id="YamlWriteRefused"),
        pytest.param(YamlPatchConflict, LITERAL_PATCH_CONFLICT, id="YamlPatchConflict"),
    ],
)
def test_r4_yaml_patcher_refusal_translated_without_leaking_path(
    tmp_path: Path, exc_cls: type[Exception], literal: str
) -> None:
    def patcher(path: Any, before: dict, after: dict) -> bool:
        raise exc_cls(f"{path}: подробности отказа записи")

    path, before = _put_recipe(tmp_path)
    store = _build_store(tmp_path, yaml_patcher=patcher)

    exc = _call_in_daemon(lambda: store.upsert(copy.deepcopy(_NEW_DEVICE)))

    _assert_translated(exc, literal, tmp_path)
    assert "подробности" not in str(exc)
    assert path.read_bytes() == before


# --------------------------------------------------------------------------- #
# R5 (охрана): RecipeConflict по-прежнему переводится
# --------------------------------------------------------------------------- #


def test_r5_recipe_conflict_still_translated_to_conflict_literal() -> None:
    store = RecipeDevicesStore(_FaultStore(save_exc=RecipeConflict(_SLUG, "1", "2")))

    with pytest.raises(RecipeDevicesError) as info:
        store.upsert(copy.deepcopy(_NEW_DEVICE))

    assert str(info.value) == LITERAL_CONFLICT


# --------------------------------------------------------------------------- #
# R6: слот AddDevicePage._on_commit при RecipeLockTimeout
# --------------------------------------------------------------------------- #


class _ImmediateRunner:
    def submit(self, fn, on_result) -> None:
        on_result(fn())


class _RecordingSender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def request_command(self, target: Any, cmd: str, args: dict) -> dict:
        self.calls.append((cmd, dict(args)))
        return {
            "device_protocols": {"protocols": ["delta_universal3"]},
            "device_list": {"devices": []},
        }.get(cmd, {"status": "ok"})

    def args_for(self, cmd: str) -> list[dict]:
        return [a for c, a in self.calls if c == cmd]


def _make_add_page(qtbot: Any, fault_store: _FaultStore):
    sender = _RecordingSender()
    presenter = DevicesPresenter(command_sender=sender, request_runner=_ImmediateRunner())
    committed: list[str] = []
    page = AddDevicePage(
        kind="robot",
        presenter=presenter,
        recipe_store=RecipeDevicesStore(fault_store),
        on_committed=lambda device_id: committed.append(device_id),
        on_cancel=lambda: None,
    )
    qtbot.addWidget(page)
    page._form.set_id("robot_x")
    page._form._edit_name.setText("Test")
    return page, sender, committed


def _no_escape(fn: Callable[[], Any]) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"исключение вышло из слота: {exc!r}")


def test_r6_add_page_commit_lock_timeout_shows_literal_and_changes_nothing(qtbot: Any) -> None:
    fault = _FaultStore(save_exc=RecipeLockTimeout(Path("/secret/recipes/demo.yaml.lock"), 5.0))
    page, sender, committed = _make_add_page(qtbot, fault)

    _no_escape(page._on_commit)

    assert page._status.text() == LITERAL_LOCK
    assert page._status.styleSheet() == "color: red;"
    assert sender.args_for("device_upsert") == []  # хаб не вызван
    assert committed == []
    assert page._committed is False


# --------------------------------------------------------------------------- #
# R7: три слота при RecipeFormatError и YamlWriteRefused из хранилища
# --------------------------------------------------------------------------- #

_R7_CASES = [
    pytest.param(
        lambda: RecipeFormatError("/secret/recipes/demo: файл рецепта не разбирается"),
        LITERAL_FORMAT,
        id="RecipeFormatError",
    ),
    pytest.param(
        lambda: YamlWriteRefused("/secret/recipes/demo.yaml: дамп ruamel не удался"),
        LITERAL_REFUSED,
        id="YamlWriteRefused",
    ),
]

_EDITOR = "multiprocess_prototype.frontend.widgets.tabs.services.devices_common.editor_dialog.DeviceEditorDialog"
_QMB = "multiprocess_prototype.frontend.widgets.tabs.services.devices_common.crud_actions.QMessageBox"


def _make_crud(fault_store: _FaultStore):
    sender = MagicMock()

    def request_command(target: Any, cmd: str, args: dict) -> dict:
        return {
            "device_protocols": {"protocols": ["delta_universal3"]},
            "device_list": {"devices": []},
            "device_upsert": {"status": "ok"},
            "device_remove": {"status": "ok"},
        }.get(cmd, {})

    sender.request_command.side_effect = request_command
    presenter = DevicesPresenter(command_sender=sender, request_runner=_ImmediateRunner())
    refresh = MagicMock()
    crud = DeviceCrudActions(
        kind="robot",
        presenter=presenter,
        recipe_store=RecipeDevicesStore(fault_store),
        refresh_cb=refresh,
        parent_widget=None,
    )
    return crud, sender, refresh


def _hub_commands(sender: MagicMock, *names: str) -> list[str]:
    return [c[0][1] for c in sender.request_command.call_args_list if c[0][1] in names]


@pytest.mark.parametrize(("make_exc", "literal"), _R7_CASES)
def test_r7_on_remove_clicked_shows_literal_and_skips_hub(make_exc: Callable[[], Exception], literal: str) -> None:
    crud, sender, refresh = _make_crud(_FaultStore(save_exc=make_exc()))

    with patch(_QMB) as MockMB:
        MockMB.StandardButton = _RealMB.StandardButton
        MockMB.question.return_value = _RealMB.StandardButton.Yes
        _no_escape(lambda: crud.on_remove_clicked("r1"))

    MockMB.warning.assert_called_once()
    assert MockMB.warning.call_args[0][2] == literal
    assert _hub_commands(sender, "device_remove", "device_upsert") == []
    refresh.assert_not_called()


@pytest.mark.parametrize(("make_exc", "literal"), _R7_CASES)
def test_r7_persist_and_sync_shows_literal_and_skips_hub(make_exc: Callable[[], Exception], literal: str) -> None:
    crud, sender, refresh = _make_crud(_FaultStore(save_exc=make_exc()))
    entry = copy.deepcopy(_NEW_DEVICE)

    with patch(_EDITOR) as MockDlg, patch(_QMB) as MockMB:
        inst = MagicMock()
        inst.exec.return_value = 1
        inst.Accepted = 1
        inst.get_entry.return_value = entry
        MockDlg.return_value = inst
        _no_escape(crud.on_add_clicked)

    MockMB.warning.assert_called_once()
    assert MockMB.warning.call_args[0][2] == literal
    assert _hub_commands(sender, "device_upsert") == []
    refresh.assert_not_called()


@pytest.mark.parametrize(("make_exc", "literal"), _R7_CASES)
def test_r7_add_page_commit_shows_literal_and_skips_hub(
    qtbot: Any, make_exc: Callable[[], Exception], literal: str
) -> None:
    page, sender, committed = _make_add_page(qtbot, _FaultStore(save_exc=make_exc()))

    _no_escape(page._on_commit)

    assert page._status.text() == literal
    assert page._status.styleSheet() == "color: red;"
    assert sender.args_for("device_upsert") == []
    assert committed == []
    assert page._committed is False


# --------------------------------------------------------------------------- #
# R8 (охрана): чужие исключения не переводятся
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("where", ["read_canonical", "save_raw"])
@pytest.mark.parametrize(
    "foreign", [AttributeError("programmer error"), KeyError("programmer_key")], ids=["AttributeError", "KeyError"]
)
def test_r8_foreign_exception_is_not_translated(where: str, foreign: Exception) -> None:
    fault = _FaultStore(read_exc=foreign) if where == "read_canonical" else _FaultStore(save_exc=foreign)
    store = RecipeDevicesStore(fault)

    with pytest.raises(type(foreign)) as info:
        store.upsert(copy.deepcopy(_NEW_DEVICE))

    assert info.value is foreign
    assert not isinstance(info.value, RecipeDevicesError)


# --------------------------------------------------------------------------- #
# R9 (охрана): list() на битом рецепте по-прежнему []
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("content", ["a: [\n", "- a\n"], ids=["unparseable", "root-is-list"])
def test_r9_list_on_broken_recipe_still_returns_empty(tmp_path: Path, content: str) -> None:
    _put_recipe(tmp_path, content)
    store = _build_store(tmp_path)
    box: list[Any] = []

    exc = _call_in_daemon(lambda: box.append(store.list()))

    assert exc is None, f"list() не должен бросать: {exc!r}"
    assert box == [[]]


# --------------------------------------------------------------------------- #
# R10: файл рецепта только для чтения -> OSError переводится
# --------------------------------------------------------------------------- #


def test_r10_readonly_recipe_translated_to_oserror_literal(tmp_path: Path) -> None:
    path, before = _put_recipe(tmp_path)
    store = _build_store(tmp_path)
    os.chmod(path, 0o444)
    try:
        if os.access(path, os.W_OK):
            pytest.skip("процесс обходит права файла (root?): os.access(W_OK) истинно после chmod 0o444")
        exc = _call_in_daemon(lambda: store.upsert(copy.deepcopy(_NEW_DEVICE)))
        _assert_translated(exc, LITERAL_OSERROR, tmp_path)
        assert path.read_bytes() == before
    finally:
        os.chmod(path, 0o644)


# --------------------------------------------------------------------------- #
# R11: лог — имя класса, без пути
# --------------------------------------------------------------------------- #


def test_r11_lock_timeout_logged_as_warning_with_class_name_without_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        exc, _path, _before = _locked_upsert(tmp_path, monkeypatch, "upsert")

    assert isinstance(exc, RecipeDevicesError), f"ждали RecipeDevicesError, вылетело: {exc!r}"
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("RecipeLockTimeout" in r.getMessage() for r in warnings), caplog.text
    assert str(tmp_path) not in caplog.text
    assert tmp_path.name not in caplog.text


# --------------------------------------------------------------------------- #
# Контроль сценария: без отказа та же цепочка пишет и удаляет (красные R1-R4 красны из-за отказа, не из-за сценария)
# --------------------------------------------------------------------------- #


def test_control_clean_chain_upsert_and_remove_work(tmp_path: Path) -> None:
    import yaml

    path, _before = _put_recipe(tmp_path)
    store = _build_store(tmp_path)

    assert _call_in_daemon(lambda: store.upsert(copy.deepcopy(_NEW_DEVICE))) is None
    assert [d["id"] for d in yaml.safe_load(path.read_text(encoding="utf-8"))["devices"]] == ["r1", "r2"]

    assert _call_in_daemon(lambda: store.remove("r1")) is None
    assert [d["id"] for d in yaml.safe_load(path.read_text(encoding="utf-8"))["devices"]] == ["r2"]
