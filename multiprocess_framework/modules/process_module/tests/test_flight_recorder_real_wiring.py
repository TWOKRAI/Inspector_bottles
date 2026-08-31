# -*- coding: utf-8 -*-
"""Ф5 (5.1) — дамп на НАСТОЯЩЕЙ проводке: пять дорог ручки и живой рецепт.

Соседний ``test_flight_recorder_hazards.py`` судит механизм — что он делает,
когда ему подсунуть циклическую ссылку, восемь потоков или сломанную ФС. Здесь
судится ДОРОГА: доезжает ли ручка до живого объекта каждым из способов, которыми
её крутят, и поднимается ли кольцо на боевом рецепте.

Разделение не косметическое. Находка №1 задачи 4.1 была ровно такой: ручка
действовала через ``config.reload`` и НЕ действовала через правку файла, при том
что обе дороги отвечали «применено», а все тесты механизма были зелёными. Дубль
такого не ловит по построению — он получает готовый объект из фикстуры.

Тесты дорогие и потому по одному на дорогу.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    LAYER_APP,
    process_observability_layers,
    resolve_recipe_section,
)
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.managers.observability_flight import flight_plane_report
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    make_observability_on_reload,
)
from multiprocess_framework.modules.process_module.managers.observability_ttl import sweep_session_ttl
from multiprocess_framework.modules.process_module.plugins.base import PluginContext

RING = "flight_ring"

#: Боевой рецепт стенда — тот самый, на котором снимается живая приёмка.
RECIPE = (
    Path(__file__).resolve().parents[4] / "multiprocess_prototype" / "backend" / "topology" / "inspection_full.yaml"
)


class _Cm:
    """Реестр обработчиков: `CommandManager` для команд — это он и есть."""

    def __init__(self) -> None:
        self.handlers: Dict[str, Any] = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler


def _logger_config_from_section(observability: Dict[str, Any], tmp_path: Path) -> Dict[str, Any]:
    """Конфиг логгера ТОЙ ЖЕ сборкой, что на boot: база L0 + раскрытая секция.

    Не ``expand_observability(section)["logger"]`` в одиночку: раскрытая секция
    несёт ЧАСТИЧНЫЙ словарь каналов (``{flight_ring: …}``), а полный набор
    приходит из машинной базы и домерживается. Возьми тест только раскрытую
    секцию — у логгера не оказалось бы ни ``system_file``, ни ``messages_file``,
    маршруты скоупов упирались бы в несуществующие имена, и харнесс отличался бы
    от прода ровно там, где судится маршрут кольца.
    """
    from multiprocess_framework.modules.process_module.configs.managers_config import merge_managers
    from multiprocess_framework.modules.process_module.configs.observability_config import expand_observability
    from multiprocess_framework.modules.process_module.managers.observability_reload import base_managers_payload

    base = base_managers_payload(str(tmp_path))
    cfg = merge_managers(base.get("logger", {}), expand_observability(observability)["logger"])
    cfg["app_name"] = "flight"
    cfg["log_directory"] = str(tmp_path)
    return cfg


def _boot(tmp_path: Path, observability: Dict[str, Any], name: str = "inspector"):
    """Настоящий процесс с настоящим логгером, поднятый ИЗ СЕКЦИИ наблюдаемости.

    Секция едет слоем L1 (``observability_app``) — тем же ключом, которым её
    кладёт ассемблер. Логгер собирается из раскрытой секции, а не из рукописного
    словаря: рукописный доказал бы, что тест умеет писать конфиг логгера.
    """
    proc = ProcessModule(name, config={"observability_app": observability})
    logger_cfg = _logger_config_from_section(observability, tmp_path)
    logger = LoggerManager(manager_name="FlightLog", config=logger_cfg, process=proc)
    logger.initialize()
    proc.logger_manager = logger
    proc.register_manager("logger", logger, enabled=True)
    proc.command_manager = _Cm()
    proc._wire_observability_hub()
    BuiltinCommands(proc).register()
    ctx = PluginContext(services=proc, plugin_name="robot_control")
    return proc, ctx, logger


def _stand_section(process_name: str = "inspector") -> Dict[str, Any]:
    """Долька боевого рецепта для процесса — ТЕМ ЖЕ резолвером, что на boot."""
    recipe = yaml.safe_load(RECIPE.read_text(encoding="utf-8"))
    return resolve_recipe_section(recipe.get("observability"), process_name)


def _dumps(tmp_path: Path, name: str = "inspector") -> List[Path]:
    directory = tmp_path / name / "flight"
    return sorted(directory.glob("*.jsonl")) if directory.exists() else []


class TestTheStandRecipeRaisesARealRing:
    """Р5.1-7 против БОЕВОГО файла, а не против выдуманной секции."""

    def test_the_recipe_slice_declares_a_memory_sink_and_routes_it(self) -> None:
        """Ловушка, которую в диффе не видно: без ``type: memory`` поднимется ФАЙЛ.

        Проверяется не «ключ есть», а обе половины сразу — тип и маршрут.
        Объявленный и не смаршрутизированный канал поднят и вечно пуст, а
        файловый канал под тем же именем ``tail()`` не имеет вовсе.
        """
        section = _stand_section()
        assert section["channels"][RING]["type"] == "memory", "без type поднялся бы файловый приёмник"
        assert section["flight"]["sink"] == RING
        routed = [name for name, body in section["scopes"].items() if RING in body["channels"]]
        assert sorted(routed) == ["BUSINESS", "SYSTEM"], "кольцо обязано быть в маршруте, иначе оно пусто"
        for scope, defaults in (("SYSTEM", ("console", "system_file")), ("BUSINESS", ("system_file", "messages_file"))):
            missing = [ch for ch in defaults if ch not in section["scopes"][scope]["channels"]]
            assert not missing, f"ось channels ЗАМЕЩАЮЩАЯ: {scope} потерял бы {missing}"

    def test_the_stand_recipe_end_to_end_produces_a_non_empty_dump(self, tmp_path: Path) -> None:
        """Боевая секция → живой процесс → непустой файл дампа.

        Единственный тест, который упадёт, если рецепт стенда поправят «почти
        правильно»: снимут ``type``, вынут кольцо из скоупов или переименуют
        приёмник, не тронув ``flight.sink``.
        """
        proc, ctx, logger = _boot(tmp_path, _stand_section())
        try:
            ctx.log_info("кадр 1")
            ctx.log_info("кадр 2")

            assert ctx.flight_dump("reject", trace_id="t1") is True

            files = _dumps(tmp_path)
            assert len(files) == 1
            records = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines() if line]
            assert records[0]["ring"]["capacity"] == 500, "ёмкость приехала из рецепта"
            body = files[0].read_text(encoding="utf-8")
            assert "кадр 1" in body and "кадр 2" in body
            assert flight_plane_report(proc)["flight"]["enabled"] is True
        finally:
            logger.shutdown()


class TestTheFiveRoads:
    """Каждая дорога пересборки доносит ручку до ЖИВОГО рекордера — или не доносит."""

    def test_boot_reads_the_section(self, tmp_path: Path) -> None:
        """Дорога 0: сшивка. Без неё boot-конфиг игнорируется молча."""
        proc, _, logger = _boot(tmp_path, {"flight": {"enabled": True, "sink": RING, "keep": 7, "limit": 11}})
        try:
            assert proc.flight_recorder.knobs == (True, RING, 7, 11)
            assert flight_plane_report(proc)["flight"]["declared"] is True
        finally:
            logger.shutdown()

    def test_config_reload_reaches_the_live_recorder_and_is_confirmed(self, tmp_path: Path) -> None:
        """Дорога 1: IPC-команда. Плюс вердикт — ручка без него неотличима от неприменённой.

        Замер 4.1 на живом стенде: ``config_reload_verified`` отвечал
        ``unverifiable`` при ``checked=0`` на всех восьми процессах, потому что
        readback не отдавал секцию. Здесь проверяется и то, и другое.
        """
        proc, _, logger = _boot(tmp_path, _stand_section())
        try:
            handler = proc.command_manager.handlers["config.reload"]

            res = handler({"observability": {"flight": {"keep": 2, "limit": 33}}})

            assert res["success"] is True
            assert res["flight_applied"] == {"enabled": True, "sink": RING, "keep": 2, "limit": 33}
            assert proc.flight_recorder.knobs == (True, RING, 2, 33), "правка обязана дойти до ЖИВОГО объекта"
            assert res["effective"]["flight"]["keep"] == 2, "readback читает рекордер, а не эхо запроса"
            assert res["verified"]["verdict"] == "confirmed", "ручка, которую нельзя подтвердить, бесполезна"
        finally:
            logger.shutdown()

    def test_a_file_edit_reaches_the_live_recorder_too(self, tmp_path: Path) -> None:
        """Дорога 2: правка ФАЙЛА. Это и была находка №1 задачи 4.1, дословно.

        Ручка действовала через ``config.reload`` и не действовала через файл;
        обе дороги отвечали «применено», расхождение молчало.
        """
        proc, _, logger = _boot(tmp_path, _stand_section())
        try:
            from multiprocess_framework.modules.config_module import Config

            on_reload = make_observability_on_reload(
                logger=proc.logger_manager,
                flight_recorder=proc.flight_recorder,
                layers=process_observability_layers(proc),
                layer=LAYER_APP,
                process_name=proc.name,
            )
            on_reload(Config(initial_data={"observability": {"flight": {"enabled": False, "sink": RING, "keep": 4}}}))

            assert proc.flight_recorder.knobs == (False, RING, 4, 0), "правка файла обязана действовать"
        finally:
            logger.shutdown()

    def test_an_expired_session_key_returns_the_policy(self, tmp_path: Path) -> None:
        """Дорога 3: возврат по сроку. Иначе — «следствие без причины».

        Возврат объявлялся бы, а дампы продолжали писаться по истёкшей правке.
        Тот же дефект уже ловили на телеметрии и на отборе широких записей.
        """
        proc, _, logger = _boot(tmp_path, _stand_section())
        try:
            handler = proc.command_manager.handlers["config.reload"]
            handler({"observability": {"flight": {"enabled": False}}, "ttl": 0.01})
            assert proc.flight_recorder.knobs[0] is False, "предпосылка: правка подействовала"

            import time as _t

            _t.sleep(0.05)
            report = sweep_session_ttl(proc)

            assert report is not None and report["success"] is True
            assert proc.flight_recorder.knobs[0] is True, "срок истёк — политика вернулась к слою рецепта"
        finally:
            logger.shutdown()

    def test_introspect_shows_the_live_counters(self, tmp_path: Path) -> None:
        """Дорога 4 (readback): счётчики дампов наблюдаемы там же, где всё остальное."""
        proc, ctx, logger = _boot(tmp_path, _stand_section())
        try:
            ctx.log_info("запись")
            assert ctx.flight_dump("reject") is True
            assert ctx.flight_dump("reject") is True

            res = proc.command_manager.handlers["introspect.observability"]({})
            flight = res["flight"]
        finally:
            logger.shutdown()

        assert flight["declared"] is True
        assert flight["dumps"] == 2
        assert flight["records"] >= 1
        assert flight["last_path"].endswith(".jsonl"), "«а куда оно пишется» отвечается readback'ом"

    def test_introspect_effective_carries_the_live_knobs(self, tmp_path: Path) -> None:
        """Дорога 5 (`effective` у `introspect`): ДЕЙСТВУЮЩИЕ ручки, а не только счётчики.

        Секция `flight` в ответе и секция `flight` в `effective` — РАЗНЫЕ ветки
        кода и разные вопросы: первая говорит «сколько дампов сделано», вторая —
        «какая политика действует сейчас». Инъекция, снявшая рекордер у
        `observability_effective` в этой команде, давала НОЛЬ красных: ручки
        молча исчезали из действующего состояния, а счётчики продолжали
        показываться, и ответ выглядел полным.

        Соседний readback (`config.reload`, после применения) сторожится своим
        тестом выше — здесь именно читающая команда, которую опрашивает пульт.
        """
        proc, _, logger = _boot(tmp_path, {"flight": {"enabled": True, "sink": RING, "keep": 6, "limit": 12}})
        try:
            res = proc.command_manager.handlers["introspect.observability"]({})
        finally:
            logger.shutdown()

        assert res["effective"]["flight"] == {"enabled": True, "sink": RING, "keep": 6, "limit": 12}


class TestTheDumpLandsBesideTheJournal:
    """Р5.1-8: путь резолвится ДОРОГОЙ ЖУРНАЛА, а не от cwd."""

    def test_the_dump_is_a_sibling_of_the_process_log_directory(self, tmp_path: Path) -> None:
        """Урок 3.3 в исполнении: относительный путь от cwd уносил файлы в дерево репо.

        Проверяется отношение к каталогу ПРОЦЕССА, а не совпадение строки: базу
        считает одна функция (``process_log_directory``), и тест обязан судить
        её результат, а не свою копию вычисления.
        """
        proc, ctx, logger = _boot(tmp_path, _stand_section())
        try:
            assert ctx.flight_dump("reject") is True
            path = Path(flight_plane_report(proc)["flight"]["last_path"])
        finally:
            logger.shutdown()

        assert path.parent == tmp_path / "inspector" / "flight"
        assert path.is_absolute(), "относительный путь резолвился бы от cwd — ровно урок 3.3"
        assert Path.cwd() not in path.parents or tmp_path.is_relative_to(Path.cwd())


class TestTheProtocolAndTheAttributeAgree:
    """Р5.1-2: порт объявлен и атрибут есть — иначе штатный процесс перестаёт удовлетворять протоколу."""

    def test_a_process_without_wiring_still_satisfies_the_protocol(self) -> None:
        from multiprocess_framework.modules.process_module.plugins.interfaces import IProcessServices

        proc = ProcessModule("bare")
        assert proc.flight_recorder is None, "атрибут КЛАССА обязан существовать до сшивки"
        assert isinstance(proc, IProcessServices), "объявление порта без атрибута ломает dev-проверку"

    def test_the_attribute_name_matches_the_constant(self) -> None:
        """Две рукописные копии имени разъезжаются молча — этим уже был дефект Н-9.

        Имя сверяется с ПРОТОКОЛОМ и с классом, а не с литералом в тесте:
        сверка литерала с литералом остаётся зелёной при любом переименовании.
        """
        from multiprocess_framework.modules.process_module.managers.observability_flight import (
            FLIGHT_RECORDER_ATTR,
        )
        from multiprocess_framework.modules.process_module.plugins.interfaces import IProcessServices

        assert hasattr(ProcessModule, FLIGHT_RECORDER_ATTR)
        assert FLIGHT_RECORDER_ATTR in {name for name in dir(IProcessServices) if not name.startswith("_")}


@pytest.mark.parametrize("process_name", ["camera_0", "gui", "storage"])
def test_the_stand_recipe_touches_only_the_inspector(process_name: str) -> None:
    """Кольцо на КАЖДОМ процессе — это 500 записей × 7 процессов задаром.

    Форма ``processes:`` без ``defaults`` выбрана именно ради этого, и свойство
    судится, а не подразумевается: одна строка ``defaults:`` в рецепте развернула
    бы кольцо всем.
    """
    assert _stand_section(process_name) == {}
