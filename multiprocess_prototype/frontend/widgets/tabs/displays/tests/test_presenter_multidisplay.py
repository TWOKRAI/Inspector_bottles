# -*- coding: utf-8 -*-
"""Тесты DisplaysPresenter — auto-id, name-default, enabled toggle (мульти-дисплей).

Pure-логика presenter без Qt (fake view + FakeDisplayCatalog + fake event bus).

Запуск (из ):
    python -m pytest multiprocess_prototype/frontend/widgets/tabs/displays/tests/test_presenter_multidisplay.py -v
"""

from __future__ import annotations

from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec
from multiprocess_prototype.domain.tests._fakes import FakeDisplayCatalog
from multiprocess_prototype.frontend.widgets.tabs.displays.presenter import DisplaysPresenter


class _FakeView:
    """Минимальный IDisplaysView для presenter-тестов."""

    def __init__(self, form_data: dict) -> None:
        self._form_data = form_data
        self.errors: list[str] = []
        self.last_specs: list[DisplaySpec] | None = None
        self.last_entry: DisplaySpec | None = None

    def refresh_list(self, specs):
        self.last_specs = list(specs)

    def show_entry(self, spec):
        self.last_entry = spec

    def set_buttons_state(self, has_selection: bool):
        pass

    def get_form_data(self) -> dict:
        return self._form_data

    def show_error(self, message: str):
        self.errors.append(message)


class _FakeEventBus:
    def __init__(self) -> None:
        self.published: list = []

    def publish(self, event) -> None:
        self.published.append(event)


def _form(**overrides) -> dict:
    base = {
        "id": "",
        "name": "",
        "enabled": True,
        "width": 1280,
        "height": 720,
        "format": "BGR",
        "fps_limit": 30.0,
        "ring_buffer_blocks": 3,
        "position": {"x": 0, "y": 0},
        "fit": "contain",
        "scale": 100,
        "rotate": 0,
        "flip": "none",
        "crop": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# auto-id
# ---------------------------------------------------------------------------


class TestAutoId:
    def test_first_create_generates_display_1(self) -> None:
        store = FakeDisplayCatalog()
        view = _FakeView(_form(name="Моя камера"))
        presenter = DisplaysPresenter(store=store, view=view)

        presenter.on_create()

        assert store.has("display_1")
        assert not view.errors

    def test_sequential_ids_skip_taken(self) -> None:
        store = FakeDisplayCatalog(specs={"display_1": DisplaySpec(display_id="display_1", display_name="x")})
        view = _FakeView(_form(name="Вторая"))
        presenter = DisplaysPresenter(store=store, view=view)

        presenter.on_create()

        assert store.has("display_2")

    def test_form_id_ignored(self) -> None:
        """ID из формы игнорируется — id всегда генерируется."""
        store = FakeDisplayCatalog()
        view = _FakeView(_form(id="custom_user_id", name="N"))
        presenter = DisplaysPresenter(store=store, view=view)

        presenter.on_create()

        assert store.has("display_1")
        assert not store.has("custom_user_id")


# ---------------------------------------------------------------------------
# name-default
# ---------------------------------------------------------------------------


class TestNameDefault:
    def test_empty_name_defaults_to_id(self) -> None:
        store = FakeDisplayCatalog()
        view = _FakeView(_form(name=""))
        presenter = DisplaysPresenter(store=store, view=view)

        presenter.on_create()

        spec = store.resolve("display_1")
        assert spec is not None
        assert spec.display_name == "display_1"

    def test_user_name_preserved(self) -> None:
        store = FakeDisplayCatalog()
        view = _FakeView(_form(name="Маска белого"))
        presenter = DisplaysPresenter(store=store, view=view)

        presenter.on_create()

        spec = store.resolve("display_1")
        assert spec.display_name == "Маска белого"


# ---------------------------------------------------------------------------
# enabled
# ---------------------------------------------------------------------------


class TestEnabledOnCreate:
    def test_enabled_default_true(self) -> None:
        store = FakeDisplayCatalog()
        view = _FakeView(_form(enabled=True))
        presenter = DisplaysPresenter(store=store, view=view)

        presenter.on_create()

        assert store.resolve("display_1").enabled is True

    def test_enabled_false_persisted(self) -> None:
        store = FakeDisplayCatalog()
        view = _FakeView(_form(enabled=False))
        presenter = DisplaysPresenter(store=store, view=view)

        presenter.on_create()

        assert store.resolve("display_1").enabled is False


# ---------------------------------------------------------------------------
# on_set_enabled (toggle)
# ---------------------------------------------------------------------------


class TestSetEnabled:
    def _make(self, enabled: bool):
        store = FakeDisplayCatalog(specs={"d1": DisplaySpec(display_id="d1", display_name="D1", enabled=enabled)})
        bus = _FakeEventBus()
        view = _FakeView(_form())
        presenter = DisplaysPresenter(store=store, view=view, event_bus=bus)
        return store, bus, presenter

    def test_toggle_off_updates_store(self) -> None:
        store, bus, presenter = self._make(enabled=True)
        presenter.on_set_enabled("d1", False)
        assert store.resolve("d1").enabled is False

    def test_toggle_emits_displays_changed(self) -> None:
        from multiprocess_prototype.domain.events import DisplaysChanged

        store, bus, presenter = self._make(enabled=True)
        presenter.on_set_enabled("d1", False)
        assert len(bus.published) == 1
        assert isinstance(bus.published[0], DisplaysChanged)

    def test_no_change_when_value_same(self) -> None:
        store, bus, presenter = self._make(enabled=True)
        presenter.on_set_enabled("d1", True)
        # без изменений → событие не эмитится
        assert bus.published == []

    def test_unknown_id_noop(self) -> None:
        store, bus, presenter = self._make(enabled=True)
        presenter.on_set_enabled("missing", False)
        assert bus.published == []

    def test_create_emits_displays_changed(self) -> None:
        from multiprocess_prototype.domain.events import DisplaysChanged

        store = FakeDisplayCatalog()
        bus = _FakeEventBus()
        view = _FakeView(_form(name="N"))
        presenter = DisplaysPresenter(store=store, view=view, event_bus=bus)

        presenter.on_create()

        assert any(isinstance(e, DisplaysChanged) for e in bus.published)
