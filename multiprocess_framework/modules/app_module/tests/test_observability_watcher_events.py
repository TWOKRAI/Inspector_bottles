# -*- coding: utf-8 -*-
"""Ф4 (4.1) — оба файловых watcher'а оркестратора несут селектор широких записей.

**Почему сторож живёт здесь, а не рядом с механизмом.** Первая редакция стояла в
``process_module/tests/`` и импортировала оттуда ``GenericProcessManagerApp`` —
контракт слоёв это запрещает и покраснел на корневом гейте
(``test_no_other_framework_module_imports_app_module``): ``process_module`` слоем
НИЖЕ ``app_module``. Сторож про оркестратор принадлежит оркестратору.

Проверяется ПРОДОВЫЙ вход — ``_start_observability_watcher`` самого приложения, а
не фабрика ``make_observability_on_reload`` внутри него: страж на фабрике зелен и
тогда, когда продовая сборка забыла передать селектор, — ровно тот зазор, который
нашло ревью 4.1 (инъекция по одной строке в каждом из двух вызовов давала ноль
красных).
"""

from __future__ import annotations

from pathlib import Path

from multiprocess_framework.modules.app_module.orchestrator import GenericProcessManagerApp
from multiprocess_framework.modules.config_module.core.config import Config
from multiprocess_framework.modules.process_module.managers.observability_wiring import WideEventSelector


def _app(tmp_path: Path) -> GenericProcessManagerApp:
    """Оркестратор в объёме, который читает ``_start_observability_watcher``.

    Через ``__new__`` и минимальный набор атрибутов: поднимать полное приложение
    ради двух вызовов значило бы платить секундами за проверку одной строки, и
    зависимость от подъёма сделала бы страж хрупким по чужой причине.
    """
    system_yaml = tmp_path / "system.yaml"
    system_yaml.write_text("observability:\n  events:\n    first_n: 7\n    every_mth: 3\n", encoding="utf-8")
    recipe = tmp_path / "line.yaml"
    recipe.write_text("processes: {}\n", encoding="utf-8")
    companion = tmp_path / "line.observability.yaml"
    # Спутник адресует ключ ПОИМЁННО: оптовые ключи рецепта на оркестратора не
    # действуют (Task 5.13, `recipe_defaults_apply_to`), и безымянная секция
    # молча резолвилась бы в пустоту — тест был бы зелен по неверной причине.
    companion.write_text(
        "observability:\n  processes:\n    ProcessManager:\n      events:\n        first_n: 5\n",
        encoding="utf-8",
    )

    app = GenericProcessManagerApp.__new__(GenericProcessManagerApp)
    app.name = "ProcessManager"
    app.logger_manager = app.error_manager = app.stats_manager = None
    app._state_store_manager = None
    app.event_selector = WideEventSelector(0, 0)
    app._observability_recipe_path = str(recipe)
    app._config = {"observability_config_path": str(system_yaml)}
    app.get_config = lambda key, default=None: app._config.get(key, default)  # type: ignore[method-assign]
    app._log_info = lambda *a, **k: None  # type: ignore[method-assign]
    app._log_error = lambda *a, **k: None  # type: ignore[method-assign]
    app._broadcast_command = lambda *a, **k: 0  # type: ignore[method-assign]
    return app


def test_both_orchestrator_watchers_carry_the_event_selector(tmp_path: Path) -> None:
    """Правка ФАЙЛА обязана менять отбор так же, как та же правка командой.

    Проверяются оба watcher'а сразу — L1 (``system.yaml``) и L2 (спутник
    рецепта): в исходнике это РАЗНЫЕ вызовы, и забыть аргумент можно в любом.
    Одна ручка не имеет права вести себя по-разному на двух дорогах — разошлись
    бы они молча.
    """
    app = _app(tmp_path)
    app._start_observability_watcher()
    try:
        l1 = app._observability_watcher
        l2 = app._observability_recipe_watcher
        assert l1 is not None and l2 is not None, "предпосылка: оба watcher'а подняты"

        l1._on_reload(Config(initial_data={"observability": {"events": {"first_n": 7, "every_mth": 3}}}))
        assert app.event_selector.knobs == (7, 3), "правка system.yaml не дошла до отбора"

        l2._on_reload(
            Config(initial_data={"observability": {"processes": {"ProcessManager": {"events": {"first_n": 5}}}}})
        )
        assert app.event_selector.knobs == (5, 3), "правка спутника рецепта не дошла до отбора"
    finally:
        for watcher in (app._observability_watcher, app._observability_recipe_watcher):
            if watcher is not None:
                watcher.stop()
