# -*- coding: utf-8 -*-
"""
Тесты приёмки Ф5.13 — маршрутизация наблюдаемости к оркестратору (PM).

Написаны НЕЗАВИСИМЫМ тестировщиком, не видевшим реализации, по критериям
приёмки и только по ним. Это намеренно: тесты от автора правки доказывают
модель автора, а не реальность.

Покрываемые критерии
---------------------
A1  — рецепт именует ProcessManager → PM получает его уровень (switch)
A2  — switch меняет уровень PM И источник слоя
A3  — молчащий рецепт снимает L2 у PM (как у детей)
A4  — долька соседа не затекает в PM и наоборот
A11 — defaults в рецепте не задевают PM; processes.ProcessManager — задевают

Критерии вне автоматики (живой стенд)
--------------------------------------
A0  — boot: spawner кладёт APP_CONFIG_KEY в конфиг PM и он применяется в
      инициализации. Наблюдаемо только на живом PM-процессе (ProcessSpawner
      + реальный boot), не в unit-тесте.
A5  — boot ≡ switch: требует запуска реального PM процесса для boot-половины.
A6  — effective.logger.log_directory указывает на каталог с реальными файлами:
      верифицируется live-прогоном (PM пишет файлы после реального старта).

Сноска об A0 — что оказалось на самом деле
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Первая редакция этой сноски (написана тестировщиком до реализации) звучала так:
«механизм boot работает, дефект в том, что ProcessSpawner не вызывает обработчик».
Диагноз оказался ближе к истине, чем формулировка резидуала, но неполным.

Реально: ассемблер строит ``proc_dict["managers"]`` из слоёв только ДОЧЕРНИМ
процессам, а bundle оркестратора ключа ``managers`` не несёт вовсе — его логгер
поднимался на голых дефолтах L0 (``default_level="INFO"``, ``log_directory=None``).
Отсюда СРАЗУ два симптома, R6-C и R6-H, и воспроизводились они даже без рецепта.
Починено в ``ProcessModule._apply_boot_observability_layers`` по структурному
признаку «секция менеджеров пуста», а не по имени процесса.

Все RED-тесты этого файла стали GREEN после правки; xfail-маркеры сняты по мере
того, как strict=True сам требовал этого при каждом XPASS.
"""

from __future__ import annotations

import pathlib
import time
from typing import Any, Dict

import pytest

from multiprocess_framework.modules.logger_module.configs import LoggerManagerConfig
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    APP_CONFIG_KEY,
    RECIPE_PATH_CONFIG_KEY,
    ORCHESTRATOR_PROCESS_NAME,
    process_observability_layers,
    resolve_recipe_section,
)
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    observability_effective,
)

from .conftest import make_pm


# ---------------------------------------------------------------------------
# Вспомогательные классы — минимальный PM-сервис для handler-тестов
# ---------------------------------------------------------------------------


class _Cm:
    """Простой command registry (те же методы, что у CommandManager)."""

    def __init__(self) -> None:
        self.handlers: Dict[str, Any] = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler


class _PmSvc:
    """Минимальный сервис с именем ProcessManager для тестов обработчика.

    Копия паттерна из test_observability_recipe_switch.py, но name=ProcessManager.
    Имя принципиально: resolve_recipe_section и обработчик config.reload
    используют ``svc.name`` для извлечения дольки рецепта.
    """

    def __init__(self, logger: LoggerManager, config: Dict[str, Any] | None = None) -> None:
        self.command_manager = _Cm()
        self.name = "ProcessManager"
        self.logger_manager = logger
        self.error_manager = None
        self.stats_manager = None
        self._config = dict(config or {})

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def update_config(self, key, value):
        self._config[key] = value

    def _log_debug(self, msg, **kw): ...

    def _log_info(self, msg, **kw): ...

    def _log_warning(self, msg, **kw): ...


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_log(tmp_path: pathlib.Path):
    """Временный каталог для логов, совместимый с Windows-lock."""
    return tmp_path


