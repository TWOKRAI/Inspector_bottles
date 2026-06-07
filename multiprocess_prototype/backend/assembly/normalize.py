"""normalize — app-glue нормализация blueprint перед сборкой.

Единственное место app-специфики сборки: ``SystemConfig`` per-category defaults.
Общий для boot и switch.

- ``normalize_blueprint`` — перенос ``_merge_defaults`` из ``launch.py``:
  in-place мутация + возврат (паритет дороги A; задокументировано).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from multiprocess_prototype.backend.config.schemas import SystemConfig


def normalize_blueprint(
    bp_dict: dict[str, Any],
    sys_config: "SystemConfig",
) -> dict[str, Any]:
    """Применить per-category defaults из SystemConfig к plugin-конфигам topology.

    Для каждого плагина: ``defaults[category] | plugin_inline_config``.
    Inline-значения имеют приоритет (override).

    .. warning::
        **Мутирует ``bp_dict`` in-place** (и возвращает его) — паритет с оригинальным
        ``_merge_defaults`` из ``launch.py``.  При необходимости передавайте копию:
        ``normalize_blueprint(copy.deepcopy(bp_dict), sys_config)``.

    Args:
        bp_dict: Blueprint dict (processes + wires + ...).
        sys_config: Системный конфиг с defaults для категорий плагинов.

    Returns:
        Тот же ``bp_dict`` с применёнными defaults.
    """
    for proc in bp_dict.get("processes", []):
        for plugin in proc.get("plugins", []):
            category = plugin.get("category", "")
            category_defaults = sys_config.defaults_for_category(category)
            if category_defaults:
                merged = {**category_defaults, **plugin}
                plugin.clear()
                plugin.update(merged)
    return bp_dict
