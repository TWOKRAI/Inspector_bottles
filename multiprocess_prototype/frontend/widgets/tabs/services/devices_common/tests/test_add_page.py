# -*- coding: utf-8 -*-
"""Тесты AddDevicePage — пробное подключение перед сохранением (Фаза D).

«Проверить связь» → пробный upsert(origin=probe)+connect (НЕ в рецепт);
«Добавить» → персист в рецепт + re-tag origin=recipe; «Отмена»/уход → remove пробного.
"""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.add_page import (
    AddDevicePage,
)
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.recipe_devices import (
    RecipeDevicesStore,
)


class _ImmediateRunner:
    def submit(self, fn, on_result) -> None:
        on_result(fn())


class _RecordingSender:
    def __init__(self):
        self.calls = []  # (cmd, args)

    def request_command(self, target, cmd, args):
        self.calls.append((cmd, dict(args)))
        return {
            "device_protocols": {"protocols": ["delta_universal3"]},
            "device_list": {"devices": []},
        }.get(cmd, {"status": "ok"})

    def cmds(self):
        return [c for c, _ in self.calls]

    def args_for(self, cmd):
        return [a for c, a in self.calls if c == cmd]


class _DictRecipeStore:
    def __init__(self, active="demo"):
        self._active = active
        self._data = {"demo": {"devices": []}}

    def get_active(self):
        return self._active

    def read_raw(self, slug):
        return self._data.get(slug)

    def save_raw(self, slug, data):
        self._data.setdefault(slug, {}).update(data)


def _make_page(qtbot, active="demo"):
    from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.presenter import (
        DevicesPresenter,
    )

    sender = _RecordingSender()
    presenter = DevicesPresenter(command_sender=sender, request_runner=_ImmediateRunner())
    store = RecipeDevicesStore(_DictRecipeStore(active=active))
    committed = []
    cancelled = []
    page = AddDevicePage(
        kind="robot",
        presenter=presenter,
        recipe_store=store,
        on_committed=lambda d: committed.append(d),
        on_cancel=lambda: cancelled.append(True),
    )
    qtbot.addWidget(page)
    return page, store, sender, committed, cancelled


def _fill(page, dev_id="robot_x"):
    page._form.set_id(dev_id)
    page._form._edit_name.setText("Test")


class TestNoActiveRecipe:
    def test_blocks_without_active(self, qtbot):
        page, store, sender, committed, cancelled = _make_page(qtbot, active=None)
        # форма не строится, кнопок нет
        assert page._form is None


class TestProbe:
    def test_check_does_provisional_upsert_and_connect(self, qtbot):
        page, store, sender, committed, cancelled = _make_page(qtbot)
        _fill(page, "robot_x")
        page._on_check()
        # пробный upsert с origin=probe, затем connect
        ups = sender.args_for("device_upsert")
        assert ups and ups[-1]["origin"] == "probe"
        assert sender.args_for("device_connect")[-1]["device_id"] == "robot_x"
        # в рецепт НЕ записано
        assert store.list() == []

    def test_conn_delta_updates_status(self, qtbot):
        page, store, sender, committed, cancelled = _make_page(qtbot)
        _fill(page, "robot_x")
        page._on_check()
        page._on_conn_delta("devices.state.robot_x.conn", {"conn": "connected"})
        assert "связь есть" in page._status.text()


class TestCommit:
    def test_commit_persists_recipe_and_retags(self, qtbot):
        page, store, sender, committed, cancelled = _make_page(qtbot)
        _fill(page, "robot_x")
        page._on_check()
        page._on_commit()
        # рецепт содержит устройство
        assert [d["id"] for d in store.list()] == ["robot_x"]
        # последний upsert — recipe-origin (re-tag)
        assert sender.args_for("device_upsert")[-1]["origin"] == "recipe:demo"
        assert committed == ["robot_x"]

    def test_commit_without_id_warns(self, qtbot):
        page, store, sender, committed, cancelled = _make_page(qtbot)
        page._on_commit()
        assert store.list() == []
        assert committed == []


class TestCancelCleanup:
    def test_cancel_removes_probe(self, qtbot):
        page, store, sender, committed, cancelled = _make_page(qtbot)
        _fill(page, "robot_x")
        page._on_check()
        page._on_cancel_clicked()
        # пробное устройство удалено из hub
        assert sender.args_for("device_remove")[-1]["device_id"] == "robot_x"
        assert cancelled == [True]

    def test_cleanup_noop_after_commit(self, qtbot):
        page, store, sender, committed, cancelled = _make_page(qtbot)
        _fill(page, "robot_x")
        page._on_check()
        page._on_commit()
        sender.calls.clear()
        page.cleanup()  # уже сохранено — remove не должен вызываться
        assert "device_remove" not in sender.cmds()