@pytest.fixture
def pm_handler_svc(tmp_log):
    """PM-сервис (name=ProcessManager) с реальным LoggerManager и L1=WARNING.

    Используется для тестов уровня обработчика: handler-тесты проверяют, что
    config.reload корректно применяет слои к PM. Большинство таких тестов
    уже ЗЕЛЁНЫЕ — дефект не в обработчике, а в доставке (switch и boot).
    """
    logger = LoggerManager(
        config=LoggerManagerConfig(
            app_name="process_manager",
            log_directory=str(tmp_log),
            enable_batching=False,
        )
    )
    svc = _PmSvc(logger, {APP_CONFIG_KEY: {"log_level": "WARNING"}})
    BuiltinCommands(svc)._register_observability_commands()
    # Boot: применить L1 (WARNING) через обработчик
    svc.command_manager.handlers["config.reload"]({"observability": {}})
    try:
        yield svc
    finally:
        logger.shutdown()
        time.sleep(0.1)


@pytest.fixture
def pm_with_real_logger(tmp_log):
    """PM из make_pm с подменённым реальным LoggerManager и L1=WARNING.

    Используется для тестов через switch-путь (apply_topology /
    _reset_observability_sessions): здесь нужен живой PM-объект с реальным
    логгером, чтобы эффективный уровень читался из настоящего LoggerManager.
    """
    logger = LoggerManager(
        config=LoggerManagerConfig(
            app_name="process_manager",
            log_directory=str(tmp_log),
            enable_batching=False,
        )
    )
    pm = make_pm({"camera_0": {"class": "x.Y"}})

    # Подменяем mock-логгер на реальный
    pm.logger_manager = logger
    pm.error_manager = None
    pm.stats_manager = None

    # Конфиг с L1=WARNING
    values: dict = {
        APP_CONFIG_KEY: {"log_level": "WARNING"},
        "stop_process_timeout": 1.0,
        "shutdown_timeout": 1.0,
        "start_ready_timeout_s": 0.05,
    }
    pm.get_config = lambda k, d=None: values.get(k, d)
    pm.update_config = lambda k, v: values.update({k: v}) or True

    # Регистрируем команды наблюдаемости
    pm.command_manager = _Cm()
    BuiltinCommands(pm)._register_observability_commands()
    pm.command_manager.handlers["config.reload"]({"observability": {}})

    # Глушим broadcast: switch посылает config.reload детям; здесь детей нет
    pm._broadcast_command = lambda cmd, data, **kw: 1

    try:
        yield pm, values
    finally:
        logger.shutdown()
        time.sleep(0.1)


def _level(svc_or_pm) -> str:
    """Текущий effective log-level из реального LoggerManager."""
    lm = getattr(svc_or_pm, "logger_manager", svc_or_pm)
    return observability_effective(logger=lm)["logger"]["default_level"]


# ---------------------------------------------------------------------------
# A11 — асимметрия defaults / processes.ProcessManager
# ---------------------------------------------------------------------------


