# -*- coding: utf-8 -*-
"""Приёмка вслепую (RED, до реализации): ``run_gate`` в схеме манифеста, в сборке и в рецептах.

Критерии (из брифа слепого tester'а, лента Ф 2.1):

  3. ``SystemConfig.run_gate: StrictBool = False``: ``"maybe"`` и ``1`` -> ``ValidationError``;
     ``True`` -> ``True``; без ключа -> ``False``. Грузится через tmp-yaml (рядом с боевым ``system.yaml``
     подмешивается ``user_overrides.yaml`` — свой каталог такого файла не содержит).
     ``SystemBuilder.build()`` кладёт ``sys_config.run_gate`` в ``launcher._orchestrator_config["run_gate"]``;
     для манифеста прототипа это значение из загруженного ``system.yaml`` (НЕ хардкод True/False — оно сменится).
  6. В каждом ``multiprocess_prototype/recipes/*.yaml`` каждый плагин ``ControlPanelPlugin`` имеет
     ``run_gated is False`` (литерал из yaml: ключ записан явно).

Состояние на ТЕКУЩЕМ коде — какие тесты красные:

  * КРАСНЫЕ все, кроме контролей. Поля ``run_gate`` нет в схеме (pydantic молча игнорирует лишний ключ
    -> ``"maybe"``/``1`` НЕ бросают, ``True`` даёт AttributeError), ключа нет в ``_orchestrator_config``,
    ``run_gated`` нет ни в одном рецепте.
  * ЗЕЛЁНЫЕ контроли: ``test_control_*`` (стенд рабочий: tmp-yaml грузится, ``build()`` собирается,
    рецепты читаются и ControlPanelPlugin в них найден).

Побочный эффект ``build()``: присваивает ``os.environ["INSPECTOR_LOG_DIR"]``. Фикстура ``_no_log_dir_env``
(по образцу ``backend_ctl/tests/test_harness_log_dir.py``) снимает env и ``_ENV_LOG_DIR_OVERRIDE`` и
ГАРАНТИРУЕТ откат: переменную сперва ставим, потом удаляем — тогда monkeypatch запомнит «не было» и удалит
то, что выставит ``build()``. Просто ``delenv`` на отсутствующей переменной ничего бы не запомнил.
Процессы не поднимаются.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from multiprocess_prototype.backend.config.schemas import SystemConfig, load_system_config

#: Корень репозитория: файл — multiprocess_prototype/backend/tests/<файл>.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_RECIPES_DIR = _REPO_ROOT / "multiprocess_prototype" / "recipes"

#: Путь класса плагина, чьи вхождения в рецептах судим (критерий 6).
_CONTROL_PANEL = "Services.control_panel.plugin.plugin.ControlPanelPlugin"

_ABSENT = object()


@pytest.fixture(autouse=True)
def _no_log_dir_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from multiprocess_prototype.backend import launch

    monkeypatch.setattr(launch, "_ENV_LOG_DIR_OVERRIDE", None)
    monkeypatch.setenv("MULTIPROCESS_LOG_DIR", "x")
    monkeypatch.setenv("INSPECTOR_LOG_DIR", "x")
    monkeypatch.delenv("MULTIPROCESS_LOG_DIR")
    monkeypatch.delenv("INSPECTOR_LOG_DIR")


def _load(tmp_path: Path, text: str) -> SystemConfig:
    """Загрузить system.yaml из своего (пустого) каталога: ``user_overrides.yaml`` рядом нет."""
    path = tmp_path / "system.yaml"
    path.write_text(text, encoding="utf-8")
    return load_system_config(path)


# ---------------------------------------------------------------------------
# Критерий 3а: схема
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ['"maybe"', "1", '"true"'], ids=["str-maybe", "int-1", "str-true"])
def test_run_gate_rejects_non_bool(tmp_path: Path, bad: str) -> None:
    """StrictBool: строка и число не приводятся к bool. Ошибка — именно про ``run_gate`` и именно bool-типа.

    Тип ошибки проверяем: иначе «ValidationError из-за чего-то постороннего» засчитался бы за зелёный.
    """
    with pytest.raises(ValidationError) as info:
        _load(tmp_path, f"run_gate: {bad}\n")

    errors = info.value.errors()
    assert [e["loc"] for e in errors] == [("run_gate",)], errors
    assert errors[0]["type"] == "bool_type", errors


def test_run_gate_true_is_kept(tmp_path: Path) -> None:
    assert _load(tmp_path, "run_gate: true\n").run_gate is True


def test_run_gate_false_is_kept(tmp_path: Path) -> None:
    assert _load(tmp_path, "run_gate: false\n").run_gate is False


def test_run_gate_defaults_to_false_without_the_key(tmp_path: Path) -> None:
    """Нет ключа -> ``False`` (литерал ``is False``: не ``None`` и не ``0``)."""
    assert _load(tmp_path, "system:\n  stop_timeout: 5.0\n").run_gate is False


def test_run_gate_assignment_is_validated_strictly(tmp_path: Path) -> None:
    """Присваивание полю тоже строгое: harness присваивает ``sys_config.run_gate`` после загрузки."""
    cfg = _load(tmp_path, "run_gate: false\n")

    with pytest.raises(ValidationError) as info:
        cfg.run_gate = 1  # type: ignore[assignment]

    # Тип ошибки: без поля pydantic тоже бросает ValidationError (no_such_attribute) — это не то, что судим.
    assert [(e["loc"], e["type"]) for e in info.value.errors()] == [(("run_gate",), "bool_type")]


def test_control_tmp_yaml_loads_and_keeps_other_keys(tmp_path: Path) -> None:
    """КОНТРОЛЬ (зелёный уже сейчас): стенд tmp-yaml рабочий, остальные ключи читаются."""
    cfg = _load(tmp_path, "system:\n  stop_timeout: 7.0\n")

    assert cfg.system.stop_timeout == 7.0


# ---------------------------------------------------------------------------
# Критерий 3б: SystemBuilder.build() кладёт run_gate в конфиг оркестратора
# ---------------------------------------------------------------------------


def _build(system_path: Path) -> Any:
    from multiprocess_prototype.backend.launch import SystemBuilder
    from multiprocess_prototype.main import DEFAULT_BLUEPRINT

    return SystemBuilder.from_topology_path(system_path, DEFAULT_BLUEPRINT).build()


@pytest.mark.parametrize("value", [True, False])
def test_build_puts_run_gate_into_orchestrator_config(tmp_path: Path, value: bool) -> None:
    """Значение из yaml -> ``_orchestrator_config["run_gate"]``, обе стороны (``is``, не truthiness)."""
    system = tmp_path / "system.yaml"
    system.write_text(f"run_gate: {'true' if value else 'false'}\n", encoding="utf-8")

    launcher = _build(system)

    assert launcher._orchestrator_config.get("run_gate", _ABSENT) is value, launcher._orchestrator_config.keys()


def test_build_default_run_gate_is_false_without_the_key(tmp_path: Path) -> None:
    """Ключ в yaml не задан -> в конфиге оркестратора ключ ЕСТЬ и равен ``False`` (а не отсутствует)."""
    system = tmp_path / "system.yaml"
    system.write_text("system:\n  stop_timeout: 5.0\n", encoding="utf-8")

    launcher = _build(system)

    assert launcher._orchestrator_config.get("run_gate", _ABSENT) is False


@pytest.mark.parametrize("value", [True, False])
def test_build_nested_sys_config_carries_the_same_run_gate(tmp_path: Path, value: bool) -> None:
    """Вложенный ``sys_config`` (его читает планировщик при горячей замене) несёт тот же ``run_gate``.

    yaml задаёт ключ явно, поэтому он есть и в сжатом дампе ``exclude_unset`` (см. отчёт: для НЕзаданного
    ключа поведение вложенного дампа брифом не определено).
    """
    system = tmp_path / "system.yaml"
    system.write_text(f"run_gate: {'true' if value else 'false'}\n", encoding="utf-8")

    launcher = _build(system)

    nested = launcher._orchestrator_config.get("sys_config")
    assert isinstance(nested, dict), "вложенный sys_config обязан быть dict (Dict at Boundary)"
    assert nested.get("run_gate", _ABSENT) is value, nested.keys()


def test_build_for_the_prototype_manifest_equals_the_loaded_config() -> None:
    """Манифест прототипа: значение в конфиге оркестратора = ``run_gate`` загруженного боевого ``system.yaml``.

    Ожидание — ЛИТЕРАЛ значения в боевом ``system.yaml``: производное от загрузки yaml (``load_system_config``)
    краснело бы только при расхождении ``build()`` с загрузкой, но не при смене самого ключа. Коммит B (``true``)
    меняет литерал ``False -> True``. Побочно проверяем тип: ``bool``, не ``None``.
    """
    from multiprocess_prototype.main import CONFIG_PATH

    expected = False  # system.yaml: run_gate: false (коммит A)

    launcher = _build(CONFIG_PATH)

    got = launcher._orchestrator_config.get("run_gate", _ABSENT)
    assert got is not _ABSENT, "ключ run_gate не попал в _orchestrator_config"
    assert isinstance(got, bool), got
    assert got is expected, (got, expected)


def test_build_for_the_prototype_manifest_nested_sys_config() -> None:
    """Вложенный ``sys_config`` для манифеста прототипа несёт тот же ключ.

    ВНИМАНИЕ (см. отчёт): вложенный дамп идёт с ``exclude_unset=True``; если боевой yaml ключ не задаёт, а
    реализация не пробрасывает его явно, тест краснеет «ложно». Брифом это место не определено.
    """
    from multiprocess_prototype.main import CONFIG_PATH

    expected = False  # system.yaml: run_gate: false (коммит A); в коммите B станет True

    launcher = _build(CONFIG_PATH)

    nested = launcher._orchestrator_config.get("sys_config")
    assert isinstance(nested, dict), "вложенный sys_config обязан быть dict"
    assert nested.get("run_gate", _ABSENT) is expected, nested.keys()


def test_control_build_assembles_and_has_orchestrator_config(tmp_path: Path) -> None:
    """КОНТРОЛЬ (зелёный уже сейчас): ``build()`` собирается, конфиг оркестратора — dict с известным ключом."""
    system = tmp_path / "system.yaml"
    system.write_text("system:\n  stop_timeout: 5.0\n", encoding="utf-8")

    launcher = _build(system)

    assert isinstance(launcher._orchestrator_config, dict)
    assert "pre_stop" in launcher._orchestrator_config


# ---------------------------------------------------------------------------
# Критерий 6: рецепты — у ControlPanelPlugin run_gated: false записан явно
# ---------------------------------------------------------------------------


def _walk(node: Any):
    """Все dict'и документа (рекурсивно, в списках тоже)."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _control_panel_entries(doc: Any) -> list[dict]:
    """dict'и-описания плагина, чей класс/путь — ControlPanelPlugin (по значению ключа класса/пути)."""
    return [d for d in _walk(doc) if _CONTROL_PANEL in (d.get("plugin_class"), d.get("class"), d.get("path"))]


