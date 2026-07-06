"""test_devices_sync.py — тесты извлечения и инжекта устройств рецепта.

Проверяют:
1. extract_recipe_devices: есть / нет / битые записи.
2. inject_recipe_devices: инжект в merged-топологию (dict-уровень).
3. Активация: upsert_devices_fn вызывается ДО apply_topology_fn.

Refs: plans/device-hub.md Фаза 3, Р11
"""

from __future__ import annotations

from unittest.mock import MagicMock


from multiprocess_prototype.recipes.devices_sync import (
    extract_recipe_devices,
    inject_recipe_devices,
)


# ------------------------------------------------------------------ #
# extract_recipe_devices
# ------------------------------------------------------------------ #


def test_extract_valid_devices() -> None:
    """Извлечение корректных записей devices."""
    raw = {
        "name": "test_recipe",
        "devices": [
            {"id": "robot_main", "kind": "robot", "transport": {"type": "tcp"}},
            {"id": "vfd_belt", "kind": "vfd", "transport": {"type": "bridge"}},
        ],
        "blueprint": {"processes": []},
    }
    result = extract_recipe_devices(raw)
    assert len(result) == 2
    assert result[0]["id"] == "robot_main"
    assert result[1]["id"] == "vfd_belt"


def test_extract_no_devices_section() -> None:
    """Нет секции devices → пустой список."""
    raw = {"name": "test", "blueprint": {"processes": []}}
    assert extract_recipe_devices(raw) == []


def test_extract_devices_not_list() -> None:
    """devices не list → пустой список."""
    raw = {"devices": "invalid", "blueprint": {"processes": []}}
    assert extract_recipe_devices(raw) == []


def test_extract_skips_malformed_entries() -> None:
    """Битые записи (не dict / нет id/kind) пропускаются."""
    raw = {
        "devices": [
            {"id": "good", "kind": "robot"},  # OK
            "not_a_dict",  # битая
            {"id": "no_kind"},  # нет kind
            {"kind": "no_id"},  # нет id
            {"id": "also_good", "kind": "vfd"},  # OK
        ],
    }
    result = extract_recipe_devices(raw)
    assert len(result) == 2
    assert result[0]["id"] == "good"
    assert result[1]["id"] == "also_good"


def test_extract_empty_devices_list() -> None:
    """Пустой список devices → пустой результат."""
    raw = {"devices": []}
    assert extract_recipe_devices(raw) == []


# ------------------------------------------------------------------ #
# inject_recipe_devices
# ------------------------------------------------------------------ #


def _make_merged_topology(*, with_devices_process: bool = True) -> dict:
    """Создать merged-топологию с процессом devices (или без)."""
    procs = []
    if with_devices_process:
        procs.append(
            {
                "process_name": "devices",
                "plugins": [
                    {
                        "plugin_name": "device_hub",
                        "plugin_class": "Plugins.hub.device_hub.plugin.DeviceHubPlugin",
                        "registry_path": "data/devices.yaml",
                    }
                ],
            }
        )
    procs.append(
        {
            "process_name": "gui",
            "plugins": [{"plugin_name": "gui_main"}],
        }
    )
    return {"name": "test", "processes": procs, "wires": []}


def test_inject_devices_into_device_hub() -> None:
    """recipe_devices и recipe_origin инжектируются в конфиг device_hub."""
    merged = _make_merged_topology()
    devices = [{"id": "robot_main", "kind": "robot"}]
    result = inject_recipe_devices(merged, devices, "my_recipe")

    # Оригинал не мутирован
    hub_cfg = merged["processes"][0]["plugins"][0]
    assert "recipe_devices" not in hub_cfg

    # Результат содержит инжект
    hub_cfg_result = result["processes"][0]["plugins"][0]
    assert hub_cfg_result["recipe_devices"] == devices
    assert hub_cfg_result["recipe_origin"] == "recipe:my_recipe"


def test_inject_empty_devices_returns_same() -> None:
    """Пустой список devices → топология без изменений."""
    merged = _make_merged_topology()
    result = inject_recipe_devices(merged, [], "test")
    assert result is merged  # тот же объект, без deepcopy


def test_inject_no_devices_process() -> None:
    """Нет процесса devices → warning, топология без изменений."""
    merged = _make_merged_topology(with_devices_process=False)
    devices = [{"id": "robot_main", "kind": "robot"}]
    result = inject_recipe_devices(merged, devices, "test")
    # Должен вернуть копию без изменений
    for proc in result["processes"]:
        for pl in proc.get("plugins", []):
            assert "recipe_devices" not in pl


# ------------------------------------------------------------------ #
# Тест активации: upsert вызывается ДО apply_topology
# ------------------------------------------------------------------ #


def test_presenter_upsert_before_apply() -> None:
    """При активации рецепта upsert_devices_fn вызывается ДО apply_topology_fn."""
    from multiprocess_prototype.frontend.widgets.tabs.recipes.presenter import RecipesPresenter

    call_order: list[str] = []

    class FakeStore:
        def list(self):
            return ["test_recipe"]

        def get_active(self):
            return None

        def read_raw(self, slug):
            return {
                "name": slug,
                "version": 4,
                "devices": [{"id": "robot_main", "kind": "robot"}],
                "blueprint": {"processes": [], "wires": []},
            }

        def set_active(self, slug):
            return True

    def fake_upsert(devices, slug):
        call_order.append("upsert")

    def fake_apply(source, on_result):
        # async-контракт Task 2.1: результат доставляется в on_result
        call_order.append("apply")
        on_result({"success": True})

    view = MagicMock()
    view.confirm_delete.return_value = True

    presenter = RecipesPresenter(
        store=FakeStore(),
        view=view,
        apply_topology_fn=fake_apply,
        upsert_devices_fn=fake_upsert,
    )
    presenter.on_set_active("test_recipe")

    assert call_order == ["upsert", "apply"], f"Порядок вызовов: {call_order}"


def test_presenter_no_upsert_without_devices() -> None:
    """Рецепт без секции devices → upsert_devices_fn не вызывается."""
    from multiprocess_prototype.frontend.widgets.tabs.recipes.presenter import RecipesPresenter

    call_order: list[str] = []

    class FakeStore:
        def list(self):
            return ["simple"]

        def get_active(self):
            return None

        def read_raw(self, slug):
            return {
                "name": slug,
                "version": 3,
                "blueprint": {"processes": [], "wires": []},
            }

        def set_active(self, slug):
            return True

    def fake_upsert(devices, slug):
        call_order.append("upsert")

    def fake_apply(source, on_result):
        # async-контракт Task 2.1: результат доставляется в on_result
        call_order.append("apply")
        on_result({"success": True})

    view = MagicMock()
    presenter = RecipesPresenter(
        store=FakeStore(),
        view=view,
        apply_topology_fn=fake_apply,
        upsert_devices_fn=fake_upsert,
    )
    presenter.on_set_active("simple")

    # upsert НЕ вызван (нет devices), apply вызван
    assert call_order == ["apply"], f"Порядок вызовов: {call_order}"