class TestA11Asymmetry:
    """A11: defaults НЕ применяются к PM; processes.ProcessManager — применяются.

    Это «осознанная асимметрия»: заглушить оркестратора можно только поимённо.

    Тесты A11-1 и A11-2 КРАСНЫ до правки.
    A11-3 (isolation) GREEN — resolve_recipe_section уже корректен для детей.
    """

    def test_a11_1_defaults_only_recipe_does_not_touch_pm(self, pm_handler_svc) -> None:
        """A11 первая половина: defaults только → PM остаётся на L1, не ERROR.

        Сейчас КРАСНЫЙ: resolve_recipe_section('ProcessManager') возвращает defaults
        и обработчик выставляет PM в ERROR вместо того, чтобы оставить WARNING.
        После правки: PM игнорирует defaults и остаётся на L1=WARNING.
        """
        svc = pm_handler_svc
        recipe = {"defaults": {"log_level": "ERROR"}}

        svc.command_manager.handlers["config.reload"](
            {
                "observability_recipe": recipe,
                "observability_recipe_path": "/tmp/recipe.yaml",
            }
        )

        # PM не должен стать ERROR — defaults к нему не применяются
        assert _level(svc) != "ERROR", (
            f"defaults из рецепта задели PM: уровень стал ERROR. "
            f"Асимметрия нарушена: PM должен быть заглушаем только поимённо. "
            f"Текущий уровень: {_level(svc)}"
        )
        # PM должен оставаться на L1 (WARNING), а не упасть обратно на L0 (INFO)
        assert _level(svc) == "WARNING", (
            f"PM не на уровне L1 после defaults-only рецепта. Ожидали WARNING (L1), получили: {_level(svc)}"
        )
        # Слой L2 рецепта у PM должен быть пустым
        assert process_observability_layers(svc).recipe == {}, (
            f"L2 у PM не пустой после defaults-only рецепта: {process_observability_layers(svc).recipe}"
        )

    def test_a11_2_pm_named_in_recipe_applies_via_handler(self, pm_handler_svc) -> None:
        """A11 вторая половина (уровень хендлера): processes.ProcessManager → PM ERROR.

        Сейчас ЗЕЛЁНЫЙ: обработчик корректно применяет processes.ProcessManager к PM.
        Тест включён как РЕГРЕССИОННЫЙ: при исправлении A11-1 нельзя сломать этот путь.
        """
        svc = pm_handler_svc
        recipe = {"processes": {"ProcessManager": {"log_level": "ERROR"}}}

        svc.command_manager.handlers["config.reload"](
            {
                "observability_recipe": recipe,
                "observability_recipe_path": "/tmp/recipe.yaml",
            }
        )

        assert _level(svc) == "ERROR", (
            f"processes.ProcessManager не применился к PM. Ожидали ERROR, получили: {_level(svc)}"
        )

    def test_a11_3_pm_section_does_not_affect_child(self) -> None:
        """A11 вторая половина (изоляция): processes.ProcessManager не затекает в camera_0.

        GREEN: resolve_recipe_section уже корректно изолирует процессы.
        Регрессионный тест.
        """
        recipe = {"processes": {"ProcessManager": {"log_level": "ERROR"}}}
        child_slice = resolve_recipe_section(recipe, "camera_0")
        assert child_slice == {}, (
            f"Долька ProcessManager вытекла в camera_0: {child_slice}. "
            f"Дочерний процесс не должен получать настройки оркестратора через processes."
        )

    def test_a11_4_defaults_apply_to_children_not_pm(self) -> None:
        """A11 симметрия через resolve_recipe_section.

        Дети получают defaults; PM — нет (после правки).
        Сейчас КРАСНЫЙ: resolve_recipe_section('ProcessManager') возвращает defaults.
        """
        recipe = {"defaults": {"log_level": "ERROR"}}

        child_slice = resolve_recipe_section(recipe, "camera_0")
        pm_slice = resolve_recipe_section(recipe, "ProcessManager")

        # Дети должны получать defaults
        assert child_slice.get("log_level") == "ERROR", f"Дочерний процесс не получил defaults: {child_slice}"
        # PM НЕ должен получать defaults
        assert pm_slice.get("log_level") != "ERROR", (
            f"resolve_recipe_section применил defaults к ProcessManager: {pm_slice}. "
            f"Асимметрия нарушена: оркестратора заглушить можно только поимённо."
        )


# ---------------------------------------------------------------------------
# A1, A2, A3 — switch доставляет рецепт к PM
# ---------------------------------------------------------------------------


