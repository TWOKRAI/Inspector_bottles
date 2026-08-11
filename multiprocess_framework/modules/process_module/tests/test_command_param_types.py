# -*- coding: utf-8 -*-
"""Task 2.2 (находка Н-5, решение Р-3а): типы параметров судятся ДО хендлера.

**Что было.** Контракт объявляет тип, но читала его только warn-мидлварь: она
писала предупреждение и ПРОПУСКАЛА сообщение дальше. Хендлер получал мусор и
ломался на нём уже своим способом. Разведка перед правкой (2026-08-11) прошла по
всей поверхности наблюдаемости и нашла три исхода, из которых находка называла один:

============================================== ==========================================
Ввод                                           Что происходило
============================================== ==========================================
``introspect.observability {"resolve": true}``  ``list(True)`` → ``Dispatch failed:
                                                'bool' object is not iterable`` (Н-5)
``config.reload {"observability_reset": true}`` тот же ``TypeError`` — **второе место
                                                того же класса**, находкой не названное
``config.reload
{"observability_session_clear": "net"}``        ``bool("net")`` истинно → **весь слой L3
                                                стёрт**, вместе с правкой оператора на
                                                600 с. Слово «нет» означало «да, снеси»
``introspect.observability {"resolve": {...}}`` ``success=true``: словарь итерировался по
                                                ключам, ответ выглядел осмысленным
============================================== ==========================================

Три класса, а не один: **падение**, **тихое приведение с разрушительным эффектом** и
**тихая бессмыслица**. Общего у них ровно одно — тип не совпал с объявленным, и никто
этого не сказал.

Суд здесь идёт **классом**: :class:`TestEveryTypedCommandRefusesWrongTypes` проходит по
каждой команде охвата и каждому её объявленному полю. Точечный тест на ``resolve``
закрыл бы ``resolve``; ровно так Н-5 и появилась — после того, как major-16 закрыли
«по именам».
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.commands.builtin_commands import (
    OBSERVABILITY_TYPED_COMMANDS,
    BuiltinCommands,
)
from multiprocess_framework.modules.process_module.commands.command_contracts import (
    BUILTIN_COMMAND_CONTRACTS,
    _adapter_for,
    _type_str,
    validated_params,
)
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    process_observability_layers,
)
from multiprocess_framework.modules.state_store_module.middleware.throttle import ThrottleMiddleware

from .test_telemetry_commands import _FakeLogger, _FakeServices


class _LoggerWithResolve(_FakeLogger):
    """Логгер, у которого ЕСТЬ ``resolve_rule``.

    Без него ветка разбора имени не исполняется вовсе, и тест на ``resolve``
    доказывал бы отсутствие получателя, а не проверку типа.
    """

    def resolve_rule(self, name: str) -> dict:
        return {"name": name, "level": "INFO"}


def _wired():
    svc = _FakeServices(logger=_LoggerWithResolve(), throttle=ThrottleMiddleware({}))
    bc = BuiltinCommands(svc)
    bc._register_observability_commands()
    bc._register_introspect_commands()
    return svc, svc.command_manager.handlers


#: Значение заведомо ЧУЖОГО типа для каждого объявленного. Правильность выбора не
#: принимается на веру — :func:`_wrong_value_for` сверяет его с тем же адаптером,
#: которым судит рантайм, и пропускает поле, для которого «мусор» оказался годным.
_WRONG_BY_TYPE = {
    "int": "не число",
    "float": "не число",
    "bool": "ага",
    "str": True,
    "Dict": "не словарь",
    "List": True,
}


def _wrong_value_for(schema, field):
    """Заведомо негодное значение поля — или ``None``, если подобрать не удалось."""
    declared = _type_str(schema.model_fields[field].annotation)
    for prefix, candidate in _WRONG_BY_TYPE.items():
        if declared.startswith(prefix):
            try:
                _adapter_for(schema, field).validate_python(candidate)
            except Exception:  # noqa: BLE001 — именно этого и ждём
                return candidate
            return None
    return None


def _typed_cases():
    """(команда, поле, негодное значение) по всему охвату — вход параметризации."""
    cases = []
    for command in sorted(OBSERVABILITY_TYPED_COMMANDS):
        schema = BUILTIN_COMMAND_CONTRACTS.get(command)
        if schema is None:
            continue
        for field in schema.model_fields:
            bad = _wrong_value_for(schema, field)
            if bad is not None:
                cases.append(pytest.param(command, field, bad, id=f"{command}:{field}"))
    return cases


class TestScopeIsRealAndNotVacuous:
    """Сперва показать, что охват существует и судится, — потом судить."""

    def test_every_command_in_scope_has_a_contract(self) -> None:
        """Команда охвата без контракта = гарантия, молча выключенная для неё.

        Ровно так и было до задачи: ``telemetry.reconfigure``,
        ``observability.sink.tail`` и ``logger.sink.tail`` жили в поверхности
        наблюдаемости без единой объявленной формы — их не видели ни мидлварь, ни
        оракул A1, ни карточка процесса.
        """
        without = sorted(c for c in OBSERVABILITY_TYPED_COMMANDS if c not in BUILTIN_COMMAND_CONTRACTS)
        assert not without, f"команды охвата без контракта: {without} — для них проверка типов не делает ничего"

    def test_every_command_in_scope_is_registered_by_the_process(self) -> None:
        """Имя в охвате, которого нет среди зарегистрированных, ничего не сторожит."""
        _svc, handlers = _wired()
        missing = sorted(c for c in OBSERVABILITY_TYPED_COMMANDS if c not in handlers)
        assert not missing, f"в охвате есть незарегистрированные имена: {missing}"

    def test_every_command_in_scope_contributes_at_least_one_case(self) -> None:
        """Каждая команда охвата обязана давать случай — иначе она уходит МОЛЧА.

        Первая редакция этого теста стояла на порогах («≥25 случаев, ≥8 команд»),
        и инъекция показала, чего они стоят: сними три контракта — и тридцать с
        лишним параметризованных случаев ПРОПАДАЮТ из сбора, а не краснеют.
        59 → 47, оба порога пройдены, класс перестал судиться. Порог, взятый
        там, где кандидаты не расходятся, не проверяет ничего; судить надо
        поимённо.
        """
        covered = {c.values[0] for c in _typed_cases()}
        uncovered = sorted(OBSERVABILITY_TYPED_COMMANDS - covered)
        assert not uncovered, (
            f"у команд охвата не подобрано ни одного случая: {uncovered}. "
            f"Либо снят контракт, либо генератор мусора не знает их типов — "
            f"в обоих случаях класс для них не судится."
        )


class TestEveryTypedCommandRefusesWrongTypes:
    """Класс целиком: чужой тип в любое объявленное поле — адресный отказ."""

    @pytest.mark.parametrize("command,field,bad", _typed_cases())
    def test_wrong_type_is_refused_with_field_and_expected_type(self, command, field, bad) -> None:
        _svc, handlers = _wired()
        res = handlers[command]({field: bad})
        assert res["success"] is False, f"{command}.{field} принял {bad!r}"
        reason = res["reason"]
        assert field in reason, f"в отказе нет имени поля: {reason}"
        expected = _type_str(BUILTIN_COMMAND_CONTRACTS[command].model_fields[field].annotation)
        assert expected in reason, f"в отказе нет ожидаемого типа {expected!r}: {reason}"
        assert res["command"] == command


class TestTheThreeFoundOutcomes:
    """Поимённо — три исхода разведки, чтобы регресс был назван, а не посчитан."""

    @pytest.mark.parametrize("bad", [True, 12, {"имя": 1}], ids=["bool", "int", "dict"])
    def test_resolve_no_longer_reaches_the_handler(self, bad) -> None:
        """Н-5 дословно: ``list(bad)`` до правки давало TypeError либо бессмыслицу."""
        _svc, handlers = _wired()
        res = handlers["introspect.observability"]({"resolve": bad})
        assert res["success"] is False
        assert "resolve" in res["reason"]

    def test_observability_reset_is_the_second_place_of_the_same_class(self) -> None:
        """Второй ``list(True)`` — на другой команде и другом поле."""
        _svc, handlers = _wired()
        res = handlers["config.reload"]({"observability_reset": True})
        assert res["success"] is False
        assert "observability_session_clear" not in res["reason"], "назван сосед, а не виновник"
        assert "observability_reset" in res["reason"]

    def test_a_word_meaning_no_no_longer_wipes_the_layer(self) -> None:
        """Главное следствие: ``bool("net")`` истинно, и слой L3 стирался целиком."""
        svc, handlers = _wired()
        layers = process_observability_layers(svc)
        layers.session_set("log_level", "DEBUG", 600, origin="оператор")

        res = handlers["config.reload"]({"observability_session_clear": "net"})
        assert res["success"] is False
        assert "observability_session_clear" in res["reason"]
        assert layers.session == {"log_level": "DEBUG"}, "отказ пришёл поверх стёртого слоя"

    def test_the_word_no_is_understood_as_false(self) -> None:
        """Приведение — часть договора: ``"no"`` значит «нет», а не «снеси всё».

        Это не косметика: до правки ЛЮБАЯ непустая строка в этом поле означала
        «снести слой», то есть ответ «нет» делал ровно противоположное.
        """
        svc, handlers = _wired()
        layers = process_observability_layers(svc)
        layers.session_set("log_level", "DEBUG", 600, origin="оператор")

        res = handlers["config.reload"](
            {"observability": {"errors": {"level": "WARNING"}}, "observability_session_clear": "no"}
        )
        assert res["success"] is True, res.get("reason")
        assert res.get("reset") is None, "слой всё-таки сброшен"
        assert layers.session["log_level"] == "DEBUG", "правка оператора не пережила «нет»"


class TestValidFormsStillWork:
    """Приёмная сторона — иначе «отвергать всё» прошло бы все проверки выше."""

    @pytest.mark.parametrize(
        "args",
        [
            {"resolve": "camera"},
            {"resolve": ["camera", "seg"]},
            {"audit_limit": 5},
            {"flush": True},
            {},
        ],
        ids=["resolve-строка", "resolve-список", "audit_limit-число", "flush-bool", "пусто"],
    )
    def test_introspect_observability_accepts_declared_forms(self, args) -> None:
        _svc, handlers = _wired()
        res = handlers["introspect.observability"](dict(args))
        assert res["success"] is True, res.get("reason")

    def test_resolve_list_still_resolves_every_name(self) -> None:
        """Приём — это не только «не отказал»: разбор обязан произойти."""
        _svc, handlers = _wired()
        res = handlers["introspect.observability"]({"resolve": ["camera", "seg"]})
        assert set(res["resolve"]) == {"camera", "seg"}

    def test_valid_telemetry_section_still_applies(self) -> None:
        """Новый контракт `telemetry.reconfigure` не должен ломать живую команду."""
        _svc, handlers = _wired()
        res = handlers["telemetry.reconfigure"]({"publish": {"metrics": {"fps": {"enabled": False}}}})
        assert res["success"] is True, res.get("reason")
        assert res["applied"] == {"publish": True}


class TestHazardsOfTheMechanism:
    """Хазарды самой обёртки — их видно только автору."""

    def test_absent_field_is_not_materialized(self) -> None:
        """Приведённые параметры не имеют права ДОБАВИТЬ отсутствующий ключ.

        Половина команд наблюдаемости различает «ключа нет» и «ключ есть со
        значением null» ПРИСУТСТВИЕМ (``publish: null`` — «выключить гейт»,
        отсутствие — «слои молчат»). Верни обёртка ``model_dump()`` целиком —
        каждая правка троттла заодно объявляла бы себя правкой publish.
        """
        _svc, handlers = _wired()
        res = handlers["telemetry.reconfigure"]({"throttle": {"processes.**.state.fps": 2.0}})
        assert res["success"] is True, res.get("reason")
        assert "publish" not in res["applied"], f"обёртка материализовала отсутствующий publish: {res['applied']}"

    def test_explicit_null_still_means_disable(self) -> None:
        """Обратная половина той же пары: явный ``null`` обязан доехать как есть."""
        _svc, handlers = _wired()
        handlers["telemetry.reconfigure"]({"publish": {}})
        res = handlers["telemetry.reconfigure"]({"publish": None})
        assert res["success"] is True, res.get("reason")
        assert res["applied"] == {"publish": True}

    def test_transport_keys_do_not_trip_the_check(self) -> None:
        """``correlation_id`` едет в ``data`` КАЖДОГО request-response вызова.

        Судили бы мы лишние ключи здесь — отказ получала бы любая команда,
        отправленная через request-response. Ровно эта грабля стоила NEW-3
        отдельного разбора; проверка типов её не воскрешает, потому что судит
        только ОБЪЯВЛЕННЫЕ поля.
        """
        _svc, handlers = _wired()
        res = handlers["introspect.observability"]({"correlation_id": "cid-1", "_address": "gui", "flush": True})
        assert res["success"] is True, res.get("reason")

    def test_coercion_happens_in_the_layer_itself(self) -> None:
        """Приведение делает ЭТОТ слой, а не хендлер своим ``int()``.

        Первая редакция проверяла приведение через ответ
        ``introspect.observability {"audit_limit": "2"}`` — и инъекция «убрать
        приведение» её НЕ убила: хендлер сам делает ``int(args.get(...))``, то
        есть тест сторожил чужой ``int``, а не гарантию слоя. Осталось два
        доказательства, и оба умирают от своей инъекции: этот юнит на самом
        механизме и живой ``test_the_word_no_is_understood_as_false`` — там
        хендлер как раз НЕ приводит, он делает ``bool(...)``, и цена ошибки
        видна на слое.
        """
        coerced, problems = validated_params("introspect.observability", {"audit_limit": "2"})
        assert problems == []
        assert coerced["audit_limit"] == 2 and isinstance(coerced["audit_limit"], int)
        assert not isinstance(coerced["audit_limit"], str)

    @pytest.mark.parametrize(
        "command,field",
        [
            ("logger.sink.disable", "ttl"),
            ("introspect.observability", "audit_limit"),
            # `config.reload:ttl` сюда НЕ входит: инъекция показала, что его
            # держит не этот слой, а `_parse_ttl` (5.8) — случай остался бы
            # зелёным при снятой проверке и создавал бы видимость доказательства.
        ],
    )
    def test_bool_is_not_a_number(self, command, field) -> None:
        """``True`` не число — иначе проверка ОСЛАБИЛА бы существующую защиту.

        Найдено полным прогоном, а не этим файлом, и это стоит записать: первая
        редакция проверки принимала ``ttl=True`` (Pydantic в мягком режиме
        приводит ``bool`` к числу — ``bool`` подкласс ``int``), то есть команда,
        которую ``validate_ttl`` отвергала с 5.8, снимала приёмник на «одну
        секунду». Покраснел старый ``test_observability_ttl.py``; здесь
        гарантия закрепляется СВОИМ тестом, чтобы не держаться на чужом.
        """
        _svc, handlers = _wired()
        res = handlers[command]({field: True})
        assert res["success"] is False
        assert field in res["reason"], res["reason"]

    def test_commands_outside_the_scope_are_untouched(self) -> None:
        """Охват — решение Р-3(а), а не «всё подряд»: за его границей ничего не изменилось.

        Без этой проверки нельзя отличить «выбрали поверхность наблюдаемости» от
        «включили глобальный STRICT», а это разные решения владельца (Р-3 а/б).
        """
        svc, _handlers = _wired()
        svc.worker_manager = None  # у команды свой, НЕ типовой отказ — его и ждём
        BuiltinCommands(svc)._register_worker_crud_commands()
        handlers = svc.command_manager.handlers
        assert "worker.create" in handlers, "контроль не собран — судить нечего"
        # `worker_name` объявлен контрактом как str; bool туда не годится ровно так же,
        # как в поля наблюдаемости. Разница только в охвате — её и проверяем.
        res = handlers["worker.create"]({"worker_name": True})
        assert res["success"] is False
        assert "ожидается" not in str(res.get("reason", "")), (
            "команда вне охвата получила проверку типов — это уже глобальный STRICT, вариант Р-3(б)"
        )
