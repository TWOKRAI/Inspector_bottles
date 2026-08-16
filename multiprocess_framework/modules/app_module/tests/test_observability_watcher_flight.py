# -*- coding: utf-8 -*-
"""Ф5 (5.1) — оба файловых watcher'а оркестратора несут рекордер дампов.

Сторож-близнец к ``test_observability_watcher_events.py``, и живёт он ЗДЕСЬ по
той же причине: первая редакция такого стража на задаче 4.1 стояла в
``process_module/tests/``, импортировала оттуда ``GenericProcessManagerApp`` и
уронила контракт слоёв (``test_no_other_framework_module_imports_app_module``) —
``process_module`` слоем НИЖЕ ``app_module``. Сторож про оркестратор принадлежит
оркестратору.

Проверяется ПРОДОВЫЙ вход — ``_start_observability_watcher`` самого приложения, а
не фабрика ``make_observability_on_reload`` внутри него: страж на фабрике зелен и
тогда, когда продовая сборка забыла передать рекордер. Именно этот зазор дал
**ноль красных** на инъекциях И8b и И8c — обе строки снимались по одной, и весь
корпус задачи оставался зелёным.

**Два теста, а не один на оба watcher'а.** В исходнике это РАЗНЫЕ вызовы, и
забыть аргумент можно в любом; сторож, краснеющий от обеих инъекций сразу, не
отвечает на вопрос «какая из двух дорог сломана». Широкий красный так же
бесполезен, как зелёный.
"""

from __future__ import annotations

from pathlib import Path

from multiprocess_framework.modules.app_module.orchestrator import GenericProcessManagerApp
from multiprocess_framework.modules.config_module.core.config import Config
from multiprocess_framework.modules.process_module.managers.observability_flight import FlightRecorder

#: Стартовая политика: ручки заведомо ОТЛИЧАЮТСЯ от того, что кладёт правка файла.
#: Совпади они — тест был бы зелен и при полностью оторванной дороге.
BOOT = (True, "ring", 5, 0)


def _app(tmp_path: Path) -> GenericProcessManagerApp:
    """Оркестратор в объёме, который читает ``_start_observability_watcher``.

    Через ``__new__`` и минимальный набор атрибутов — дословно приём соседнего
    стража 4.1: поднимать полное приложение ради двух вызовов значило бы платить
    секундами за проверку одной строки и сделать сторож хрупким по чужой причине.
    """
    system_yaml = tmp_path / "system.yaml"
    system_yaml.write_text("observability:\n  flight:\n    keep: 9\n", encoding="utf-8")
    recipe = tmp_path / "line.yaml"
    recipe.write_text("processes: {}\n", encoding="utf-8")
    companion = tmp_path / "line.observability.yaml"
    # Спутник адресует ключ ПОИМЁННО: оптовые ключи рецепта на оркестратора не
    # действуют (Task 5.13, `recipe_defaults_apply_to`), и безымянная секция
    # молча резолвилась бы в пустоту — сторож был бы зелен по неверной причине.
    companion.write_text(
        "observability:\n  processes:\n    ProcessManager:\n      flight:\n        keep: 3\n",
        encoding="utf-8",
    )

    app = GenericProcessManagerApp.__new__(GenericProcessManagerApp)
    app.name = "ProcessManager"
    app.logger_manager = app.error_manager = app.stats_manager = None
    app._state_store_manager = None
    app.flight_recorder = FlightRecorder(*BOOT)
    app._observability_recipe_path = str(recipe)
    app._config = {"observability_config_path": str(system_yaml)}
    app.get_config = lambda key, default=None: app._config.get(key, default)  # type: ignore[method-assign]
    app._log_info = lambda *a, **k: None  # type: ignore[method-assign]
    app._log_error = lambda *a, **k: None  # type: ignore[method-assign]
    app._broadcast_command = lambda *a, **k: 0  # type: ignore[method-assign]
    return app


def _started(tmp_path: Path):
    app = _app(tmp_path)
    app._start_observability_watcher()
    return app


def _stop(app: GenericProcessManagerApp) -> None:
    for watcher in (app._observability_watcher, getattr(app, "_observability_recipe_watcher", None)):
        if watcher is not None:
            watcher.stop()


def test_the_system_yaml_watcher_carries_the_flight_recorder(tmp_path: Path) -> None:
    """L1: правка ``system.yaml`` обязана менять политику дампа так же, как команда.

    Трогается ТОЛЬКО watcher L1 — сторож дороги L2 стоит отдельно и не имеет
    права краснеть от этой инъекции.
    """
    app = _started(tmp_path)
    try:
        watcher = app._observability_watcher
        assert watcher is not None, "предпосылка: watcher L1 поднят"
        assert app.flight_recorder.knobs == BOOT, "предпосылка: политика ещё загрузочная"

        watcher._on_reload(Config(initial_data={"observability": {"flight": {"keep": 9}}}))

        assert app.flight_recorder.knobs[2] == 9, "правка system.yaml не дошла до рекордера дампов"
    finally:
        _stop(app)


def test_the_recipe_companion_watcher_carries_the_flight_recorder(tmp_path: Path) -> None:
    """L2: та же ручка, вторая дорога, отдельный вызов в исходнике.

    Одна ручка не имеет права вести себя по-разному на двух дорогах — разошлись
    бы они молча.
    """
    app = _started(tmp_path)
    try:
        watcher = app._observability_recipe_watcher
        assert watcher is not None, "предпосылка: watcher L2 поднят"
        assert app.flight_recorder.knobs == BOOT, "предпосылка: политика ещё загрузочная"

        watcher._on_reload(
            Config(initial_data={"observability": {"processes": {"ProcessManager": {"flight": {"keep": 3}}}}})
        )

        assert app.flight_recorder.knobs[2] == 3, "правка спутника рецепта не дошла до рекордера дампов"
    finally:
        _stop(app)
