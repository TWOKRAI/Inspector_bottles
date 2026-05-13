# -*- coding: utf-8 -*-
"""Тесты SystemSettingsPresenter — pure-Python, без Qt.

Проверяет:
  - test_save_validates_and_persists        : save() валидирует через SystemConfig и вызывает save_settings
  - test_save_validation_error_shows_on_view: невалидные данные → view.show_validation_error()
  - test_reload_resets_editors              : reload() вызывает view.set_editor_value() для каждого поля
  - test_field_change_marks_dirty           : on_field_changed() → _dirty=True, on_dirty_changed вызван
  - test_save_resets_dirty                  : save() → _dirty=False
  - test_save_notifies_on_settings_saved    : save() вызывает on_settings_saved с dict
  - test_reload_clears_validation_errors    : reload() вызывает view.clear_validation_errors()
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


from multiprocess_prototype.frontend.widgets.tabs.settings.system.presenter import (
    SystemSettingsPresenter,
)
from multiprocess_prototype.config.schemas import SystemConfig


# ---------------------------------------------------------------------------
# Вспомогательные классы и фабрики
# ---------------------------------------------------------------------------


class MockSystemView:
    """Mock для SystemSettingsView Protocol — чистый Python, без Qt."""

    def __init__(self) -> None:
        # Хранилище значений редакторов (key → value)
        self.editor_values: dict[str, object] = {}
        # Текущий флаг dirty
        self.dirty_indicator: bool | None = None
        # Записи вызовов show_validation_error
        self.validation_errors: list[tuple[str, str]] = []
        # Счётчик clear_validation_errors
        self.clear_called: int = 0
        # Записи set_editor_value(key, value)
        self.set_editor_calls: list[tuple[str, object]] = []

    def get_editor_values(self) -> dict[str, object]:
        """Вернуть текущие значения редакторов."""
        return self.editor_values

    def set_editor_value(self, key: str, value: object) -> None:
        """Установить значение редактора."""
        self.editor_values[key] = value
        self.set_editor_calls.append((key, value))

    def set_dirty_indicator(self, dirty: bool) -> None:
        """Обновить индикатор несохранённых изменений."""
        self.dirty_indicator = dirty

    def show_validation_error(self, key: str, message: str) -> None:
        """Зафиксировать ошибку валидации."""
        self.validation_errors.append((key, message))

    def clear_validation_errors(self) -> None:
        """Сбросить все ошибки валидации."""
        self.clear_called += 1

    def set_save_enabled(self, enabled: bool) -> None:
        """Управление кнопкой сохранения (в тестах не проверяем)."""

    def set_reset_enabled(self, enabled: bool) -> None:
        """Управление кнопкой сброса (в тестах не проверяем)."""


def _make_mock_ctx() -> MagicMock:
    """Создать mock AppContext с action_bus() → None."""
    ctx = MagicMock()
    ctx.action_bus.return_value = None
    return ctx


def _make_presenter(
    view: MockSystemView | None = None,
    cfg: SystemConfig | None = None,
) -> SystemSettingsPresenter:
    """Создать presenter с замоканными yaml_io функциями.

    load_settings → возвращает cfg (или SystemConfig()),
    save_settings → заглушка,
    schema_to_field_infos → возвращает пустой список (чтобы не нужен реестр полей в __init__).
    """
    if view is None:
        view = MockSystemView()
    if cfg is None:
        cfg = SystemConfig()

    ctx = _make_mock_ctx()

    # Патчим yaml_io в контексте модуля presenter
    target_module = (
        "multiprocess_prototype.frontend.widgets.tabs.settings.system.presenter"
    )
    with (
        patch(f"{target_module}.load_settings", return_value=cfg),
        patch(f"{target_module}.save_settings"),
        patch(f"{target_module}.schema_to_field_infos", return_value=[]),
    ):
        presenter = SystemSettingsPresenter(view=view, rm=None, ui=None, ctx=ctx)

    return presenter


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestSave:
    """Тесты метода save()."""

    def test_save_validates_and_persists(self) -> None:
        """save() собирает значения из view, валидирует через SystemConfig и вызывает save_settings."""
        view = MockSystemView()
        # Допустимые значения для SystemConfig (секция.поле = значение)
        view.editor_values = {
            "system.stop_timeout": 5.0,
            "camera.fps": 25,
        }
        presenter = _make_presenter(view=view)

        target_module = (
            "multiprocess_prototype.frontend.widgets.tabs.settings.system.presenter"
        )
        with patch(f"{target_module}.save_settings") as mock_save:
            result = presenter.save()

        assert result is True
        mock_save.assert_called_once()
        # Первый аргумент save_settings — это SystemConfig-объект
        saved_cfg = mock_save.call_args[0][0]
        assert isinstance(saved_cfg, SystemConfig)

    def test_save_validation_error_shows_on_view(self) -> None:
        """save() с невалидными данными → view.show_validation_error() вызывается, возвращает False."""
        view = MockSystemView()
        # Невалидное значение fps (строка вместо числа)
        view.editor_values = {
            "camera.fps": "не_число",
        }
        presenter = _make_presenter(view=view)

        target_module = (
            "multiprocess_prototype.frontend.widgets.tabs.settings.system.presenter"
        )
        with patch(f"{target_module}.save_settings") as mock_save:
            result = presenter.save()

        # Должна вернуть False при ошибке валидации
        assert result is False
        # save_settings не должен был вызываться
        mock_save.assert_not_called()
        # view должен получить хотя бы одну ошибку
        assert len(view.validation_errors) >= 1

    def test_save_resets_dirty(self) -> None:
        """save() с валидными данными сбрасывает dirty-флаг в False."""
        view = MockSystemView()
        view.editor_values = {"camera.fps": 25}
        presenter = _make_presenter(view=view)

        # Сначала помечаем dirty вручную
        presenter._set_dirty(True)
        assert presenter.is_dirty() is True

        target_module = (
            "multiprocess_prototype.frontend.widgets.tabs.settings.system.presenter"
        )
        with patch(f"{target_module}.save_settings"):
            presenter.save()

        assert presenter.is_dirty() is False
        assert view.dirty_indicator is False

    def test_save_notifies_on_settings_saved(self) -> None:
        """save() вызывает on_settings_saved с dict-ом изменений."""
        view = MockSystemView()
        view.editor_values = {"camera.fps": 30}
        presenter = _make_presenter(view=view)

        saved_payloads: list[dict] = []
        presenter.on_settings_saved = lambda d: saved_payloads.append(d)

        target_module = (
            "multiprocess_prototype.frontend.widgets.tabs.settings.system.presenter"
        )
        with patch(f"{target_module}.save_settings"):
            presenter.save()

        assert len(saved_payloads) == 1
        # dict должен содержать секцию camera
        assert "camera" in saved_payloads[0]

    def test_save_clears_validation_errors_on_success(self) -> None:
        """save() при успехе вызывает view.clear_validation_errors()."""
        view = MockSystemView()
        view.editor_values = {"camera.fps": 25}
        presenter = _make_presenter(view=view)

        target_module = (
            "multiprocess_prototype.frontend.widgets.tabs.settings.system.presenter"
        )
        with patch(f"{target_module}.save_settings"):
            presenter.save()

        # clear_validation_errors должен быть вызван хотя бы один раз
        assert view.clear_called >= 1


class TestReload:
    """Тесты метода reload()."""

    def test_reload_resets_editors(self) -> None:
        """reload() вызывает view.set_editor_value() для каждого FieldInfo."""
        view = MockSystemView()
        presenter = _make_presenter(view=view)

        # Создаём фиктивный FieldInfo с известными значениями
        fi = SimpleNamespace(plugin_name="camera", field_name="fps")

        target_module = (
            "multiprocess_prototype.frontend.widgets.tabs.settings.system.presenter"
        )
        fresh_cfg = SystemConfig()
        # camera.fps по умолчанию = 25
        with (
            patch(f"{target_module}.load_settings", return_value=fresh_cfg),
            patch(f"{target_module}.schema_to_field_infos", return_value=[fi]),
            patch(f"{target_module}.save_settings"),
        ):
            # Сброс счётчика вызовов перед reload
            view.set_editor_calls.clear()
            presenter.reload()

        # После reload для нашего FieldInfo должен быть вызван set_editor_value
        keys_set = [key for key, _ in view.set_editor_calls]
        assert "camera.fps" in keys_set

    def test_reload_clears_validation_errors(self) -> None:
        """reload() вызывает view.clear_validation_errors()."""
        view = MockSystemView()
        presenter = _make_presenter(view=view)

        target_module = (
            "multiprocess_prototype.frontend.widgets.tabs.settings.system.presenter"
        )
        with (
            patch(f"{target_module}.load_settings", return_value=SystemConfig()),
            patch(f"{target_module}.schema_to_field_infos", return_value=[]),
        ):
            clear_before = view.clear_called
            presenter.reload()

        assert view.clear_called > clear_before

    def test_reload_resets_dirty_flag(self) -> None:
        """reload() сбрасывает dirty-флаг в False."""
        view = MockSystemView()
        presenter = _make_presenter(view=view)

        # Помечаем dirty
        presenter._set_dirty(True)
        assert presenter.is_dirty() is True

        target_module = (
            "multiprocess_prototype.frontend.widgets.tabs.settings.system.presenter"
        )
        with (
            patch(f"{target_module}.load_settings", return_value=SystemConfig()),
            patch(f"{target_module}.schema_to_field_infos", return_value=[]),
        ):
            presenter.reload()

        assert presenter.is_dirty() is False


class TestDirty:
    """Тесты dirty-флага."""

    def test_field_change_marks_dirty(self) -> None:
        """on_field_changed() устанавливает _dirty=True и вызывает on_dirty_changed."""
        view = MockSystemView()
        presenter = _make_presenter(view=view)

        dirty_calls: list[bool] = []
        presenter.on_dirty_changed = lambda v: dirty_calls.append(v)

        # Изначально clean
        assert presenter.is_dirty() is False

        presenter.on_field_changed()

        assert presenter.is_dirty() is True
        # on_dirty_changed вызван с True
        assert True in dirty_calls
        # view.set_dirty_indicator тоже обновлён
        assert view.dirty_indicator is True

    def test_initial_state_is_not_dirty(self) -> None:
        """Presenter создаётся без dirty-флага."""
        view = MockSystemView()
        presenter = _make_presenter(view=view)

        assert presenter.is_dirty() is False

    def test_on_dirty_changed_called_with_correct_value(self) -> None:
        """on_dirty_changed вызывается с правильным значением при смене dirty."""
        view = MockSystemView()
        presenter = _make_presenter(view=view)

        received: list[bool] = []
        presenter.on_dirty_changed = lambda v: received.append(v)

        # Устанавливаем True
        presenter._set_dirty(True)
        # Устанавливаем False
        presenter._set_dirty(False)

        assert received == [True, False]
