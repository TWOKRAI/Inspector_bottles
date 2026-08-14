# -*- coding: utf-8 -*-
"""Task 3.1 — опасности САМОГО механизма «нет получателя → отказ у inline-двери».

Это тесты автора, и они намеренно не пересекаются с приёмочными
(``test_telemetry_no_receiver_acceptance.py``, независимый тестер). Тестер судит
контракт снаружи: «отказ, адрес, слот не занят». Здесь — то, что видно только
изнутри устройства правки.

**Чем этот механизм опасен, учитывая, КАК он построен.**

1. **Отказ стоит у двери, а состояние меняют ТРИ дороги.** Секция телеметрии
   въезжает в слой из трёх мест: ``telemetry.reconfigure`` → ``_apply_telemetry_section``;
   ``config.reload`` с одной телеметрией → та же функция; ``config.reload`` с
   секцией ``observability`` рядом → ``_merge_telemetry_layer`` НАПРЯМУЮ, мимо
   неё (``builtin_commands`` :1820). Страж, поставленный внутри
   ``_apply_telemetry_section``, закрыл бы две дороги из трёх, и дефект воскрес
   бы ровно там, где его труднее всего заметить — «отказ зависит от того, приехала
   ли рядом секция observability». Тем же способом уже воскресала проверка
   ``telemetry_mode`` (замечание 2 ревью 5.10), поэтому страж стоит у ДВЕРИ,
   рядом с ``validate_telemetry_section``, и покрывает обе дороги ``config.reload``
   одним местом. Класс закрепляют :class:`TestGuardCoversAllRoadsIntoTheLayer`.

2. **Отказ обязан быть ЦЕЛЫМ.** В одной команде приезжают обе под-секции, и
   применимость у них разная: ``publish`` есть у любого процесса с heartbeat,
   ``throttle`` — только у оркестратора. Частичное применение оставило бы
   состояние, изменённое командой, которая ответила «отказ»: откатывать нечего,
   и оператор не знает, что уехало. Решение — отказ целиком (inline-половина
   ADR-PM-031: «состояние не изменилось» обязано быть правдой без оговорок).
   Закрепляет :class:`TestRefusalIsWholeNotPartial`.

3. **Владение плоскостью — ЛИПКОЕ.** ``layers.throttle_owned`` не снимается ничем,
   кроме пересоздания слоёв. Захвати его дельта, которой некуда ехать, — и
   плоскость навсегда «во владении слоёв» на процессе, где исполнителя нет:
   истечение срока начинает возвращать к загрузочным правилам, которых не было.
   Поэтому присвоение переехало ЗА проверку получателя. Опасность липкости в
   том, что она видна не с первого раза, а с ВТОРОГО — закрепляет
   :class:`TestRefusalAccumulatesNothing`.

4. **Отказ живёт рядом с чужими сроками.** L3 — общий слот-пул с TTL, и команда,
   которая ничего не применила, не имеет права ни продлить, ни укоротить, ни
   снять срок соседа. Механически это близко: ``session_touch`` обновляет сроки
   ключей ПРАВКИ, и стоило бы отказу пройти чуть глубже — он бы их коснулся.
   Закрепляет :class:`TestRefusalDoesNotTouchNeighbourExpiry`.

5. **Страж и применение резолвят получателя ДВАЖДЫ.** Дверь зовёт
   ``telemetry_unaddressable`` → ``telemetry_targets``; применение ниже зовёт
   ``telemetry_targets`` снова. Разойдись эти два резолва — и дверь отказывала бы
   там, где применение справилось. Общий резолвер (``resolve_store_throttle``)
   выбран именно поэтому; полу-собранный оркестратор (``_state_store_manager``
   есть, middleware ``"throttle"`` нет) — та точка, где наивный страж
   (``hasattr(svc, "_state_store_manager")``) разошёлся бы с применением.
   Закрепляет :class:`TestGuardAndApplierResolveTheSameReceiver`.

**Названный потолок (не гарантия, а известная граница).** Страж читает получателя
ВНЕ ``layers.lock``, а запись в слой идёт внутри него: между проверкой и записью
получатель теоретически может исчезнуть. Механизм назван точно, потому что первая
редакция этого абзаца назвала его неверно («снос ``_state_store_manager`` на
остановке»): рантайм-сноса в коде нет вовсе — единственное присваивание
``_state_store_manager = None`` это инициализация в ``process_manager_process``.
Реальное окно уже: исчезновение middleware ``"throttle"`` из живого стора.
Лок тут и не помог бы — он защищает слои, а не менеджеров процесса.
Исход такого гонки — прежнее поведение: ``applied.throttle=False`` при
``success=True``, то есть не хуже, чем до задачи, и без потери состояния.
Воспроизведения у этого окна нет, и оно НЕ закрепляется тестом: закрепить
означало бы объявить контрактом то, что мы считаем дефектом.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    process_observability_layers,
)
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    telemetry_unaddressable,
)
from multiprocess_framework.modules.process_module.managers.observability_ttl import (
    sweep_session_ttl,
)
from multiprocess_framework.modules.state_store_module.middleware.throttle import (
    ThrottleMiddleware,
)

from .test_telemetry_commands import _FakeServices, _make

_PUBLISH = {"metrics": {"fps": {"enabled": False}}}
_THROTTLE = {"a.b": 1.0}


class _Clock:
    """Управляемые тестом часы — зависимость объекта, а не глобальный патч."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _wired(**kw):
    """Процесс + слои с управляемыми часами. Без ``throttle`` → получателя нет."""
    svc, cm = _make(**kw)
    clock = _Clock()
    layers = process_observability_layers(svc)
    layers.clock = clock
    return svc, cm, layers, clock


