# -*- coding: utf-8 -*-
"""Task 2.1 (находка Н-4): содержимое ``telemetry`` судится ДО записи в слой.

**Что было.** Плоскость телеметрии живёт в тех же слоях L1/L2/L3, что и логи, но её
содержимое не судил никто: ``validate_layer_section`` про ключ ``telemetry`` не знала,
а ``ObservabilityConfig`` принимает лишние ключи молча. Разведка на этом харнессе
(2026-08-11) дала три разных исхода, и ни один не был отказом до записи:

============================ ================================================
Ввод                         Что происходило
============================ ================================================
``publish`` с мусором        ``success=false`` — но мусор УЖЕ в L3. Отказ ловил
                             Pydantic у получателя, то есть после записи
``throttle`` с мусором       ``success=true``, правило доехало до живого
                             ``ThrottleMiddleware``, стор падал на ВТОРОЙ записи
опечатка в имени под-секции  без секции ``observability`` рядом — тихий no-op;
                             вместе с ней — ключ ложился в L3 под срок
============================ ================================================

**Главное следствие — на соседе.** Отравленный слой ломал не свою плоскость:
после отказа команды телеметрии следующий, ни в чём не виноватый
``config.reload {"observability": {"log_level": "DEBUG"}}`` отвечал
``reconfigure failed: … TelemetryPublishConfig``. Оператор, который телеметрию не
трогал, не мог сменить уровень логов 300 секунд — до истечения срока правки,
которой ему официально ОТКАЗАЛИ. Это и закрепляет :class:`TestNeighbourNotBlocked`;
остальные классы — пары ОТКАЗ/ПРИЁМ на обеих дорогах и на двери самого слоя.

Тестов на «мусор доезжает до получателя» здесь нет намеренно: доказывать надо
границу, а не то, что Pydantic умеет ругаться.
"""

from __future__ import annotations

import math

import pytest

from multiprocess_framework.modules.process_module.configs.observability_layers import (
    LAYER_APP,
    LAYER_SESSION,
    process_observability_layers,
    validate_layer_section,
    validate_telemetry_section,
)
from multiprocess_framework.modules.state_store_module.middleware.throttle import ThrottleMiddleware

from .test_telemetry_commands import _make

#: Формы мусора, которые обязана отвергнуть КАЖДАЯ дорога. Пара «секция → кусок
#: адреса, который оператор обязан увидеть в отказе»: без адреса отказ заставляет
#: искать опечатку глазами по всей секции — ровно то, чего задача 2.1 не хочет.
GARBAGE = [
    pytest.param(
        {"publish": {"default_interval_sec": "быстро"}}, "telemetry.publish.default_interval_sec", id="publish-скаляр"
    ),
    pytest.param(
        {"publish": {"metrics": {"fps": {"enabled": "может быть"}}}},
        "telemetry.publish.metrics.fps.enabled",
        id="publish-вложенный",
    ),
    pytest.param({"publish": {"default_interval_sec": -5.0}}, "telemetry.publish", id="publish-отрицательный"),
    pytest.param({"publish": "включи"}, "telemetry.publish", id="publish-не-словарь"),
    pytest.param(
        {"throttle": {"processes.**.state.fps": "часто"}},
        "telemetry.throttle['processes.**.state.fps']",
        id="throttle-строка",
    ),
    pytest.param(
        {"throttle": {"processes.**.state.fps": -1.0}},
        "telemetry.throttle['processes.**.state.fps']",
        id="throttle-отрицательный",
    ),
    pytest.param(
        {"throttle": {"processes.**.state.fps": True}},
        "telemetry.throttle['processes.**.state.fps']",
        id="throttle-bool",
    ),
    pytest.param(
        {"throttle": {"processes.**.state.fps": math.inf}},
        "telemetry.throttle['processes.**.state.fps']",
        id="throttle-inf",
    ),
    pytest.param({"throttle": "помедленнее"}, "telemetry.throttle", id="throttle-не-словарь"),
    pytest.param({"throttle": {"__clear__": "да"}}, "telemetry.throttle['__clear__']", id="clear-не-true"),
    pytest.param({"pubish": {"tick_sec": 1.0}}, "telemetry.pubish", id="опечатка-в-под-секции"),
    pytest.param("выключи", "telemetry", id="секция-не-словарь"),
]

