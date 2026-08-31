# -*- coding: utf-8 -*-
"""S-23, шаг (б): презентационный патч живёт и на ГОРЯЧЕЙ пересборке.

Boot накладывает overlay на слитую топологию (`SystemBuilder.from_manifest`), а
горячая замена рецепта собирает топологию заново — из одного лишь рецепта. Рецепт
объявляет `gui` в дренирующем воплощении (`HeadlessGuiProcess`), поэтому без
патча switch раздал бы пересобранному процессу headless-класс.

Наблюдаемое следствие сегодня — не смерть окна: `gui` объявлен `protected: true`
во всех 14 рецептах, что его объявляют, поэтому switch его физически не трогает,
и расхождение лишь вечно горит в сигнале конфликта protected (живьём: путь
`class` в голосе планировщика). Но `protected` — свойство рецепта, а не закон:
снятие галочки превращает вечный ложный сигнал в молча умирающее окно. Патч
закрывает оба исхода одним местом.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from multiprocess_prototype.backend.config.schemas import load_system_config
from multiprocess_prototype.backend.orchestrator_hooks import configure_topology_engine

from ._orchestrator_stub_contract import assert_stub_speaks_the_real_class_surface

PROJECT_ROOT = Path(__file__).resolve().parents[3]
QT_CLASS = "multiprocess_prototype.frontend.process.GuiProcess"
HEADLESS_CLASS = "multiprocess_prototype.frontend.headless_process.HeadlessGuiProcess"

#: Рецепт из двух процессов без проводов — валиден для ассемблера и не тянет железо.
RECIPE: dict[str, Any] = {
    "name": "_overlay_probe",
    "version": 3,
    "blueprint": {
        "name": "_overlay_probe",
        "processes": [
            {
                "process_name": "gui",
                "plugins": [],
                "workers": [],
                "process_class": HEADLESS_CLASS,
                "protected": True,
                "metadata": {},
            },
        ],
        "wires": [],
        "displays": [],
    },
    "displays": [],
}


class _TopologyManagerStub:
    def __init__(self) -> None:
        self.configured: dict[str, Any] = {}

    def configure(self, **kwargs: Any) -> None:
        self.configured = kwargs


class _OrchestratorStub:
    """Минимум, который читает ``configure_topology_engine``."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self.logger_manager = None
        self.error_manager = None
        self.stats_manager = None
        self._topology_manager = _TopologyManagerStub()
        self._full_replace_planner = None
        self.infos: list[str] = []

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def _log_info(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.infos.append(message)

    def _get_protected_names(self) -> set[str]:
        return set()

    def _topology_current_names(self) -> set[str]:
        return set()

    def live_process_config(self, name: str) -> dict | None:
        return None


def _sys_config_dict() -> dict:
    return load_system_config(
        PROJECT_ROOT / "multiprocess_prototype" / "backend" / "config" / "system.yaml"
    ).model_dump()


def _overlay() -> dict:
    raw = yaml.safe_load(
        (PROJECT_ROOT / "multiprocess_prototype" / "frontend" / "presentation.yaml").read_text(encoding="utf-8")
    )
    return raw


def _gui_class_after_hot_rebuild(overlay: dict | None) -> str:
    orch = _OrchestratorStub({"sys_config": _sys_config_dict(), "presentation_overlay": overlay})
    configure_topology_engine(orch)
    proc_dicts = orch._full_replace_planner._proc_dicts_fn(RECIPE)
    return proc_dicts["gui"]["class"]


def test_hot_rebuild_with_overlay_keeps_the_qt_class() -> None:
    """Патч задан → пересобранный `gui` едет Qt-классом, а не тем, что в рецепте."""
    assert _gui_class_after_hot_rebuild(_overlay()) == QT_CLASS


def test_hot_rebuild_without_overlay_keeps_the_recipe_class() -> None:
    """Патча нет (бэкенд-вход, --headless) → класс рецепта. Патч не появляется
    из ниоткуда: контроль к предыдущему тесту, иначе тот был бы согласен с любым
    поведением, лишь бы класс оказался Qt-шным.
    """
    assert _gui_class_after_hot_rebuild(None) == HEADLESS_CLASS


def test_overlay_reaches_the_builder_through_the_real_front_entry_switch(monkeypatch) -> None:
    """Провод целиком, при ВКЛЮЧЁННОЙ презентации — так, как её включает фронт-вход.

    ``app.yaml`` ключа ``presentation`` не содержит вовсе (находка S-22), поэтому
    проверка «как есть» сравнивала бы None с None и была бы согласна с любой
    реализацией. Презентацию включает env ``INSPECTOR_PRESENTATION``, который
    выставляет ``frontend/run.py`` — включаем её тем же способом.
    """
    from multiprocess_prototype.backend.config.manifest import PRESENTATION_ENV, load_manifest
    from multiprocess_prototype.backend.launch import SystemBuilder

    monkeypatch.setenv(
        PRESENTATION_ENV,
        str(PROJECT_ROOT / "multiprocess_prototype" / "frontend" / "presentation.yaml"),
    )
    app = load_manifest(PROJECT_ROOT / "multiprocess_prototype" / "app.yaml")
    assert app.presentation is not None, "предусловие теста: env обязан включить презентацию"

    with_pres = SystemBuilder.from_manifest(app, include_presentation=True)
    headless = SystemBuilder.from_manifest(app, include_presentation=False)

    assert with_pres._presentation_overlay is not None
    assert with_pres._presentation_overlay.get("processes"), "патч обязан нести процессы"
    # headless-флаг перебивает презентацию — патч не едет и в оркестратор.
    assert headless._presentation_overlay is None


def test_a_plugin_brought_by_the_patch_arrives_with_its_category_defaults() -> None:
    """Патч может принести не только класс, но и ПЛАГИН — и тот обязан доехать
    собранным, с дефолтами своей категории, а не голым объявлением.

    Тест НЕ про порядок «патч → normalize», хотя писался ради него: инъекция,
    переворачивающая порядок, не убивает ни одного теста, потому что ассемблер
    добирает дефолты плагина сам (разница 3 ключа против 8 видна на промежуточном
    blueprint и исчезает к proc_dict). Сторожит он ровно то, что названо в имени,
    и умирает вместе с «патч не наложен» — этого достаточно.
    """
    overlay_with_plugin = {
        "processes": [
            {
                "process_name": "gui",
                "process_class": QT_CLASS,
                "plugins": [
                    {
                        "plugin_class": "Plugins.sources.capture.plugin.CapturePlugin",
                        "plugin_name": "capture",
                        "category": "source",
                    }
                ],
            }
        ]
    }

    orch = _OrchestratorStub({"sys_config": _sys_config_dict(), "presentation_overlay": overlay_with_plugin})
    configure_topology_engine(orch)
    proc_dicts = orch._full_replace_planner._proc_dicts_fn(RECIPE)

    plugin = proc_dicts["gui"]["config"]["plugins"][0]
    assert plugin["plugin_name"] == "capture"
    assert plugin.get("fps") == 25, (
        "плагин, принесённый патчем, обязан пройти через normalize и получить "
        f"per-category defaults категории source — получено {plugin!r}"
    )


def test_hot_rebuild_does_not_mutate_the_stored_overlay() -> None:
    """Хранимый патч переживает сборку неизменным.

    ``apply_presentation_overlay`` сливает пополям поверхностно, а
    ``normalize_blueprint`` мутирует in-place — значит без копии список плагинов
    патча обогащался бы per-category defaults прямо в конфиге оркестратора и на
    следующий switch приезжал бы не тем, чем объявлен. Измерено на живом коде до
    правки: запись плагина в патче вырастала с 3 ключей до 8.

    Тот же дефект отравлял и соседний тест порядка: общий изменяемый патч делал
    его зелёным независимо от порядка — инъекция «перевернуть порядок» не убивала
    никого, пока патч копироваться не начал.
    """
    import copy as _copy

    overlay = {
        "processes": [
            {
                "process_name": "gui",
                "process_class": QT_CLASS,
                "plugins": [
                    {
                        "plugin_class": "Plugins.sources.capture.plugin.CapturePlugin",
                        "plugin_name": "capture",
                        "category": "source",
                    }
                ],
            }
        ]
    }
    snapshot = _copy.deepcopy(overlay)

    orch = _OrchestratorStub({"sys_config": _sys_config_dict(), "presentation_overlay": overlay})
    configure_topology_engine(orch)
    orch._full_replace_planner._proc_dicts_fn(RECIPE)
    orch._full_replace_planner._proc_dicts_fn(RECIPE)  # второй switch — на нём и вылезало

    assert overlay == snapshot, "патч в конфиге оркестратора не имеет права обогащаться сборкой"


# ---------------------------------------------------------------------------
# S-29 — дублёр оркестратора обязан совпадать по именам с настоящим классом
# ---------------------------------------------------------------------------


def test_the_stub_orchestrator_speaks_the_real_class_surface() -> None:
    """`_OrchestratorStub` этого файла обязан совпадать по именам с НАСТОЯЩИМ
    `GenericProcessManagerApp` — иначе переименование в проде остаётся
    незамеченным.

    Этот файл проверяет, что презентационный патч переживает горячую пересборку
    (класс `gui`, принесённый плагин, отсутствие мутации хранимого overlay) — но
    каждый тест гоняет `configure_topology_engine` против `_OrchestratorStub`,
    объявленного выше, и ни разу не заглядывает в оркестратор по имени.
    Измерено (S-29, 2026-08-18): переименование `live_process_config` в
    `process_manager_process.py` не покрасило ни одного теста этого файла.
    Общая проверка — `_orchestrator_stub_contract.py` (S-26).
    """
    assert_stub_speaks_the_real_class_surface(_OrchestratorStub)