class TestSwitchDeliversRecipeToPm:
    """A1, A2, A3 через путь apply_topology / _reset_observability_sessions.

    Все тесты КРАСНЫ до правки: _reset_observability_sessions рассылает
    config.reload детям, но не применяет L2 к PM самому себе.
    """

    def test_a1_switch_with_pm_named_in_recipe_updates_pm_level(self, pm_with_real_logger) -> None:
        """A1: switch с processes.ProcessManager.log_level=DEBUG → PM effective DEBUG.

        Сейчас КРАСНЫЙ: switch не обновляет PM собственный L2.
        После правки: PM должен получить DEBUG.
        """
        pm, _ = pm_with_real_logger

        result = pm.apply_topology(
            {
                "processes": [],
                "wires": [],
                "observability": {"processes": {"ProcessManager": {"log_level": "DEBUG"}}},
            }
        )

        assert result["success"] is True, f"apply_topology не удался: {result}"
        assert _level(pm) == "DEBUG", (
            f"PM не получил уровень из рецепта через switch. "
            f"Ожидали DEBUG (из processes.ProcessManager), получили: {_level(pm)}"
        )

    def test_a9_companion_rides_in_switch_envelope_and_beats_recipe(self, pm_with_real_logger, tmp_log) -> None:
        """A9 (шаг 6): спутник едет в конверте switch'а и побеждает рецепт.

        Авторский тест на опасность механизма, а не на критерий приёмки.

        До шага 6 спутник попадал в слой только через пересборку proc_dict'ов, а
        конверт вёз сырую секцию рецепта. Ненаблюдаемо это было потому, что
        пересоздаваемый ребёнок получал спутник вторым путём. Двух адресатов
        второго пути нет: protected-процессы (не перезапускаются) и сам
        оркестратор — у них конверт единственный источник, и «сохранить» после
        switch молча откатывалось.

        Порядок проверяется явно: спутник ПОВЕРХ рецепта. Будь он обратным,
        сохранённая настройка отменялась бы switch'ем через раз — то есть
        зависела бы от того, что человек написал в рецепте руками.
        """
        from multiprocess_framework.modules.process_module.configs.observability_companion import (
            companion_path,
        )

        recipe = tmp_log / "r_companion.yaml"
        recipe.write_text("processes: []\n", encoding="utf-8")
        # Формат спутника: корневой ключ `observability`, внутри — та же форма,
        # что у секции рецепта. Машина всегда пишет его в виде `processes:`.
        companion_path(str(recipe)).write_text(
            """observability:
  processes:
    ProcessManager:
      log_level: ERROR
""",
            encoding="utf-8",
        )
        _, values = pm_with_real_logger
        values[RECIPE_PATH_CONFIG_KEY] = str(recipe)
        pm = pm_with_real_logger[0]

        resp = pm.apply_topology(
            {
                "processes": [],
                "wires": [],
                # Рецепт говорит DEBUG, спутник — ERROR. Спутник новее: его пишет пульт.
                "observability": {"processes": {"ProcessManager": {"log_level": "DEBUG"}}},
            }
        )

        reset = (resp or {}).get("observability_session_reset") or {}
        assert reset.get("orchestrator_recipe_keys") == ["log_level"]
        assert _level(pm) == "ERROR", "спутник обязан побеждать рецепт — его писал пульт, он новее"

    def test_a2_switch_changes_pm_level_and_recipe_source(self, pm_with_real_logger, tmp_log) -> None:
        """A2: последовательный switch A→B меняет и уровень PM, и источник слоя.

        Сейчас КРАСНЫЙ: уровень не меняется (PM игнорирует recipe при switch).
        После правки: оба switch должны менять уровень PM.
        """
        pm, values = pm_with_real_logger
        recipe_a_path = str(tmp_log / "recipe_a.yaml")
        recipe_b_path = str(tmp_log / "recipe_b.yaml")

        # Switch A: WARNING для PM
        values[RECIPE_PATH_CONFIG_KEY] = recipe_a_path
        pm.apply_topology(
            {
                "processes": [],
                "wires": [],
                "observability": {"processes": {"ProcessManager": {"log_level": "WARNING"}}},
            }
        )
        level_a = _level(pm)

        # Switch B: ERROR для PM
        values[RECIPE_PATH_CONFIG_KEY] = recipe_b_path
        pm.apply_topology(
            {
                "processes": [],
                "wires": [],
                "observability": {"processes": {"ProcessManager": {"log_level": "ERROR"}}},
            }
        )
        level_b = _level(pm)

        # A2: уровни должны быть разными (источник изменился)
        assert level_a == "WARNING", f"Switch A: PM не стал WARNING. Получили: {level_a}"
        assert level_b == "ERROR", f"Switch B: PM не стал ERROR. Получили: {level_b}"
        assert level_a != level_b, (
            f"PM уровень не изменился между switch A и B: оба {level_a}. Источник слоя или уровень не обновляется."
        )

    def test_a3_silent_recipe_removes_pm_l2(self, pm_with_real_logger) -> None:
        """A3: рецепт без observability снимает L2 у PM.

        Сейчас КРАСНЫЙ: PM не получает L2 ни при первом switch, ни при снятии.
        После правки: сначала L2 устанавливается, затем снимается пустым рецептом.
        """
        pm, _ = pm_with_real_logger

        # Сначала установить L2 (PM должен получить его через switch)
        pm.apply_topology(
            {
                "processes": [],
                "wires": [],
                "observability": {"processes": {"ProcessManager": {"log_level": "ERROR"}}},
            }
        )
        assert _level(pm) == "ERROR", (
            f"Предусловие A3 не выполнено: L2 не установлен через switch. Текущий уровень: {_level(pm)}"
        )

        # Switch к рецепту без секции observability → L2 должен сняться
        pm.apply_topology(
            {
                "processes": [],
                "wires": [],
                # observability отсутствует → blueprint.observability = None → {} → пусто
            }
        )
        # После снятия L2 побеждает L1 (WARNING)
        assert _level(pm) == "WARNING", (
            f"A3: после пустого рецепта PM не вернулся к L1. Ожидали WARNING (L1), получили: {_level(pm)}"
        )
        assert process_observability_layers(pm).recipe == {}, (
            f"L2 рецепта у PM не снят: {process_observability_layers(pm).recipe}"
        )

    def test_a1_recipe_layer_is_stored_in_pm_config(self, pm_with_real_logger) -> None:
        """A1 — слой L2 фиксируется в конфиге PM (не только в менеджере).

        process_observability_layers(pm).recipe читает OVERRIDE_CONFIG_KEY из
        pm.get_config — если L2 туда не записан, provenance будет врать.
        Сейчас КРАСНЫЙ: recipe == {} после switch.
        """
        pm, _ = pm_with_real_logger
        expected_recipe = {"log_level": "DEBUG"}

        pm.apply_topology(
            {
                "processes": [],
                "wires": [],
                "observability": {"processes": {"ProcessManager": expected_recipe}},
            }
        )

        layers = process_observability_layers(pm)
        assert layers.recipe == expected_recipe, (
            f"L2 рецепта не сохранён в конфиге PM. Ожидали {expected_recipe}, получили: {layers.recipe}"
        )


