# -*- coding: utf-8 -*-
"""Тесты DeviceCrudActions — CRUD-поток рецепт→hub (Фаза C device-tree-recipe).

Проверяет порядок: персист в рецепт (RecipeDevicesStore, истина) → отражение в
hub (presenter.device_upsert/remove) → refresh_cb. Без активного рецепта —
добавление блокируется.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from multiprocess_framework.modules.recipe import RecipeConflict
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.crud_actions import (
    DeviceCrudActions,
)
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.presenter import (
    DevicesPresenter,
)
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.recipe_devices import (
    RecipeDevicesStore,
)


class _ImmediateRunner:
    """RequestRunner-стаб: выполняет синхронно в том же потоке."""

    def submit(self, fn, on_result) -> None:
        on_result(fn())


class _DictRecipeStore:
    """In-memory RecipeStore (read_canonical/save_raw/get_active) для тестов."""

    def __init__(self, active: str | None = "demo") -> None:
        self._active = active
        self._data: dict[str, dict] = {"demo": {"devices": []}}
        self._revs: dict[str, int] = {}

    def get_active(self) -> str | None:
        return self._active

    def read_raw(self, slug: str) -> dict | None:
        return self._data.get(slug)

    def read_canonical(self, slug: str) -> tuple[dict | None, str | None]:
        doc = self._data.get(slug)
        return doc, (None if doc is None else str(self._revs.get(slug, 0)))

    def save_raw(self, slug: str, data: dict, *, expected_rev: str | None = None) -> str:
        current = None if slug not in self._data else str(self._revs.get(slug, 0))
        if expected_rev is not None and expected_rev != current:
            raise RecipeConflict(slug, expected_rev, current)
        self._data.setdefault(slug, {}).update(data)
        self._revs[slug] = self._revs.get(slug, 0) + 1
        return str(self._revs[slug])


def _make_crud(*, kind="robot", active="demo"):
    sender = MagicMock()

    def request_command(target, cmd, args):
        return {
            "device_protocols": {"protocols": ["delta_universal3"]},
            "device_list": {"devices": []},
            "device_upsert": {"status": "ok"},
            "device_remove": {"status": "ok"},
            "device_describe": {
                "id": "r1",
                "name": "Робот",
                "kind": kind,
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            },
        }.get(cmd, {})

    sender.request_command.side_effect = request_command
    presenter = DevicesPresenter(command_sender=sender, request_runner=_ImmediateRunner())
    recipe_store = RecipeDevicesStore(_DictRecipeStore(active=active))
    refresh = MagicMock()
    crud = DeviceCrudActions(
        kind=kind,
        presenter=presenter,
        recipe_store=recipe_store,
        refresh_cb=refresh,
        parent_widget=None,
    )
    return crud, recipe_store, sender, refresh


_EDITOR = "multiprocess_prototype.frontend.widgets.tabs.services.devices_common.editor_dialog.DeviceEditorDialog"
_QMB = "multiprocess_prototype.frontend.widgets.tabs.services.devices_common.crud_actions.QMessageBox"


class TestAdd:
    def test_add_blocked_without_active_recipe(self) -> None:
        crud, store, sender, refresh = _make_crud(active=None)
        with patch(_QMB) as MockMB:
            crud.on_add_clicked()
        MockMB.information.assert_called_once()  # подсказка показана
        sender.request_command.assert_not_called()  # протоколы не запрашивались

    def test_add_accept_persists_recipe_then_hub(self) -> None:
        crud, store, sender, refresh = _make_crud()
        entry = {
            "id": "robot_new",
            "name": "Новый",
            "kind": "robot",
            "transport": {"type": "tcp", "host": "127.0.0.1", "port": 502, "unit_id": 1},
        }
        with patch(_EDITOR) as MockDlg:
            inst = MagicMock()
            inst.exec.return_value = 1
            inst.Accepted = 1
            inst.get_entry.return_value = entry
            MockDlg.return_value = inst
            crud.on_add_clicked()

        # рецепт обновлён (истина)
        assert [d["id"] for d in store.list()] == ["robot_new"]
        # hub вызван с origin recipe:demo
        upserts = [c for c in sender.request_command.call_args_list if c[0][1] == "device_upsert"]
        assert len(upserts) == 1
        assert upserts[0][0][2]["id"] == "robot_new"
        assert upserts[0][0][2]["origin"] == "recipe:demo"
        # список обновлён
        refresh.assert_called()

    def test_add_real_dialog_accept(self, qtbot, monkeypatch) -> None:
        """Регрессия: exec() сравнивается с QDialog.DialogCode.Accepted на РЕАЛЬНОМ
        DeviceEditorDialog (инстанс QDialog не имеет атрибута .Accepted — баг живого
        запуска, который скрыли моки)."""
        from PySide6.QtWidgets import QDialog

        from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.editor_dialog import (
            DeviceEditorDialog,
        )

        crud, store, sender, refresh = _make_crud()
        entry = {
            "id": "robot_real",
            "name": "Реальный",
            "kind": "robot",
            "transport": {"type": "tcp", "host": "127.0.0.1", "port": 502, "unit_id": 1},
        }
        # Реальный класс диалога; патчим только exec (модальность) и get_entry.
        monkeypatch.setattr(DeviceEditorDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
        monkeypatch.setattr(DeviceEditorDialog, "get_entry", lambda self: entry)

        crud.on_add_clicked()  # не должен бросить AttributeError на dlg.Accepted

        assert [d["id"] for d in store.list()] == ["robot_real"]
        assert any(c[0][1] == "device_upsert" for c in sender.request_command.call_args_list)

    def test_add_reject_no_persist(self) -> None:
        crud, store, sender, refresh = _make_crud()
        with patch(_EDITOR) as MockDlg:
            inst = MagicMock()
            inst.exec.return_value = 0  # Rejected
            inst.Accepted = 1
            MockDlg.return_value = inst
            crud.on_add_clicked()
        assert store.list() == []
        assert not any(c[0][1] == "device_upsert" for c in sender.request_command.call_args_list)


class TestRemove:
    def test_remove_confirmed_recipe_then_hub(self) -> None:
        crud, store, sender, refresh = _make_crud()
        store.upsert({"id": "r1", "name": "R", "kind": "robot"})
        with patch(_QMB) as MockMB:
            from PySide6.QtWidgets import QMessageBox as _RealMB

            MockMB.StandardButton = _RealMB.StandardButton
            MockMB.question.return_value = _RealMB.StandardButton.Yes
            crud.on_remove_clicked("r1")
        # рецепт: устройство удалено
        assert store.list() == []
        # hub: device_remove вызван
        removes = [c for c in sender.request_command.call_args_list if c[0][1] == "device_remove"]
        assert removes and removes[0][0][2]["device_id"] == "r1"
        refresh.assert_called()

    def test_remove_cancelled_no_op(self) -> None:
        crud, store, sender, refresh = _make_crud()
        store.upsert({"id": "r1", "name": "R", "kind": "robot"})
        with patch(_QMB) as MockMB:
            from PySide6.QtWidgets import QMessageBox as _RealMB

            MockMB.StandardButton = _RealMB.StandardButton
            MockMB.question.return_value = _RealMB.StandardButton.No
            crud.on_remove_clicked("r1")
        # рецепт не тронут, hub не вызван
        assert [d["id"] for d in store.list()] == ["r1"]
        assert not any(c[0][1] == "device_remove" for c in sender.request_command.call_args_list)