#: Законные формы. Список не декоративный: ровно на них ломается «отвергать всё,
#: что не понял» — ``publish: null`` снимает гейт, ``None`` у паттерна снимает
#: правило, ``__clear__: true`` читает файловый watcher.
VALID = [
    pytest.param({"publish": {"metrics": {"fps": {"enabled": False}}}}, id="publish-словарь"),
    pytest.param({"publish": None}, id="publish-null-снимает-гейт"),
    pytest.param({"publish": {}}, id="publish-пустой-владеет"),
    pytest.param({"throttle": {"processes.**.state.fps": 2.0}}, id="throttle-число"),
    pytest.param({"throttle": {"processes.**.state.fps": 0}}, id="throttle-ноль-блокировка"),
    pytest.param({"throttle": {"processes.**.state.fps": None}}, id="throttle-null-снимает-правило"),
    pytest.param({"throttle": {"__clear__": True}}, id="throttle-маркер-очистки"),
    pytest.param({"throttle": {}}, id="throttle-пустая-дельта"),
    pytest.param({}, id="пустая-секция"),
    pytest.param(None, id="секция-отсутствует"),
]


def _session(svc) -> dict:
    return process_observability_layers(svc).session


class TestValidatorItself:
    """Правило само по себе — до дорог, чтобы отказ дороги нельзя было спутать с чужим."""

    @pytest.mark.parametrize("section,address", GARBAGE)
    def test_garbage_is_refused_with_the_address(self, section, address) -> None:
        with pytest.raises(ValueError) as exc:
            validate_telemetry_section(section, layer=LAYER_SESSION)
        assert address in str(exc.value), f"в отказе нет адреса ключа: {exc.value}"

    @pytest.mark.parametrize("section", VALID)
    def test_valid_forms_pass(self, section) -> None:
        validate_telemetry_section(section, layer=LAYER_SESSION)

    def test_all_problems_are_named_at_once(self) -> None:
        """Две ошибки — два адреса в одном отказе.

        Иначе оператор чинит секцию по одной строке за команду: отказ, правка,
        снова отказ. Первая попавшаяся проблема — это про удобство валидатора,
        а не про того, кто читает.
        """
        with pytest.raises(ValueError) as exc:
            validate_telemetry_section(
                {"publish": {"default_interval_sec": "быстро"}, "throttle": {"p.**.fps": "часто"}},
                layer=LAYER_SESSION,
            )
        text = str(exc.value)
        assert "telemetry.publish.default_interval_sec" in text
        assert "telemetry.throttle['p.**.fps']" in text

    def test_throttle_address_is_not_dotted(self) -> None:
        """Адрес правила — скобками, а не точкой (хазард автора).

        Точечная форма ``telemetry.throttle.processes.**.state.fps`` — это ровно
        тот путь, который слои ЗАПРЕЩАЮТ (``_reject_path_inside_opaque``): точки
        внутри паттерна часть имени. Назвав его оператору, отказ подсказывал бы
        команду, которая тут же отказала бы снова, уже по другой причине.
        """
        with pytest.raises(ValueError) as exc:
            validate_telemetry_section({"throttle": {"processes.**.state.fps": "часто"}}, layer=LAYER_SESSION)
        assert "telemetry.throttle.processes" not in str(exc.value)

    def test_layer_is_named_in_the_text(self) -> None:
        """Тем же словом, что у соседней плоскости, — читателю не различать двух форм."""
        with pytest.raises(ValueError) as exc:
            validate_telemetry_section({"publish": "мусор"}, layer=LAYER_APP)
        assert f"слой {LAYER_APP} отвергнут" in str(exc.value)