# ---------------------------------------------------------------------------
# A4 — изоляция долек процессов
# ---------------------------------------------------------------------------


class TestA4Isolation:
    """A4: долька PM не задевает соседей и наоборот.

    Тесты уровня resolve_recipe_section — GREEN (функция работает корректно).
    Тест через switch — RED (switch не доставляет L2 к PM).
    """

    def test_a4_pm_and_neighbor_get_different_slices(self) -> None:
        """A4: при наличии обоих sections PM и camera_0 получают разные дольки.

        GREEN — регрессионный тест.
        """
        recipe = {
            "processes": {
                "ProcessManager": {"log_level": "ERROR"},
                "camera_0": {"log_level": "DEBUG"},
            }
        }
        pm_slice = resolve_recipe_section(recipe, "ProcessManager")
        camera_slice = resolve_recipe_section(recipe, "camera_0")

        assert pm_slice.get("log_level") == "ERROR", f"ProcessManager не получил свою дольку: {pm_slice}"
        assert camera_slice.get("log_level") == "DEBUG", f"camera_0 не получила свою дольку: {camera_slice}"
        assert pm_slice != camera_slice, "Дольки PM и camera_0 совпали — утечка"

    def test_a4_switch_neighbor_change_does_not_affect_pm(self, pm_with_real_logger) -> None:
        """A4: switch, меняющий только camera_0, не трогает PM.

        Сейчас КРАСНЫЙ для обоих switch (PM не получает свой L2).
        После правки: первый switch устанавливает PM=WARNING, второй не трогает PM.
        """
        pm, _ = pm_with_real_logger

        # Switch A: PM=WARNING, camera_0=INFO
        pm.apply_topology(
            {
                "processes": [],
                "wires": [],
                "observability": {
                    "processes": {
                        "ProcessManager": {"log_level": "WARNING"},
                        "camera_0": {"log_level": "INFO"},
                    }
                },
            }
        )
        # Предусловие: PM на WARNING
        assert _level(pm) == "WARNING", f"A4 предусловие: PM не на WARNING после первого switch. Уровень: {_level(pm)}"

        # Switch B: только camera_0 меняется, PM.processes не указан
        pm.apply_topology(
            {
                "processes": [],
                "wires": [],
                "observability": {
                    "processes": {
                        "camera_0": {"log_level": "DEBUG"},
                    }
                },
            }
        )
        # PM должен остаться на WARNING
        assert _level(pm) == "WARNING", f"A4: switch на camera_0 задел PM. Ожидали WARNING, получили: {_level(pm)}"