def _run_gated_values(entry: dict) -> list[Any]:
    """``run_gated`` плагина: на уровне записи и/или в её ``config`` (обе раскладки встречаются в рецептах)."""
    values = []
    if "run_gated" in entry:
        values.append(entry["run_gated"])
    cfg = entry.get("config")
    if isinstance(cfg, dict) and "run_gated" in cfg:
        values.append(cfg["run_gated"])
    return values


def _recipe_files() -> list[Path]:
    return sorted(_RECIPES_DIR.glob("*.yaml"))


def _recipes_with_control_panel() -> list[Path]:
    out = []
    for path in _recipe_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if _control_panel_entries(doc):
            out.append(path)
    return out


def test_control_recipes_with_control_panel_are_found() -> None:
    """КОНТРОЛЬ (зелёный уже сейчас): обход находит ControlPanelPlugin в рецептах — иначе критерий ниже вакуумен.

    Инвентаризация ``git grep -F`` по рецептам на момент написания: pult_demo, phone_sketch, webcam_sketch.
    """
    names = sorted(p.name for p in _recipes_with_control_panel())

    assert {"pult_demo.yaml", "phone_sketch.yaml", "webcam_sketch.yaml"} <= set(names), names


@pytest.mark.parametrize("recipe", [p.name for p in _recipes_with_control_panel()])
def test_control_panel_plugin_has_run_gated_false(recipe: str) -> None:
    """Каждая запись ControlPanelPlugin рецепта несёт ``run_gated`` и он ровно ``False`` (не 0, не строка, не None)."""
    doc = yaml.safe_load((_RECIPES_DIR / recipe).read_text(encoding="utf-8"))
    entries = _control_panel_entries(doc)
    assert entries, f"{recipe}: ControlPanelPlugin не найден"

    for entry in entries:
        values = _run_gated_values(entry)
        assert values, f"{recipe}: у плагина {entry.get('plugin_name')!r} нет ключа run_gated"
        assert all(v is False for v in values), f"{recipe}: {entry.get('plugin_name')!r}: run_gated={values!r}"