class TestDoorTelemetryCommand:
    """Дорога 1: ``telemetry.reconfigure`` / ``telemetry.set``."""

    @pytest.mark.parametrize(
        "section,address",
        # Опечатка в имени под-секции этой дорогой не проходит вовсе: команда
        # собирает секцию по СВОИМ параметрам (`publish`/`throttle`), и незнакомое
        # имя до валидатора не доезжает — у неё свой, более ранний отказ
        # (см. `test_unknown_subsection_has_its_own_refusal`).
        [p for p in GARBAGE if isinstance(p.values[0], dict) and set(p.values[0]) <= {"publish", "throttle"}],
    )
    def test_refuses_before_touching_the_layer(self, section, address) -> None:
        svc, cm = _make(throttle=ThrottleMiddleware({}))
        res = cm.dispatch("telemetry.reconfigure", dict(section))
        assert res["success"] is False
        # Task 2.2 разделила ответственность, и это видно ровно здесь: «не словарь»
        # на КОМАНДНОЙ дороге ловит проверка типов параметра (контракт объявляет
        # `Optional[Dict]`) и называет поле коротким именем; содержимое словаря —
        # по-прежнему валидатор секции, с полным адресом ключа. Обе дают отказ до
        # записи, поэтому проверяем общее: имя виновника в тексте и нетронутый слой.
        guilty = next(iter(section))  # publish | throttle
        assert guilty in res["reason"], res["reason"]
        assert _session(svc) == {}, "отказ пришёл ПОВЕРХ изменённого слоя"

    def test_unknown_subsection_has_its_own_refusal(self) -> None:
        """Опечатка в имени под-секции: отказ есть, и он называет известные имена."""
        svc, cm = _make()
        res = cm.dispatch("telemetry.reconfigure", {"pubish": {"tick_sec": 1.0}})
        assert res["success"] is False
        assert "publish" in res["reason"] and "throttle" in res["reason"]
        assert _session(svc) == {}

    def test_live_throttle_is_untouched_by_a_refusal(self) -> None:
        """Отказ не имеет права оставить правило в живом троттле.

        До задачи мусорный интервал доезжал до ``ThrottleMiddleware`` и ронял стор
        на второй записи по этому пути — ``TypeError: unsupported operand type(s)
        for /: 'float' and 'str'``.
        """
        throttle = ThrottleMiddleware({"уже.было": 1.0})
        svc, cm = _make(throttle=throttle)
        res = cm.dispatch("telemetry.reconfigure", {"throttle": {"processes.**.state.fps": "часто"}})
        assert res["success"] is False
        assert throttle.rules == {"уже.было": 1.0}

    @pytest.mark.parametrize("section", [p for p in VALID if isinstance(p.values[0], dict) and p.values[0]])
    def test_valid_sections_are_applied(self, section) -> None:
        svc, cm = _make(throttle=ThrottleMiddleware({}))
        res = cm.dispatch("telemetry.reconfigure", dict(section))
        assert res["success"] is True, res.get("reason")
        assert _session(svc), "принято, но в слое ничего не осталось"