# ---------------------------------------------------------------------------
# A0 — handler-контракт (GREEN, задокументирован как регрессионный)
# ---------------------------------------------------------------------------


class TestA0HandlerContract:
    """A0 на уровне обработчика: handler корректно применяет L1 к PM.

    Эти тесты GREEN: дефект не в обработчике, а в доставке (boot/switch).
    Включены для регрессии: исправление не должно сломать handler-путь.

    ВНИМАНИЕ: полный A0 (PM применяет L1 при реальном запуске) проверяется
    живым прогоном, не unit-тестом. Spawner кладёт observability_app в
    orchestrator_config; PM должен применить его при инициализации.
    """

    def test_a0_handler_applies_l1_when_set(self, pm_handler_svc) -> None:
        """Если APP_CONFIG_KEY=WARNING задан и handler вызван — PM на WARNING.

        GREEN. Регрессионный тест: исправление не должно сломать путь.
        """
        svc = pm_handler_svc
        assert _level(svc) == "WARNING", f"Обработчик не применил L1=WARNING к PM. Текущий: {_level(svc)}"

    def test_a0_without_l1_pm_defaults_to_framework_default(self, tmp_log) -> None:
        """Без APP_CONFIG_KEY PM стоит на дефолте фреймворка (INFO).

        GREEN — документирует текущее поведение до применения L1.
        Это именно то, что сейчас происходит в продакшне при boot (A0-дефект).
        """
        logger = LoggerManager(
            config=LoggerManagerConfig(
                app_name="pm_noconfig",
                log_directory=str(tmp_log),
                enable_batching=False,
            )
        )
        svc = _PmSvc(logger, {})  # APP_CONFIG_KEY не задан
        BuiltinCommands(svc)._register_observability_commands()
        svc.command_manager.handlers["config.reload"]({"observability": {}})

        try:
            level = _level(svc)
            # Без L1 уровень — дефолт фреймворка (INFO)
            assert level == "INFO", f"Без APP_CONFIG_KEY ожидался INFO (дефолт фреймворка), получили: {level}"
        finally:
            logger.shutdown()
            time.sleep(0.1)


# ---------------------------------------------------------------------------
# Проверка «тест сам не лжёт» — break-injection проверка A11
# ---------------------------------------------------------------------------