# ---------------------------------------------------------------------------
# S3b2 (слепая приёмка): ключи работы PM ``run_autostart`` / ``run_stop_timeout_s`` / ``run_restart_grace_s``
# ---------------------------------------------------------------------------


def test_run_stop_timeout_s_int_is_coerced_to_float(tmp_path: Path) -> None:
    """Критерий 7: ``run_stop_timeout_s: 2`` -> ``2.0`` (число, не строка и не ``bool``)."""
    value = _load(tmp_path, "run_stop_timeout_s: 2\n").run_stop_timeout_s

    assert value == 2.0
    assert isinstance(value, float), type(value)


def test_run_restart_grace_s_int_is_coerced_to_float(tmp_path: Path) -> None:
    value = _load(tmp_path, "run_restart_grace_s: 45\n").run_restart_grace_s

    assert value == 45.0
    assert isinstance(value, float), type(value)


def test_run_keys_defaults_without_the_keys(tmp_path: Path) -> None:
    """Критерий 7: без ключей умолчания ``10.0`` / ``30.0`` / ``False``."""
    cfg = _load(tmp_path, "run_gate: false\n")

    assert cfg.run_stop_timeout_s == 10.0
    assert cfg.run_restart_grace_s == 30.0
    assert cfg.run_autostart is False