class TestDoorConfigReload:
    """Дорога 2: ``config.reload`` — и одна, и вместе с секцией observability."""

    @pytest.mark.parametrize("section,address", [p for p in GARBAGE if isinstance(p.values[0], dict)])
    def test_refuses_telemetry_alone(self, section, address) -> None:
        svc, cm = _make()
        res = cm.dispatch("config.reload", {"telemetry": dict(section)})
        assert res["success"] is False
        assert address in res["reason"]
        assert _session(svc) == {}

    @pytest.mark.parametrize("section,address", [p for p in GARBAGE if isinstance(p.values[0], dict)])
    def test_refuses_together_with_observability(self, section, address) -> None:
        """Та же секция рядом с observability — тот же отказ.

        Раньше именно здесь исходы расходились: соседняя секция включала другую
        ветку обработчика, и опечатка в имени под-секции ложилась в L3 под срок.
        Ответ на один и тот же ввод не имеет права зависеть от того, что приехало
        рядом.
        """
        svc, cm = _make()
        res = cm.dispatch(
            "config.reload",
            {"observability": {"log_level": "DEBUG"}, "telemetry": dict(section)},
        )
        assert res["success"] is False
        assert address in res["reason"]
        assert _session(svc) == {}, "секция observability доехала до слоя, а телеметрия отказала"

    def test_valid_pair_applies_both_planes(self) -> None:
        svc, cm = _make()
        res = cm.dispatch(
            "config.reload",
            {
                "observability": {"log_level": "DEBUG"},
                "telemetry": {"publish": {"metrics": {"fps": {"enabled": False}}}},
            },
        )
        assert res["success"] is True, res.get("reason")
        session = _session(svc)
        assert session["log_level"] == "DEBUG"
        assert session["telemetry"]["publish"]["metrics"]["fps"]["enabled"] is False

    def test_refusal_from_file_names_the_app_layer(self, tmp_path) -> None:
        """Файловая дорога отвергает тем же правилом и называет СВОЙ слой."""
        import yaml

        path = tmp_path / "system.yaml"
        path.write_text(
            yaml.safe_dump({"observability": {"log_level": "INFO"}, "telemetry": {"throttle": {"p.**.fps": "часто"}}}),
            encoding="utf-8",
        )
        svc, cm = _make()
        res = cm.dispatch("config.reload", {"path": str(path)})
        assert res["success"] is False
        assert f"слой {LAYER_APP} отвергнут" in res["reason"]
        assert "telemetry.throttle['p.**.fps']" in res["reason"]


class TestDoorLayerBoundary:
    """Дверь самого слоя: ``session_set`` и ``replace_layer`` (через validate_layer_section)."""

    def test_session_set_of_the_opaque_leaf_is_judged(self) -> None:
        svc, _cm = _make()
        layers = process_observability_layers(svc)
        with pytest.raises(ValueError, match=r"telemetry\.throttle"):
            layers.session_set("telemetry.throttle", {"p.**.fps": "часто"}, 60, origin="тест")
        assert layers.session == {}

    def test_replace_layer_body_with_telemetry_is_judged(self) -> None:
        svc, _cm = _make()
        layers = process_observability_layers(svc)
        with pytest.raises(ValueError, match=r"telemetry\.publish"):
            layers.replace_layer(LAYER_APP, {"log_level": "INFO", "telemetry": {"publish": "мусор"}}, origin="тест")
        assert layers.app in (None, {})

    def test_neighbour_keys_of_the_same_body_still_judged(self) -> None:
        """Снятие ключа telemetry не имеет права ослепить проверку соседей.

        Валидатор вырезает ``telemetry`` перед схемой наблюдаемости — если бы он
        вырезал и возвращался, ``log_level: "БОЛТОВНЯ"`` рядом проехал бы.
        """
        with pytest.raises(ValueError, match="log_level"):
            validate_layer_section(
                {"log_level": "БОЛТОВНЯ", "telemetry": {"publish": {}}},
                layer=LAYER_SESSION,
            )

    def test_body_of_only_telemetry_is_judged(self) -> None:
        """Тело из ОДНОЙ телеметрии: после выреза секция пуста — и это не «нечего судить»."""
        with pytest.raises(ValueError, match=r"telemetry\.publish"):
            validate_layer_section({"telemetry": {"publish": "мусор"}}, layer=LAYER_SESSION)


class TestNeighbourNotBlocked:
    """Главное следствие Н-4: отравленный слой ломал СОСЕДНЮЮ плоскость."""

    def test_refused_telemetry_does_not_block_a_later_log_level_change(self) -> None:
        svc, cm = _make()
        refused = cm.dispatch("telemetry.reconfigure", {"publish": {"default_interval_sec": "быстро"}})
        assert refused["success"] is False

        neighbour = cm.dispatch("config.reload", {"observability": {"log_level": "DEBUG"}})
        assert neighbour["success"] is True, neighbour.get("reason")
        assert _session(svc)["log_level"] == "DEBUG"

    def test_refused_telemetry_does_not_block_a_later_valid_telemetry_edit(self) -> None:
        svc, cm = _make()
        cm.dispatch("telemetry.reconfigure", {"publish": {"default_interval_sec": "быстро"}})
        again = cm.dispatch("telemetry.reconfigure", {"publish": {"metrics": {"fps": {"enabled": False}}}})
        assert again["success"] is True, again.get("reason")


