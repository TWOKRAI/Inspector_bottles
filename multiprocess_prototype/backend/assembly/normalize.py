"""normalize — app-glue нормализация blueprint перед сборкой.

Единственное место app-специфики сборки: ``SystemConfig`` per-category defaults.
Общий для boot и switch.

- ``normalize_blueprint`` — перенос ``_merge_defaults`` из ``launch.py``:
  in-place мутация + возврат (паритет дороги A; задокументировано).
- ``build_proc_dicts`` — связка для Phase 2 switch: нормализация + assembler
  в одном вызове.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from multiprocess_framework.modules.process_module.configs import expand_observability

from .assembler import BlueprintAssembler

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


def build_proc_dicts(
    bp_dict: dict[str, Any],
    sys_config: "SystemConfig",
) -> dict[str, dict[str, Any]]:
    """Нормализация + сборка в одном вызове (связка для Phase 2 switch).

    Строит ``BlueprintAssembler`` с observability overlay и log_dir из
    ``sys_config``, нормализует blueprint и зовёт ``assemble``.

    Args:
        bp_dict: Blueprint dict (будет мутирован — нормализация in-place).
        sys_config: Системный конфиг.

    Returns:
        ``{process_name: normalized_proc_dict}``.
    """
    obs_overlay = expand_observability(sys_config.observability.model_dump())
    log_dir = sys_config.system.log_dir or "logs"

    assembler = BlueprintAssembler(
        observability_dict=obs_overlay,
        log_dir=log_dir,
    )
    return assembler.assemble(normalize_blueprint(bp_dict, sys_config))
