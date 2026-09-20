# -*- coding: utf-8 -*-
"""Ф1 Task 1.0 — опасности дефолтного ``default_state_bootstrap``.

Тесты АВТОРА на опасности конкретного механизма (не замена независимому набору
``test_f1_task10_acceptance.py``, который написан слепым тестером по критериям).

Три опасности, каждая своим тестом:

1. **Пустой blueprint.** У посева два взаимоисключающих исхода, и оба «выглядят
   правильно» в отрыве от гейта: ``{}`` (store не создаётся) и ``{"processes": {}}``
   (создаётся пустой). Гейт ``GenericProcessManagerApp._setup_state_store`` смотрит
   на ИСТИННОСТЬ dict'а, поэтому выбор решает, ответит ли приложение без процессов
   «поддерево пусто» или «обработчика нет» — это разные диагнозы. Решение
   (``{"processes": {}}``) пришпилено прогоном НАСТОЯЩЕГО гейта, а не сравнением
   литерала: сравнение литерала согласилось бы и с ``{}``.

2. **Результат едет через spawn.** Хук исполняется в РОДИТЕЛЕ, а его результат
   пиклится в ``orchestrator_config`` и распаковывается ребёнком. Непиклябельное
   значение (Path, Pydantic-модель, ссылка на реестр) падало бы глубоко в
   ``Process.start()``. Плюс сюда же — запрет прикладных веток: они наполняются из
   реестров прототипа, которых у framework нет.

3. **Что именно получает хук.** Вызов один (``bootstrap(blueprint)``), и подмена
   аргумента на ``proc_dicts`` (dict-по-имени) НЕ упала бы: ``.get("processes")``
   вернул бы ``None`` → посев молча пустой → ровно тот симптом, ради которого
   задача и делалась. Тест пинует, что явный хук получает blueprint-форму (список
   ``processes`` с ``process_name``), и что дефолт на этом же аргументе даёт
   непустое дерево.
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.app_module import (
    AppSpec,
    ManifestStore,
    build_app,
    default_blueprint_loader,
    default_state_bootstrap,
)
from multiprocess_framework.modules.app_module.builder import SystemBuilder
from multiprocess_framework.modules.app_module.orchestrator import GenericProcessManagerApp
from multiprocess_framework.modules.state_store_module.testing.in_memory_router import (
    InMemoryRouter,
)

# .../app_module/tests/<файл> -> parents[4] = корень репозитория.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_MINIMAL_APP_YAML = _REPO_ROOT / "examples" / "minimal_app" / "app.yaml"

_TICKER = "ticker"
_CONSOLE_SINK = "console_sink"

#: Ветки прикладного ``build_initial_state``, которые в framework НЕ переезжают
#: (их наполняют реестры прототипа: DisplaysConfig, каталог рецептов, SystemConfig).
_APP_ONLY_BRANCHES = ("system", "wires", "services", "displays", "recipes", "plugins")


def _make_orchestrator(initial_state: dict[str, Any]) -> GenericProcessManagerApp:
    """Оркестратор без multiprocessing-init — только поля для ``_setup_state_store``.

    Образец — ``test_state_store_logger_wiring.py::orchestrator``: ``__new__``
    обходит ``ProcessModule.__init__`` и ``_init_managers``, поэтому поля,
    которых касается гейт и конструктор StateStoreManager, ставятся явно.
    """
    orch = GenericProcessManagerApp.__new__(GenericProcessManagerApp)
    orch.name = "ProcessManager"
    orch.config = {"initial_state": initial_state}
    orch.config_handler = None
    orch.router_manager = InMemoryRouter()
    orch.command_manager = None
    orch.logger_manager = None
    orch._state_store_manager = None
    return orch


@pytest.fixture()
def gate_probe():
    """Фабрика «посев → поднялся ли StateStore», гасящая поднятые менеджеры.

    Teardown обязателен: StateStoreManager поднимает поток коалесцирования
    DeltaDispatcher'а, и сторож потоков в ``modules/conftest.py`` краснеет на утечке.
    """
    created: list[Any] = []

    def probe(initial_state: dict[str, Any]) -> bool:
        orch = _make_orchestrator(initial_state)
        orch._setup_state_store()
        if orch._state_store_manager is not None:
            created.append(orch._state_store_manager)
            return True
        return False

    try:
        yield probe
    finally:
        for manager in created:
            manager.shutdown()


def _walk_leaves(node: Any, path: str = "") -> list[tuple[str, Any]]:
    """Все листья дерева с их путями (для проверки примитивности значений)."""
    if isinstance(node, dict):
        out: list[tuple[str, Any]] = []
        for key, value in node.items():
            out.extend(_walk_leaves(value, f"{path}.{key}" if path else str(key)))
        return out
    if isinstance(node, list):
        out = []
        for idx, value in enumerate(node):
            out.extend(_walk_leaves(value, f"{path}[{idx}]"))
        return out
    return [(path, node)]


# --------------------------------------------------------------------------- #
# Опасность 1: пустой blueprint — решение проверяется НАСТОЯЩИМ гейтом          #
# --------------------------------------------------------------------------- #


def test_empty_blueprint_decision_is_pinned(gate_probe) -> None:
    """Пустой blueprint → ``{"processes": {}}``, и этот посев ПОДНИМАЕТ StateStore.

    Довод за ``{"processes": {}}`` против ``{}``: приложение без процессов — законная
    конфигурация, и на ``state.get_subtree`` оно должно отвечать «пусто», а не
    «обработчика нет» (диспетчер отвечает отказом, когда команду никто не
    зарегистрировал, то есть когда StateStore не поднялся). Цена решения — пустой
    StateStore у приложения, которое state-plane не использует; она мала против
    инструмента вердиктов, который врёт про топологию.

    Контроль в том же тесте: ``{}`` гейт НЕ поднимает. Без него утверждение выше
    было бы вакуумным — оно бы прошло и на реализации, которая поднимает store
    всегда, и решение «не ``{}``» ничего бы не значило.
    """
    seed = default_state_bootstrap({"name": "empty", "processes": []})

    assert seed == {"processes": {}}, f"посев пустого blueprint не равен литералу решения: {seed!r}"
    assert gate_probe(seed), "посев {'processes': {}} не поднял StateStore — гейт решение не пропустил"
    assert not gate_probe({}), "контроль сломан: пустой dict тоже поднимает StateStore, гейт ничего не различает"

    # blueprint вообще без ключа processes — та же ветка (None → пусто), не падение.
    assert default_state_bootstrap({}) == {"processes": {}}


# --------------------------------------------------------------------------- #
# Опасность 2: результат пересекает spawn + запрет прикладных веток             #
# --------------------------------------------------------------------------- #


def test_seed_is_pickle_safe_and_has_no_app_branches() -> None:
    """Посев РЕАЛЬНОГО приложения: пиклится без потерь, все листья — примитивы.

    Проверка идёт на blueprint'е ``examples/minimal_app`` (а не на синтетическом
    словаре): синтетика согласилась бы с чем угодно, потому что в неё непримитив и
    не положишь. Реальный загрузчик тянет YAML через ``recipe``-разворот, и именно
    там мог бы приехать Path/модель.

    Круговой прогон ``loads(dumps(...)) == seed`` — не то же, что «дампится»: он
    ловит значения, которые пиклятся, но восстанавливаются НЕ равными себе.
    """
    manifest = ManifestStore(_MINIMAL_APP_YAML).load()
    blueprint = default_blueprint_loader(manifest)

    seed = default_state_bootstrap(blueprint)

    assert set(seed) == {"processes"}, f"верхний уровень посева не только 'processes': {sorted(seed)!r}"
    for branch in _APP_ONLY_BRANCHES:
        assert branch not in seed, f"прикладная ветка {branch!r} протекла в generic-посев: {seed!r}"

    assert _TICKER in seed["processes"] and _CONSOLE_SINK in seed["processes"], (
        f"посев minimal_app не содержит ожидаемых процессов: {sorted(seed['processes'])!r}"
    )

    assert pickle.loads(pickle.dumps(seed)) == seed, "посев не переживает круговой прогон pickle"  # nosec B301

    non_primitive = [
        (path, type(value).__name__)
        for path, value in _walk_leaves(seed)
        if value is not None and not isinstance(value, (str, int, float, bool))
    ]
    assert not non_primitive, f"в посеве непримитивные листья (spawn-граница): {non_primitive!r}"


# --------------------------------------------------------------------------- #
# Опасность 3: что именно приезжает в хук                                      #
# --------------------------------------------------------------------------- #


def test_explicit_hook_receives_same_blueprint_as_default() -> None:
    """Явному хуку приезжает blueprint-форма, и дефолт на ней даёт непустое дерево.

    Опасность конкретно этого шва: единственный вызов ``bootstrap(blueprint)`` стоит
    рядом с ``builder(blueprint, ...)``, результат которого — ``proc_dicts``
    (dict-по-имени). Подмена аргумента НЕ упала бы: у dict'а нет ключа ``processes``,
    ``or []`` вернул бы пусто, посев стал бы ``{"processes": {}}`` — молча пустым.
    Это ровно тот симптом, ради которого задача и делалась, поэтому проверяется
    ФОРМА аргумента (список с ``process_name``), а не только факт вызова.
    """
    recorded: list[Any] = []

    def _recording_hook(blueprint: dict) -> dict:
        recorded.append(blueprint)
        return {"processes": {"marker": {"config": {}, "state": {"status": "stopped"}}}}

    build_app(AppSpec(manifest_path=_MINIMAL_APP_YAML, state_bootstrap=_recording_hook))

    assert len(recorded) == 1, f"хук вызван не один раз: {len(recorded)}"
    got = recorded[0]

    manifest = ManifestStore(_MINIMAL_APP_YAML).load()
    assert got == default_blueprint_loader(manifest), (
        "хуку приехал НЕ blueprint от default_blueprint_loader (возможна подмена аргумента)"
    )

    procs = got.get("processes")
    assert isinstance(procs, list) and procs, f"аргумент хука не blueprint-формы (список processes): {type(procs)!r}"
    names = {p.get("process_name") for p in procs if isinstance(p, dict)}
    assert {_TICKER, _CONSOLE_SINK} <= names, f"в аргументе хука нет процессов minimal_app: {names!r}"

    # Дефолт на ТОМ ЖЕ аргументе даёт непустое дерево — значит «явный выиграл»
    # означает победу над работающим дефолтом, а не над пустотой.
    assert set(default_state_bootstrap(got)["processes"]) == names


# --------------------------------------------------------------------------- #
# Опасность 4: factory-дорога — прикладной посев не трогать                     #
# --------------------------------------------------------------------------- #


def test_factory_road_keeps_application_seed_untouched(tmp_path: Path) -> None:
    """Factory-дорога (прототип): посев приложения доезжает ЦЕЛЫМ, дефолт не применяется.

    Свойство «прототип выигрывает у дефолта» держится не ``AppSpec.state_bootstrap``,
    а ранним ``return`` в :meth:`SystemBuilder.build` до generic-ветки — то есть
    отсутствием кода, а не его наличием. Такое свойство не краснеет само: измерено
    инъекцией (дефолтный посев дописан поверх factory-результата) — из 100 тестов
    ``app_module`` + ``test_run_app_prototype`` + ``minimal_app`` не умер НИ ОДИН.
    Существующие кандидаты мимо: ``test_factory_mode_delegates_to_launcher_factory``
    смотрит на тип launcher'а и аргументы фабрики, ``test_run_app_prototype`` — на
    имена процессов и класс оркестратора; ``initial_state`` не сверяет никто.

    Пинуется НАБЛЮДАЕМЫЙ эффект — тот же объект посева на выходе, — а не имя
    невызванной функции: спай на ``default_state_bootstrap`` охранял бы имя и
    протух бы при любой равносильной замене.

    Ветка ``system`` в образце значима: прикладной посев её строит, дефолт по
    контракту НЕ строит (см. ``_APP_ONLY_BRANCHES``). Её исчезновение — признак
    того, что посев подменён дефолтным.
    """
    (tmp_path / "pipeline.yaml").write_text(
        f"name: p\nprocesses:\n  - process_name: {_TICKER}\nwires: []\n", encoding="utf-8"
    )
    manifest = tmp_path / "app.yaml"
    manifest.write_text("name: FactorySeedApp\npipeline: pipeline.yaml\n", encoding="utf-8")

    app_seed = {
        "system": {"mode": "prototype-own"},
        "processes": {_TICKER: {"state": {"status": "seeded-by-app"}}},
    }

    class _FakeLauncher:
        def __init__(self) -> None:
            self._orchestrator_config = {"initial_state": app_seed}

    spec = AppSpec(manifest_path=manifest, launcher_factory=lambda m, override: _FakeLauncher())
    launcher = SystemBuilder(spec).build()

    seed = launcher._orchestrator_config["initial_state"]
    assert seed is app_seed, f"builder подменил объект посева на factory-дороге: {seed!r}"
    # Литерал, а не сравнение с app_seed: ссылочное равенство выше согласится и с
    # посевом, который builder изменил НА МЕСТЕ.
    assert seed == {
        "system": {"mode": "prototype-own"},
        "processes": {"ticker": {"state": {"status": "seeded-by-app"}}},
    }, f"посев приложения изменён на месте: {seed!r}"