class TestBreakInjectionA11:
    """Break-injection: каждый RED-тест должен реально падать на текущем коде.

    Эти тесты ВЕРИФИЦИРУЮТ, что A11-1 и A11-4 — действительно красные, а не
    случайно зелёные из-за неверной логики теста.

    Запускается ОТДЕЛЬНО от основного набора — для подтверждения перед слиянием.
    В CI они будут зелёными только после исправления A11.
    """

    def test_readback_explains_the_asymmetry(self, pm_handler_svc) -> None:
        """Шаг 9: readback объясняет асимметрию, а не оставляет её догадкой.

        Без этого поля `provenance` показывал бы у оркестратора `layer=app` там,
        где у соседа `layer=recipe`, и на вопрос «почему у PM нет ключа» ответа
        в ответе команды не было бы вовсе — правило жило бы только в голове
        того, кто его принял.

        Значение обязано браться из того же `recipe_defaults_apply_to`, которым
        правило исполняется. Здесь это проверяется тем, что признак совпадает с
        поведением резолвера на той же секции: разойдись они — readback описывал
        бы не то, что происходит.
        """
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            recipe_defaults_apply_to,
        )

        # `introspect.observability` живёт в другом регистраторе, чем команды
        # правки — читающая команда и пишущие разведены намеренно.
        BuiltinCommands(pm_handler_svc)._register_introspect_commands()
        resp = pm_handler_svc.command_manager.handlers["introspect.observability"]({})
        flag = resp["layers"]["recipe_defaults_applied"]

        assert flag is False, "у оркестратора оптовый ключ рецепта не действует"
        assert flag is recipe_defaults_apply_to(pm_handler_svc.name)
        # И признак не врёт: резолвер на той же секции ведёт себя так же.
        section = {"defaults": {"log_level": "ERROR"}}
        applied = bool(resolve_recipe_section(section, pm_handler_svc.name))
        assert applied is flag
        # У обычного процесса — противоположно, обе стороны пары.
        assert recipe_defaults_apply_to("camera_0") is True
        assert bool(resolve_recipe_section(section, "camera_0")) is True

    def test_defaults_reach_pm_only_with_explicit_override(self) -> None:
        """Разницу делает ИМЕННО правило исключения, а не что-то по соседству.

        Пришёл на смену «маяку» `test_current_behavior_defaults_do_apply_to_pm`,
        который был зелёным до правки Task 5.13 и красным после — то есть
        самоуничтожался в момент успеха и переставал что-либо стеречь.

        Здесь тот же факт закреплён навсегда: одна и та же секция, один и тот же
        адресат, различается только `include_defaults`. Если завтра `defaults`
        перестанут доходить до PM по какой-то ПОСТОРОННЕЙ причине (сломался
        merge, потерялась короткая форма), первая половина останется зелёной по
        неверной причине — а вторая упадёт и назовёт это.
        """
        section = {"defaults": {"log_level": "ERROR"}, "processes": {"camera_0": {"log_level": "DEBUG"}}}

        # Правило действует: оптовый ключ до оркестратора не доходит.
        assert resolve_recipe_section(section, ORCHESTRATOR_PROCESS_NAME) == {}
        # Override возвращает прежнюю семантику — значит правило и есть разница.
        assert resolve_recipe_section(section, ORCHESTRATOR_PROCESS_NAME, include_defaults=True) == {
            "log_level": "ERROR"
        }
        # И то же правило НЕ задевает обычный процесс.
        assert resolve_recipe_section(section, "camera_0") == {"log_level": "DEBUG"}

    def test_switch_reports_own_layer_separately_from_broadcast(self, pm_with_real_logger) -> None:
        """«Раздал детям» и «применил себе» — разные утверждения в ответе switch'а.

        Пришёл на смену «маяку» `test_current_behavior_switch_does_not_deliver_to_pm`,
        который был зелёным до правки Task 5.13 и красным после.

        Стережёт ровно тот разрыв, которым дефект и жил: до 5.13 рассылка детям
        шла успешно (`broadcast_reached` > 0) при том, что сам оркестратор своей
        дольки не применял. Слей эти два факта в одно поле — и разрыв снова
        станет ненаблюдаемым, а ответ команды будет отчитываться за намерение,
        выдавая его за доставку.
        """
        pm, _ = pm_with_real_logger

        resp = pm.apply_topology(
            {
                "processes": [],
                "wires": [],
                "observability": {"processes": {"ProcessManager": {"log_level": "DEBUG"}}},
            }
        )

        reset = (resp or {}).get("observability_session_reset") or {}
        # Свой слой назван отдельным полем и содержит именно то, что применено.
        assert reset.get("orchestrator_recipe_keys") == ["log_level"]
        # И он ДЕЙСТВИТЕЛЬНО применён к живым менеджерам, а не только объявлен.
        assert _level(pm) == "DEBUG"
