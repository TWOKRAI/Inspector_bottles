# multiprocess_prototype_v3/tests/integration/test_profile_switch_updates_registers.py
"""L2 integration-тест: переключение профиля через Presenter → RegistersManager обновляется.

Phase 2 — SettingsProfilePresenter как точка входа для пользовательских действий:
Apply, Save, Default. Реальные объекты (RegistersManager, SettingsProfileManager, YAML).

Сценарии:
1 — ProfileSwitch: apply "fast" (camera_count=4) → регистр обновлён, view.refresh вызван.
2 — ShmBudgetError: apply "overbudget" → ошибка в view, регистры НЕ изменились.
3 — SaveCurrentRegisters: save текущие регистры → YAML сохранён, round-trip проверка.
4 — DefaultRestoresRegisters: из "fast" → on_default_clicked → регистры вернулись к дефолту.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from multiprocess_prototype_v3.frontend.managers.settings_profile_manager import (
    SettingsProfileManager,
)
from multiprocess_prototype_v3.frontend.managers.settings_yaml_store import (
    default_profile_snapshot,
)
from multiprocess_prototype_v3.frontend.widgets.settings_profile_widget.model import (
    SettingsProfileModel,
)
from multiprocess_prototype_v3.frontend.widgets.settings_profile_widget.presenter import (
    SettingsProfilePresenter,
)
from multiprocess_prototype_v3.frontend.widgets.settings_profile_widget.profile_combo_model import (
    from_profile_manager,
    sync_current,
)
from multiprocess_prototype_v3.frontend.widgets.settings_profile_widget.schemas import (
    SettingsProfileTabConfig,
)
from multiprocess_prototype_v3.registers import create_registers
from multiprocess_prototype_v3.registers.constants import SETTINGS_REGISTER

# ---------------------------------------------------------------------------
# FakeView — заменяет Qt-виджет без зависимости от PyQt5
# ---------------------------------------------------------------------------


class FakeView:
    """Минимальная реализация SettingsProfilePanelViewProtocol (без Qt)."""

    def __init__(self, current_id: str = "default") -> None:
        self._current_id = current_id
        self.refresh_calls: int = 0
        self.errors: list[str] = []
        self.leaf_texts: dict[tuple[str, str], str] = {}

    def current_profile_id(self) -> str:
        return self._current_id

    def refresh_table_rows(self) -> None:
        self.refresh_calls += 1

    def set_leaf_value_text(self, group_id: str, field_id: str, text: str) -> None:
        self.leaf_texts[(group_id, field_id)] = text

    def show_error(self, msg: str) -> None:
        self.errors.append(msg)


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture()
def registers():
    """Реальный RegistersManager со всеми регистрами прототипа."""
    rm, _ = create_registers()
    return rm


@pytest.fixture()
def yaml_path(tmp_path: Path) -> str:
    """Временный путь к YAML-файлу профилей (изолированный на каждый тест)."""
    return str(tmp_path / "settings_profiles.yaml")


def _make_presenter(
    manager: SettingsProfileManager,
    rm,
    current_id: str,
) -> tuple[SettingsProfilePresenter, FakeView]:
    """Собрать Presenter + FakeView из реального менеджера и RegistersManager."""
    combo = from_profile_manager(manager)
    sync_current(combo, manager)
    model = SettingsProfileModel(
        ui=SettingsProfileTabConfig(),
        profile_manager=manager,
        rm=rm,
        combo_model=combo,
    )
    view = FakeView(current_id=current_id)
    presenter = SettingsProfilePresenter(view=view, model=model)
    return presenter, view


# ---------------------------------------------------------------------------
# Сценарий 1: ProfileSwitch — apply "fast" обновляет регистры
# ---------------------------------------------------------------------------


class TestScenario_ProfileSwitch:
    """Apply профиля "fast" (camera_count=4) через Presenter → регистр обновлён."""

    def test_apply_fast_updates_registers_and_refreshes_view(
        self, registers, yaml_path: str
    ) -> None:
        manager = SettingsProfileManager(data_path=yaml_path)
        manager.ensure_default_profile(registers)

        # Проверяем дефолтное значение
        reg_before = registers.get_register(SETTINGS_REGISTER)
        assert reg_before.camera_count == 1

        # Сохраняем профиль "fast" с camera_count=4
        manager.save_profile_snapshot(
            "fast",
            {**default_profile_snapshot(), "camera_count": 4},
        )

        # Собираем Presenter с FakeView, указывающим на "fast"
        presenter, view = _make_presenter(manager, registers, current_id="fast")

        # Применяем профиль
        result = presenter.on_apply_clicked()

        # Регистр обновился
        reg_after = registers.get_register(SETTINGS_REGISTER)
        assert reg_after.camera_count == 4, (
            f"Ожидали camera_count=4 после apply, получили {reg_after.camera_count}"
        )

        # Presenter вернул True (успех)
        assert result is True

        # View получил refresh
        assert view.refresh_calls == 1, (
            f"Ожидали 1 вызов refresh_table_rows, получили {view.refresh_calls}"
        )

        # Ошибок нет
        assert view.errors == []


# ---------------------------------------------------------------------------
# Сценарий 2: ShmBudgetError — регистры не меняются при превышении бюджета
# ---------------------------------------------------------------------------


class TestScenario_ShmBudgetErrorNoRegistersChange:
    """Overbudget-профиль: ошибка в view, регистры остались на default."""

    def test_overbudget_shows_error_and_preserves_registers(
        self, registers, yaml_path: str
    ) -> None:
        manager = SettingsProfileManager(data_path=yaml_path)
        manager.ensure_default_profile(registers)

        # Запоминаем исходное состояние
        reg_before = registers.get_register(SETTINGS_REGISTER)
        camera_before = reg_before.camera_count
        assert camera_before == 1

        # Профиль с превышением SHM-бюджета:
        # 8 камер * 3 ring-buffer * 1080p BGR = ~142 MB > budget 64 MB
        manager.save_profile_snapshot(
            "overbudget",
            {
                **default_profile_snapshot(),
                "camera_count": 8,
                "ring_buffer_size": 3,
                "shm_budget_mb": 64,
            },
        )

        presenter, view = _make_presenter(manager, registers, current_id="overbudget")

        # Применяем — должна быть ошибка
        result = presenter.on_apply_clicked()

        # Presenter вернул False
        assert result is False

        # View получил ошибку
        assert len(view.errors) > 0, "Ожидали хотя бы одну ошибку в view.errors"
        assert "budget" in view.errors[0].lower() or "SHM" in view.errors[0]

        # Регистры НЕ изменились
        reg_after = registers.get_register(SETTINGS_REGISTER)
        assert reg_after.camera_count == camera_before, (
            f"Регистры не должны меняться при ShmBudgetError: "
            f"ожидали camera_count={camera_before}, получили {reg_after.camera_count}"
        )

        # refresh НЕ вызван (профиль не применился)
        assert view.refresh_calls == 0


# ---------------------------------------------------------------------------
# Сценарий 3: SaveCurrentRegisters — save текущего состояния в YAML
# ---------------------------------------------------------------------------


class TestScenario_SaveCurrentRegistersToProfile:
    """switch → save → reload из нового менеджера → данные сохранены."""

    def test_save_persists_current_registers_to_yaml(
        self, registers, yaml_path: str
    ) -> None:
        manager = SettingsProfileManager(data_path=yaml_path)
        manager.ensure_default_profile(registers)

        # Сохраняем и переключаемся на "fast" (camera_count=4)
        manager.save_profile_snapshot(
            "fast",
            {**default_profile_snapshot(), "camera_count": 4},
        )
        manager.switch_profile("fast", registers)

        # Убеждаемся что регистр действительно переключился
        assert registers.get_register(SETTINGS_REGISTER).camera_count == 4

        # Собираем Presenter, имитируем нажатие "Сохранить"
        presenter, view = _make_presenter(manager, registers, current_id="fast")
        presenter.on_save_clicked()

        # Round-trip: новый менеджер с тем же YAML-файлом
        new_mgr = SettingsProfileManager(data_path=yaml_path)
        snapshot = new_mgr.get_profile_snapshot("fast")

        assert snapshot is not None, "Профиль 'fast' должен существовать в YAML"
        assert snapshot["camera_count"] == 4, (
            f"Ожидали camera_count=4 в сохранённом профиле, получили {snapshot['camera_count']}"
        )


# ---------------------------------------------------------------------------
# Сценарий 4: DefaultRestoresRegisters — возврат к дефолтному профилю
# ---------------------------------------------------------------------------


class TestScenario_DefaultRestoresRegisters:
    """Из "fast" (camera_count=4) → on_default_clicked → camera_count=1."""

    def test_default_restores_factory_values(
        self, registers, yaml_path: str
    ) -> None:
        manager = SettingsProfileManager(data_path=yaml_path)
        manager.ensure_default_profile(registers)

        # Переключаемся на "fast" (camera_count=4)
        manager.save_profile_snapshot(
            "fast",
            {**default_profile_snapshot(), "camera_count": 4},
        )
        manager.switch_profile("fast", registers)

        # Убеждаемся, что регистр изменился
        assert registers.get_register(SETTINGS_REGISTER).camera_count == 4

        # Presenter с любым current_id — on_default_clicked использует "default" hardcoded
        presenter, view = _make_presenter(manager, registers, current_id="default")

        result = presenter.on_default_clicked()

        # Регистры вернулись к дефолту
        reg_after = registers.get_register(SETTINGS_REGISTER)
        assert reg_after.camera_count == 1, (
            f"Ожидали camera_count=1 после on_default_clicked, получили {reg_after.camera_count}"
        )

        # Presenter вернул True
        assert result is True

        # View получил refresh
        assert view.refresh_calls == 1

        # Ошибок нет
        assert view.errors == []