class TestUnknownNamesInsideTelemetry:
    """Задача 5.7 — блокер Н2-4 переприёмки раунда 2.

    Задача 5.4 закрыла класс «незнакомое ИМЯ ключа» у трёх плоскостей и передала
    ключ ``telemetry`` сюда — а здесь судились только имена ПОД-СЕКЦИЙ и ЗНАЧЕНИЯ.
    Воспроизведено живьём до правки::

        config.reload {"telemetry": {"publish": {"нет_такой_метрики": {"interval_sec": 5.0}}}}
        → success=true, verified=None,
          session_keys=['telemetry.publish.нет_такой_метрики.interval_sec']  # со сроком 254 с

    Граница названа: имя под ``metrics`` — это ИМЯ МЕТРИКИ, и незнакомое имя там
    ЗАКОННО (конфиг сужает набор, а не объявляет белый список). Его судит голосом
    ``unknown_metrics``, а не отказом.
    """

    BAD_NAMES = [
        (
            {"publish": {"нет_такой_метрики": {"interval_sec": 5.0}}},
            "telemetry.publish.нет_такой_метрики",
        ),
        ({"publish": {"deafult_interval_sec": 2.0}}, "telemetry.publish.deafult_interval_sec"),
        ({"publish": {"metrics": {"fps": {"enabld": True}}}}, "telemetry.publish.metrics.fps.enabld"),
    ]

    @pytest.mark.parametrize("section,address", BAD_NAMES)
    def test_unknown_field_is_refused_with_its_address(self, section, address) -> None:
        with pytest.raises(ValueError) as exc:
            validate_telemetry_section(section, layer=LAYER_SESSION)
        assert address in str(exc.value), exc.value

    @pytest.mark.parametrize("section,address", BAD_NAMES)
    def test_the_command_refuses_and_nothing_lands_in_the_layer(self, section, address) -> None:
        svc, cm = _make()
        res = cm.dispatch("config.reload", {"telemetry": section})
        assert res["success"] is False, res
        assert address in str(res.get("reason", "")), res
        assert _session(svc) == {}, "мусорное имя всё равно легло в L3"

    def test_a_metric_name_is_legal_and_only_voiced(self) -> None:
        """Пара к отказу: страж, срабатывающий всегда, запретил бы новую метрику.

        Незнакомое имя метрики — не опечатка по построению. Отказ здесь сломал бы
        forward-compat: метрика из будущей версии в старом процессе валила бы reload.
        """
        validate_telemetry_section(
            {"publish": {"metrics": {"будущая_метрика": {"enabled": True}}}},
            layer=LAYER_SESSION,
        )

    def test_legal_fields_pass_the_same_door(self) -> None:
        validate_telemetry_section(
            {"publish": {"default_interval_sec": 2.0, "tick_sec": 1.0, "metrics": {"fps": {"enabled": False}}}},
            layer=LAYER_SESSION,
        )
        validate_telemetry_section({"publish": None}, layer=LAYER_SESSION)
        validate_telemetry_section({"throttle": {"processes.**.state.fps": 2.0}}, layer=LAYER_SESSION)

    def test_telemetry_reload_carries_a_verdict_instead_of_silence(self) -> None:
        """Вторая половина Н2-4: было `verified=None` — ни одного из трёх исходов.

        Честный ответ — ``unverifiable`` с перечнем запрошенных путей: readback
        плоскости телеметрии не отдаётся, значит подтверждать нечем, и это ОТВЕТ,
        а не молчание. Форма — та же, что у соседней секции.
        """
        svc, cm = _make()
        res = cm.dispatch("config.reload", {"telemetry": {"publish": {"default_interval_sec": 2.0}}})
        assert res["success"] is True, res.get("reason")
        verified = res.get("verified")
        assert verified is not None, "телеметрийная правка снова без вердикта"
        assert verified["verdict"] == "unverifiable", verified
        assert "telemetry.publish.default_interval_sec" in verified["unverifiable"], verified