@pytest.mark.parametrize("key", ["run_stop_timeout_s", "run_restart_grace_s"])
@pytest.mark.parametrize(
    "bad",
    ["0", "-1", "true", '"5"', ".inf", ".nan"],
    ids=["zero", "neg", "bool", "str", "inf", "nan"],
)
def test_run_timeouts_reject_invalid_values(tmp_path: Path, key: str, bad: str) -> None:
    """Число > 0, конечное: ноль, минус, ``bool``, строка, inf, nan -> ``ValidationError`` про этот ключ."""
    with pytest.raises(ValidationError) as info:
        _load(tmp_path, f"{key}: {bad}\n")

    assert [e["loc"] for e in info.value.errors()] == [(key,)], info.value.errors()


@pytest.mark.parametrize("bad", ['"yes"', "1", '"true"'], ids=["str-yes", "int-1", "str-true"])
def test_run_autostart_rejects_non_bool(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValidationError) as info:
        _load(tmp_path, f"run_autostart: {bad}\n")

    errors = info.value.errors()
    assert [e["loc"] for e in errors] == [("run_autostart",)], errors
    assert errors[0]["type"] == "bool_type", errors


def test_build_omits_unset_run_keys(tmp_path: Path) -> None:
    """Критерий 8a: в yaml нет новых ключей -> в ``orchestrator_config`` их нет, ``run_gate`` есть и ``False``."""
    system = tmp_path / "system.yaml"
    system.write_text("run_gate: false\n", encoding="utf-8")

    cfg = _build(system)._orchestrator_config

    assert cfg["run_gate"] is False
    for key in ("run_autostart", "run_stop_timeout_s", "run_restart_grace_s"):
        assert key not in cfg, (key, cfg[key])


def test_build_puts_set_run_keys_into_orchestrator_config(tmp_path: Path) -> None:
    """Критерий 8b: заданные в yaml ключи попадают в ``orchestrator_config`` значениями нужного типа."""
    system = tmp_path / "system.yaml"
    system.write_text("run_restart_grace_s: 45\nrun_autostart: true\n", encoding="utf-8")

    cfg = _build(system)._orchestrator_config

    assert cfg.get("run_restart_grace_s", _ABSENT) == 45.0
    assert isinstance(cfg["run_restart_grace_s"], float), type(cfg["run_restart_grace_s"])
    assert cfg.get("run_autostart", _ABSENT) is True


def test_build_keeps_only_set_run_keys(tmp_path: Path) -> None:
    """Заданы два из трёх -> третий (``run_stop_timeout_s``) не появляется."""
    system = tmp_path / "system.yaml"
    system.write_text("run_restart_grace_s: 45\nrun_autostart: true\n", encoding="utf-8")

    cfg = _build(system)._orchestrator_config

    assert "run_stop_timeout_s" not in cfg
