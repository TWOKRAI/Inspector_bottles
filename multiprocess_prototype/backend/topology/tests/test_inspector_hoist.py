"""Тесты подъёма ``inspector`` из ``metadata`` в прямой ключ процесса.

GUI при сохранении рецепта кладёт ``inspector`` под ``metadata`` (домен-entity
``Process`` не имеет поля ``inspector``). Бэкенд читает ``ProcessConfig.inspector``
(прямой ключ) — ``unwrap_recipe`` должен поднять его обратно, иначе join МОЛЧА
выключается (fanin) и multi-input узлы (overlay_draw/center_crop) не сливают входы.

См. memory project_recipe_inspector_join_key.
"""

from multiprocess_prototype.backend.launch import unwrap_recipe


def _join_block() -> dict:
    return {"mode": "join", "inputs": ["frame", "overlay"], "primary": "frame"}


def test_recipe_hoists_inspector_from_metadata():
    """Рецепт (вложенный blueprint): inspector под metadata → прямой ключ."""
    recipe = {
        "blueprint": {
            "processes": [
                {"process_name": "draw", "metadata": {"inspector": _join_block()}},
            ],
        },
    }
    bp = unwrap_recipe(recipe)
    proc = bp["processes"][0]
    assert proc["inspector"]["mode"] == "join"


def test_raw_topology_hoists_inspector_from_metadata():
    """Сырая topology (processes на верхнем уровне): тоже поднимаем."""
    topo = {
        "processes": [
            {"process_name": "crop", "metadata": {"inspector": _join_block()}},
        ],
    }
    out = unwrap_recipe(topo)
    assert out["processes"][0]["inspector"]["mode"] == "join"


def test_direct_inspector_not_overwritten():
    """Если inspector уже прямой ключ — metadata не перетирает его."""
    recipe = {
        "blueprint": {
            "processes": [
                {
                    "process_name": "draw",
                    "inspector": {"mode": "join", "primary": "frame"},
                    "metadata": {"inspector": {"mode": "fanin"}},
                },
            ],
        },
    }
    bp = unwrap_recipe(recipe)
    assert bp["processes"][0]["inspector"]["mode"] == "join"


def test_no_inspector_no_key_added():
    """Процесс без inspector в metadata — ключ не появляется."""
    recipe = {"blueprint": {"processes": [{"process_name": "roi", "metadata": {}}]}}
    bp = unwrap_recipe(recipe)
    assert "inspector" not in bp["processes"][0]