def _gate_metrics(svc) -> set:
    gate = svc._heartbeat._telemetry_gate
    return set(gate.due_metrics(now=0.0)) if gate is not None else set()


class TestGuardCoversAllRoadsIntoTheLayer:
    """Опасность 1: три дороги в слой, страж — один, у двери.

    Третья дорога (``config.reload`` с секцией observability рядом) вливает
    телеметрию в слой мимо ``_apply_telemetry_section``. Стой страж внутри неё —
    эта пара была бы красной, а первые две зелёными: «отказ зависит от соседней
    секции», ровно тот класс, что уже воскресал у проверки ``telemetry_mode``.
    """

    def test_reload_with_observability_alongside_still_refuses(self) -> None:
        svc, cm, layers, _ = _wired()
        res = cm.dispatch(
            "config.reload",
            {"observability": {"log_level": "DEBUG"}, "telemetry": {"throttle": dict(_THROTTLE)}},
        )
        assert res["success"] is False, "секция observability рядом провела мимо стража"
        assert res["telemetry_no_receiver"] == ["throttle"]

    def test_the_observability_neighbour_is_not_applied_either(self) -> None:
        """Отказ третьей дороги — ДО записи, включая соседнюю секцию observability.

        Порядок здесь несущий: ветка observability кладёт СВОЮ секцию в L3
        раньше, чем доходит до телеметрии. Стой страж внутри неё — `log_level`
        уже лежал бы в сессии под ответом «отказ».
        """
        svc, cm, layers, _ = _wired()
        cm.dispatch(
            "config.reload",
            {"observability": {"log_level": "DEBUG"}, "telemetry": {"throttle": dict(_THROTTLE)}},
        )
        assert list(layers.session_keys()) == [], f"отказ оставил след в L3: {layers.session_keys()}"

    def test_receiver_present_passes_all_three_roads(self) -> None:
        """Контроль: страж не отказывает там, где применить есть кому.

        Без этой пары «отказ всегда» дал бы зелёные проверки выше.
        """
        throttle = ThrottleMiddleware({})
        svc, cm = _make(throttle=throttle)
        assert cm.dispatch("telemetry.reconfigure", {"throttle": {"x.y": 1.0}})["success"] is True
        assert cm.dispatch("config.reload", {"telemetry": {"throttle": {"x.y": 2.0}}})["success"] is True
        res = cm.dispatch(
            "config.reload",
            {"observability": {"log_level": "DEBUG"}, "telemetry": {"throttle": {"x.y": 3.0}}},
        )
        assert res["success"] is True
        assert throttle.rules == {"x.y": 3.0}, "третья дорога не доехала до получателя"


