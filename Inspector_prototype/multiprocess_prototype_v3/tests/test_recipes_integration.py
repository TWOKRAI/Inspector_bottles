# multiprocess_prototype_v3/tests/test_recipes_integration.py
"""L2 integration-тест: ячейка → RegistersManager → IPC-метаданные (Phase 1, Task 1.6).

Критерий приёмки фазы (из phase_1_tasks.md):
  редактирование ячейки через presenter → rm.set_field_value →
  значение отражается в RegistersManager и видно, на какой канал IPC оно должно уйти.

Тест использует настоящий RegistersManager (create_registers) + FakeRecipeManager
с реальным YAML через tempfile. PyQt5 требуется (presenter импортирует frontend_module);
в dev-venv без PyQt5 тест пропускается.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PyQt5", reason="presenter импортирует frontend_module.interfaces (тянет PyQt5)")

from multiprocess_prototype_v3.frontend.managers.access_context import AccessContext  # noqa: E402
from multiprocess_prototype_v3.frontend.managers.recipe_manager import RecipeManager  # noqa: E402
from multiprocess_prototype_v3.frontend.widgets.recipes_widget.model import (
    RegisterRecipeModel,  # noqa: E402
)
from multiprocess_prototype_v3.frontend.widgets.recipes_widget.presenter import (  # noqa: E402
    RegisterRecipePresenter,
)
from multiprocess_prototype_v3.frontend.widgets.settings_recipe_widget.schemas import (  # noqa: E402
    RecipesTabConfig,
)
from multiprocess_prototype_v3.registers import (  # noqa: E402
    CAMERA_REGISTER,
    PROCESSOR_REGISTER,
    SETTINGS_REGISTER,
    create_registers,
)


class _FakeView:
    """Минимальный view-стаб: хранит slot и текстовые откаты ячеек."""

    def __init__(self, slot: int = 0) -> None:
        self.slot_value = slot
        self.refreshed = 0
        self.leaf_texts: list[tuple[str, str, str]] = []

    def parse_slot(self) -> int:
        return self.slot_value

    def refresh_table_rows(self) -> None:
        self.refreshed += 1

    def set_leaf_value_text(self, group_id: str, field_id: str, text: str) -> None:
        self.leaf_texts.append((group_id, field_id, text))


@pytest.fixture()
def yaml_path(tmp_path: Path) -> Path:
    return tmp_path / "recipes.yaml"


@pytest.fixture()
def registers_manager():
    rm, _ = create_registers()
    return rm


@pytest.fixture()
def recipe_manager(yaml_path: Path) -> RecipeManager:
    return RecipeManager(data_path=str(yaml_path), app_recipes_path=str(yaml_path.parent / "app.yaml"))


@pytest.fixture()
def presenter_factory():
    def _factory(rm, mgr, view_slot: int = 0) -> tuple[RegisterRecipePresenter, _FakeView]:
        model = RegisterRecipeModel(
            rm=rm,
            recipe_manager=mgr,
            access_ctx=AccessContext.default(),
            ui=RecipesTabConfig(),
        )
        view = _FakeView(slot=view_slot)
        return RegisterRecipePresenter(view=view, model=model), view

    return _factory


class TestCellToRegister:
    def test_settings_int_field_updated_via_cell_edit(
        self, registers_manager, recipe_manager, presenter_factory
    ) -> None:
        """Редактирование camera_count в ячейке → значение меняется в реальном регистре."""
        presenter, _ = presenter_factory(registers_manager, recipe_manager)

        # field_id в build_recipe_rows: "{register_name}.{field_name}".
        field_id = f"{SETTINGS_REGISTER}.camera_count"
        before = registers_manager.get_register(SETTINGS_REGISTER).camera_count
        assert before == 1

        presenter.on_leaf_value_changed(SETTINGS_REGISTER, field_id, "value", "4")

        after = registers_manager.get_register(SETTINGS_REGISTER).camera_count
        assert after == 4
        assert isinstance(after, int)

    def test_invalid_value_rolls_back_cell(
        self, registers_manager, recipe_manager, presenter_factory
    ) -> None:
        """Ввод ниже min=1 → set_field_value падает, presenter пишет прежнее значение в ячейку."""
        presenter, view = presenter_factory(registers_manager, recipe_manager)

        field_id = f"{SETTINGS_REGISTER}.camera_count"
        before = registers_manager.get_register(SETTINGS_REGISTER).camera_count
        assert before == 1

        presenter.on_leaf_value_changed(SETTINGS_REGISTER, field_id, "value", "0")

        # Значение в регистре не изменилось (валидатор min=1 отбил).
        assert registers_manager.get_register(SETTINGS_REGISTER).camera_count == 1
        # Presenter вернул старое значение (1) обратно в текст ячейки.
        assert any("1" in text for _, _, text in view.leaf_texts)


class TestIpcMetadataPresent:
    """Phase 0/1 регистры имеют FieldRouting.channel — готовность к IPC propagation в Phase 2+."""

    def test_settings_field_carries_routing_channel(
        self, registers_manager
    ) -> None:
        reg = registers_manager.get_register(SETTINGS_REGISTER)
        meta = type(reg).model_fields["camera_count"].metadata
        # FieldMeta объект среди metadata → у него routing.channel == "control_settings".
        routing_channels = [
            getattr(m, "routing", None).channel
            for m in meta
            if getattr(m, "routing", None) is not None
        ]
        assert "control_settings" in routing_channels

    def test_camera_field_uses_control_camera_channel(
        self, registers_manager
    ) -> None:
        reg = registers_manager.get_register(CAMERA_REGISTER)
        meta = type(reg).model_fields["fps"].metadata
        routing_channels = [
            getattr(m, "routing", None).channel
            for m in meta
            if getattr(m, "routing", None) is not None
        ]
        assert "control_camera" in routing_channels


class TestSlotSwitchLoadsRecipe:
    def test_save_then_load_slot_restores_values(
        self, registers_manager, recipe_manager, presenter_factory
    ) -> None:
        """Записать рецепт в слот 1, изменить регистры, загрузить слот 1 → значения возвращаются."""
        presenter, view = presenter_factory(registers_manager, recipe_manager, view_slot=1)

        # Задаём «эталонные» значения в регистрах.
        registers_manager.set_field_value(SETTINGS_REGISTER, "camera_count", 3)
        registers_manager.set_field_value(PROCESSOR_REGISTER, "color_min_area", 750)

        # Сохраняем слот 1.
        presenter.on_save_clicked()
        assert recipe_manager.get_slot("1") is not None

        # Меняем регистры «мимо» слота.
        registers_manager.set_field_value(SETTINGS_REGISTER, "camera_count", 8)
        registers_manager.set_field_value(PROCESSOR_REGISTER, "color_min_area", 1234)
        assert registers_manager.get_register(SETTINGS_REGISTER).camera_count == 8

        # Загрузка слота 1 должна восстановить оригинал.
        presenter.on_load_clicked()
        assert registers_manager.get_register(SETTINGS_REGISTER).camera_count == 3
        assert registers_manager.get_register(PROCESSOR_REGISTER).color_min_area == 750
        assert view.refreshed >= 1


class TestComboModelFromRecipeManager:
    """RecipeSlotComboModel.from_manager должен корректно работать с реальным RecipeManager."""

    def test_uses_list_slots_after_saves(
        self, registers_manager, recipe_manager, presenter_factory
    ) -> None:
        from multiprocess_prototype_v3.frontend.widgets.recipes_widget import RecipeSlotComboModel

        # Сохраняем 2 слота через presenter.
        presenter_a, _ = presenter_factory(registers_manager, recipe_manager, view_slot=1)
        presenter_a.on_save_clicked()
        presenter_b, _ = presenter_factory(registers_manager, recipe_manager, view_slot=2)
        presenter_b.on_save_clicked()

        model = RecipeSlotComboModel.from_manager(recipe_manager, 0, 5)
        # Реальный RecipeManager.list_slots() возвращает ["1", "2"] в порядке записи.
        assert set(model.slots) == {"1", "2"}