class TestRefusalIsWholeNotPartial:
    """Опасность 2: обе под-секции в одной команде, применима одна.

    Решение — отказ ЦЕЛИКОМ. Проверяется не только ответ, но и то, что применимая
    половина действительно не уехала: ответ «отказ» при перестроенном гейте был
    бы худшим из исходов — состояние изменено, а откатывать по ответу нечего.
    """

    def test_publish_does_not_leak_through_when_throttle_is_unaddressable(self) -> None:
        svc, cm, layers, _ = _wired()  # heartbeat есть, троттла нет
        before = _gate_metrics(svc)
        res = cm.dispatch("telemetry.reconfigure", {"publish": dict(_PUBLISH), "throttle": dict(_THROTTLE)})
        assert res["success"] is False
        assert res["telemetry_no_receiver"] == ["throttle"], "названа не та половина"
        assert svc._heartbeat._telemetry_gate is None, "publish применился под ответом «отказ»"
        assert _gate_metrics(svc) == before
        assert list(layers.session_keys()) == []

    def test_the_same_publish_alone_would_have_applied(self) -> None:
        """Контроль к предыдущему: половина применима сама по себе.

        Без него «publish не применился» доказывало бы лишь то, что он не
        применяется никогда.
        """
        svc, cm, _, _ = _wired()
        res = cm.dispatch("telemetry.reconfigure", {"publish": dict(_PUBLISH)})
        assert res["success"] is True
        assert svc._heartbeat._telemetry_gate is not None

    def test_both_unaddressable_are_named_in_a_stable_order(self) -> None:
        """Ни heartbeat'а, ни троттла — названы ОБЕ, и порядок не зависит от входа.

        Порядок ключей во входном словаре не должен менять текст ответа: иначе
        два одинаковых промаха читались бы как два разных.
        """

        class _Bare(_FakeServices):
            def __init__(self) -> None:
                super().__init__()
                self._heartbeat = None

        svc = _Bare()
        BuiltinCommands(svc)._register_observability_commands()
        first = svc.command_manager.dispatch(
            "telemetry.reconfigure", {"throttle": dict(_THROTTLE), "publish": dict(_PUBLISH)}
        )
        second = svc.command_manager.dispatch(
            "telemetry.reconfigure", {"publish": dict(_PUBLISH), "throttle": dict(_THROTTLE)}
        )
        assert first["telemetry_no_receiver"] == ["throttle", "publish"]
        assert first["telemetry_no_receiver"] == second["telemetry_no_receiver"]
        assert first["reason"] == second["reason"]


class TestRefusalAccumulatesNothing:
    """Опасность 3: липкое владение видно со ВТОРОГО раза, не с первого."""

    def test_ten_refusals_leave_the_layer_exactly_as_it_was(self) -> None:
        svc, cm, layers, _ = _wired()
        for _ in range(10):
            assert cm.dispatch("telemetry.reconfigure", dict(throttle=dict(_THROTTLE)))["success"] is False
        assert list(layers.session_keys()) == []
        assert layers.throttle_owned is False, "владение накопилось отказами"
        assert layers.telemetry_owned is False

    def test_refusal_leaves_no_audit_record(self) -> None:
        """Журнал смен — тоже состояние. «Ничего не изменилось» включает и его.

        Аудит — единственный долговечный след правки слоёв; запись о смене,
        которой не было, увела бы разбор живого инцидента на несуществующую
        правку.
        """
        svc, cm, layers, _ = _wired()
        before = len(layers.audit.entries())
        cm.dispatch("telemetry.reconfigure", {"throttle": dict(_THROTTLE)})
        assert len(layers.audit.entries()) == before

    def test_a_legal_edit_after_refusals_still_applies(self) -> None:
        """Сосед не отравлен: отказы не переводят дверь в «отказывать всему».

        Свойство хрупкое по построению — страж читает состояние процесса, и
        залипни он на первом ответе, законная правка молча перестала бы
        применяться после первого промаха оператора.
        """
        svc, cm, layers, _ = _wired()
        for _ in range(3):
            cm.dispatch("telemetry.reconfigure", {"throttle": dict(_THROTTLE)})
        res = cm.dispatch("telemetry.reconfigure", {"publish": dict(_PUBLISH)})
        assert res["success"] is True
        assert res["applied"]["publish"] is True


class TestRefusalDoesNotTouchNeighbourExpiry:
    """Опасность 4: отказ рядом с чужими сроками в общем пуле L3."""

    def test_refusal_neither_refreshes_nor_drops_a_neighbours_ttl(self) -> None:
        """Отказ не двигает срок соседа — сторож ГЛУБИНЫ, краснеет только от пары изломов.

        Замерено инъекциями (замечание З3 ревью). Одиночные изломы его НЕ красят,
        и это не дефект теста, а следствие того, что он сторожит:

        * снять стража двери — отказ пройдёт насквозь, но ``session_touch``
          получит ключи ТОЛЬКО этой правки, и срок соседа всё равно уцелеет;
        * подать в ``session_touch`` все ключи сессии вместо ключей правки —
          отказ до него не доходит, потому что страж вернул раньше. Этот излом
          ловит существующий ``test_telemetry_layers::
          test_merge_does_not_extend_the_deadline_of_foreign_keys``.

        Красным он становится ровно на ПАРЕ. Рецепт записан, потому что число
        красных от него зависит: снять блок ``if no_receiver: return`` в
        ``_cmd_telemetry_reconfigure`` И подменить ``layers.session_touch(incoming,
        …)`` в ``_merge_telemetry_layer`` на ``session_touch(flatten_section(
        layers.session).keys(), …)`` — текстовой правкой файла, до импорта. Даёт
        **7 красных из 14** в этом файле, включая данный. (Ревью прогнало ту же
        пару плагином ПОСЛЕ импорта тест-модулей и получило 9 — расходится набор
        задетых резолверов, а не свойство. Кто повторяет — сверяйтесь с рецептом,
        а не с числом.)

        Утверждение теста: даже если страж однажды откажет, отказ не имеет права
        продлить чужую ручку. Убирать его нельзя — он единственный, кто судит эту
        композицию.
        """
        svc, cm, layers, clock = _wired()
        assert cm.dispatch("telemetry.reconfigure", {"publish": dict(_PUBLISH), "ttl": 60})["success"] is True
        key = next(k for k in layers.session_keys() if k.startswith("telemetry.publish"))
        clock.advance(30)
        assert layers.session_expires_in(key) == 30.0  # база отсчёта

        cm.dispatch("telemetry.reconfigure", {"throttle": dict(_THROTTLE)})  # отказ

        left = layers.session_expires_in(key)
        assert left == 30.0, f"отказ тронул срок соседа: осталось {left}, ожидалось 30.0"

    def test_sweeper_after_a_refusal_removes_the_neighbour_and_only_it(self) -> None:
        """Истечение после отказа снимает ЧУЖОЙ ключ по его собственному сроку.

        Обратная сторона той же опасности: отказ не должен ни продлить соседа
        (тогда подметальщик его не найдёт), ни подложить в пул свой ключ (тогда
        найдёт лишний).
        """
        svc, cm, layers, clock = _wired()
        cm.dispatch("telemetry.reconfigure", {"publish": dict(_PUBLISH), "ttl": 60})
        cm.dispatch("telemetry.reconfigure", {"throttle": dict(_THROTTLE)})  # отказ
        clock.advance(61)

        report = sweep_session_ttl(svc)
        assert report is not None, "сосед не истёк — отказ продлил чужой срок"
        expired = list(report.get("expired") or [])
        assert all("throttle" not in k for k in expired), f"подметальщик нашёл ключ отказа: {expired}"
        assert list(layers.session_keys()) == []


class TestGuardAndApplierResolveTheSameReceiver:
    """Опасность 5: два резолва получателя обязаны сходиться."""

    def test_half_wired_store_manager_without_throttle_middleware_is_refused(self) -> None:
        """``_state_store_manager`` есть, middleware ``"throttle"`` — нет.

        Наивный страж (``hasattr(svc, "_state_store_manager")``) сказал бы
        «получатель есть», применение вернуло бы ``throttle: False`` — и мы
        получили бы прежний дефект на полу-собранном оркестраторе, то есть в
        единственном месте, где его никто не ищет.
        """

        class _EmptyStore:
            def get_middleware(self, name):  # noqa: ARG002 — «нет ни одного»
                return None

        svc, cm = _make()
        svc._state_store_manager = _EmptyStore()
        assert telemetry_unaddressable(svc, {"throttle": dict(_THROTTLE)}) == ["throttle"]
        res = cm.dispatch("telemetry.reconfigure", {"throttle": dict(_THROTTLE)})
        assert res["success"] is False
        assert res["telemetry_no_receiver"] == ["throttle"]

    def test_guard_judges_key_presence_not_truthiness(self) -> None:
        """``publish: null`` — законная команда «снять гейт», и снимать тоже некому.

        Опасность конкретная: ``.get(sub)`` вернул бы ``None`` и для «ключа нет»,
        и для явного ``null``, а второй случай — правка, которую обязан
        рассудить страж. Тем же правилом Г3 живёт вся секция.
        """

        class _Bare(_FakeServices):
            def __init__(self) -> None:
                super().__init__()
                self._heartbeat = None

        svc = _Bare()
        assert telemetry_unaddressable(svc, {"publish": None}) == ["publish"]
        assert telemetry_unaddressable(svc, {}) == []

    def test_receiver_present_is_not_reported_missing(self) -> None:
        """Контроль: у процесса-получателя список пуст — иначе всё выше вакуумно."""
        svc, _cm = _make(throttle=ThrottleMiddleware({}))
        assert telemetry_unaddressable(svc, {"throttle": dict(_THROTTLE), "publish": dict(_PUBLISH)}) == []
