# -*- coding: utf-8 -*-
"""Опасности механизма ``ObservableMixin.report_error`` (Task 1.3b, тесты автора).

Не приёмка задачи — приёмку писал независимый тестер
(``Plugins/**/test_failure_classes_*_acceptance.py``). Здесь то, что видно
только автору: что именно может сломаться в ЭТОЙ конструкции, учитывая, как она
собрана.

Механизм даёт два обязательства, и они не равны по цене:

* **факт** — запись в плоскость ошибок, идёт ВСЕГДА;
* **голос** — строка в журнал, не чаще окна на ключ ``(класс, context)``.

Из неравенства цены следует главная опасность файла: у этой двери вызывающий —
по построению миграции Task 1.3b тело ``except``, и любой бросок ИЗ механизма
подменяет исходную ошибку своей. Поэтому «голос упал» обязано стоить голос, а
не разбор инцидента. Две дыры этого рода найдены при написании докстрингов
ниже, до всякого прогона: бросок держателя окон и коллизия поля ``origin``.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Tuple

import pytest

from multiprocess_framework.modules.base_manager.mixins.observable_mixin import ObservableMixin
from multiprocess_framework.modules.channel_routing_module.observability.store_tap import (
    ORIGIN_ERROR_MANAGER,
    ORIGIN_FIELD,
)
from multiprocess_framework.modules.error_module.interfaces import (
    DeviceOpenFailed,
    ObservabilityMisuse,
    SubsystemStartFailed,
)


class _Probe(ObservableMixin):
    """Наследник миксина без BaseManager — механизм от него не зависит."""

    def __init__(self, managers: Dict[str, Any] | None = None) -> None:
        ObservableMixin.__init__(self, managers=managers or {}, source_name="probe")


class _ErrorPlane:
    """Приёмник плоскости ошибок: помнит каждую запись целиком."""

    def __init__(self) -> None:
        self.rows: List[Tuple[BaseException, Dict[str, Any]]] = []
        self._lock = threading.Lock()

    def track_error(self, error: BaseException, context: Dict[str, Any] | None = None) -> None:
        with self._lock:
            self.rows.append((error, dict(context or {})))


def _wire(probe: _Probe) -> Tuple[_ErrorPlane, List[Tuple[str, Dict[str, Any]]]]:
    """Подключить плоскость ошибок и перехватить голоса."""
    plane = _ErrorPlane()
    probe.register_manager("error", plane, enabled=True)
    voices: List[Tuple[str, Dict[str, Any]]] = []
    probe._log_error = lambda msg, **kw: voices.append((msg, kw))  # type: ignore[method-assign]
    return plane, voices


class TestTheVoiceNeverCostsTheIncident:
    """Отказ ГОЛОСА не имеет права стать вторым исключением поверх первого."""

    def test_throwing_window_holder_costs_the_voice_not_the_fact(self) -> None:
        """Держатель окон бросил → факт записан, наружу ничего не ушло, отказ посчитан.

        Опасность реальная, а не гипотетическая: держатель окон — ЧУЖОЙ
        механизм с собственным локом, и ревью Task 1.3a уже воспроизводило его
        бросок на ``take()``. Разница с ``HealthState`` здесь сознательная: там
        бросок уходит вызывающему (процессные хуки его ловят и считают), а сюда
        зовут ИЗ ``except``-веток — подменить там исходную ошибку жалобой
        механизма наблюдаемости хуже, чем промолчать одной строкой журнала.
        """
        probe = _Probe()
        plane, voices = _wire(probe)
        probe.should_voice = lambda key, interval=None: (_ for _ in ()).throw(  # type: ignore[method-assign]
            RuntimeError("держатель окон недоступен")
        )

        probe.report_error(DeviceOpenFailed("камера не открылась"), context="capture.start", camera_id=3)

        assert len(plane.rows) == 1, f"факт потерян из-за отказа ГОЛОСА: {plane.rows}"
        assert voices == [], "голос не мог прозвучать — держатель бросил до решения"
        assert probe.manager_call_failures.get("logger.report_error.voice") == 1, (
            f"отказ голоса обязан быть посчитан, а не проглочен молча: {probe.manager_call_failures}"
        )

    def test_throwing_logger_costs_the_voice_not_the_fact(self) -> None:
        """Приёмник журнала бросил → факт записан, наружу ничего не ушло."""
        probe = _Probe()
        plane, _voices = _wire(probe)

        def _boom(msg: str, **kw: Any) -> None:
            raise OSError("файл журнала недоступен")

        probe._log_error = _boom  # type: ignore[method-assign]

        probe.report_error(SubsystemStartFailed("воркер не создан"), context="hub.create_worker")

        assert len(plane.rows) == 1, f"факт потерян из-за отказа журнала: {plane.rows}"
        assert probe.manager_call_failures.get("logger.report_error.voice") == 1


class TestFieldsDoNotCollideWithTheMechanism:
    """Поля инцидента — данные сайта, и они не имеют права ломать механизм."""

    def test_site_field_named_origin_does_not_crash_the_voice(self) -> None:
        """Сайт передал поле ``origin`` → голос звучит, маркер выигрывает.

        Найдено чтением собственного кода: первая редакция собирала голос как
        ``self._log_error(text, **fields, **marker)``, и сайт со своим полем
        ``origin`` ронял вызов ``TypeError: got multiple values for keyword
        argument 'origin'`` — то есть поле данных убивало ГОЛОС целиком.
        Маркер обязан выигрывать: он не деталь инцидента, а утверждение о
        строке стора, и его подмена значением сайта сняла бы дедуп путей.
        """
        probe = _Probe()
        _plane, voices = _wire(probe)

        probe.report_error(DeviceOpenFailed("отказ"), context="op", origin="самодельное значение")

        assert len(voices) == 1, f"поле сайта убило голос: {voices}"
        assert voices[0][1][ORIGIN_FIELD] == ORIGIN_ERROR_MANAGER, (
            f"значение сайта перебило маркер дедупа путей — стор получит дубль: {voices[0][1]}"
        )

    def test_marker_is_absent_when_the_error_plane_is_not_there(self) -> None:
        """Плоскости нет → маркера нет, иначе инцидент исчезает целиком.

        Класс Major 1 ревью Task 1.3a: маркер утверждает «строка стора у этого
        инцидента уже есть». Безусловный, он ложен на процессе без
        ErrorManager, и логгер-tap по этому ложному утверждению пропускает
        голос — было 1 строка, стало 0.
        """
        probe = _Probe()  # слот 'error' пуст
        voices: List[Tuple[str, Dict[str, Any]]] = []
        probe._log_error = lambda msg, **kw: voices.append((msg, kw))  # type: ignore[method-assign]

        probe.report_error(DeviceOpenFailed("отказ"), context="op")

        assert len(voices) == 1, "голос обязан прозвучать и без плоскости ошибок"
        assert ORIGIN_FIELD not in voices[0][1], f"маркер утверждает чужую строку стора, которой нет: {voices[0][1]}"


class TestWindowKeyIsPerFailureClass:
    """Ключ — (класс, context). Ни грубее, ни дробнее."""

    def test_two_classes_in_one_context_both_speak(self) -> None:
        """Разные классы в одном контексте не глушат друг друга."""
        probe = _Probe()
        _plane, voices = _wire(probe)

        probe.report_error(DeviceOpenFailed("камера"), context="hub.op")
        probe.report_error(SubsystemStartFailed("воркер"), context="hub.op")

        assert len(voices) == 2, f"один класс заглушил другой — ключ окна вырожден: {voices}"

    def test_one_class_repeated_speaks_once_and_names_the_suppressed(self) -> None:
        """Повтор одного класса — один голос, но с числом подавленных.

        Вторая половина обязательна: «одна строка» без числа неотличима от
        «остальные потеряли», а потеряны они как раз НЕ были — факты ниже.
        """
        probe = _Probe()
        plane, voices = _wire(probe)

        for i in range(5):
            probe.report_error(DeviceOpenFailed(f"попытка {i}"), context="hub.op")

        assert len(plane.rows) == 5, f"факт обязан идти на КАЖДОЕ вхождение: {plane.rows}"
        assert len(voices) == 1, f"повтор одного класса обязан дать один голос: {voices}"

        probe.report_error(DeviceOpenFailed("шестая"), context="hub.op", throttle=0.0)
        assert "подавлено" in voices[1][0], f"второй голос обязан назвать число подавленных вхождений: {voices[1][0]!r}"


class TestMisuseIsAFactNotAThrow:
    """Кривой вызов дороги наблюдаемости не роняет обработчик."""

    def test_non_exception_becomes_a_typed_fact_and_a_counter(self) -> None:
        """``_track_error`` с мусором → ObservabilityMisuse + книга, без броска.

        Живой прецедент: четыре адреса звали
        ``self._track_error("dispatcher.initialization.failed", error=e)`` —
        ``error`` позиционно И по имени. Прогон до правки:
        ``TypeError: got multiple values for argument 'error'`` внутри
        ``except``. Не стреляло только потому, что сами ветки мертвы.
        """
        probe = _Probe()
        plane, _voices = _wire(probe)

        probe._track_error("не исключение, а строка")  # type: ignore[arg-type]

        assert len(plane.rows) == 1, "мусор обязан стать ФАКТОМ, а не исчезнуть"
        assert isinstance(plane.rows[0][0], ObservabilityMisuse), (
            f"мусор обязан приехать типизированным, иначе ключ окна вырожден: {plane.rows[0][0]!r}"
        )
        assert probe.track_error_misuse == {"probe": 1}, (
            f"книга misuse обязана назвать источник кривого вызова: {probe.track_error_misuse}"
        )

    def test_a_clean_probe_has_an_empty_misuse_book(self) -> None:
        """Контроль: без кривых вызовов книга ПУСТА, а не «нулевая по молчанию».

        Без этого контроля предыдущий тест был бы зелен и у механизма, который
        считает misuse на КАЖДЫЙ вызов.
        """
        probe = _Probe()
        _plane, _voices = _wire(probe)

        probe.report_error(DeviceOpenFailed("честный отказ"), context="op")

        assert probe.track_error_misuse == {}, (
            f"здоровый вызов не имеет права попасть в книгу misuse: {probe.track_error_misuse}"
        )


class TestConcurrency:
    """Механизм зовут из воркер-потоков; лок держателя окон — чужой."""

    def test_every_thread_leaves_a_fact_and_only_one_speaks(self) -> None:
        """20 потоков одного класса → 20 фактов, 1 голос, никто не завис.

        Тест обязан ПАДАТЬ, а не висеть: если лок держателя окон удерживается
        на время эмиссии, join с дедлайном покажет это числом невернувшихся
        потоков, а не таймаутом всего гейта.
        """
        probe = _Probe()
        plane, voices = _wire(probe)
        voices_lock = threading.Lock()
        raw_append = voices.append

        def _safe_append(item: Any) -> None:
            with voices_lock:
                raw_append(item)

        probe._log_error = lambda msg, **kw: _safe_append((msg, kw))  # type: ignore[method-assign]

        threads = [
            threading.Thread(
                target=probe.report_error,
                args=(DeviceOpenFailed(f"поток {i}"),),
                kwargs={"context": "op"},
                daemon=True,
            )
            for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5.0)

        alive = [t for t in threads if t.is_alive()]
        assert not alive, f"{len(alive)} из 20 потоков не вернулись за 5с — механизм держит лок на время эмиссии"
        assert len(plane.rows) == 20, f"факт обязан быть у КАЖДОГО потока: {len(plane.rows)}"
        assert len(voices) == 1, f"один класс в одном контексте — один голос: {voices}"


@pytest.mark.parametrize("bad_context", [None, "", 0])
def test_context_shapes_do_not_break_the_key(bad_context: Any) -> None:
    """Пустой/отсутствующий контекст — законное состояние, а не отказ."""
    probe = _Probe()
    plane, voices = _wire(probe)

    probe.report_error(DeviceOpenFailed("отказ"), context=bad_context)

    assert len(plane.rows) == 1
    assert len(voices) == 1


class TestProcessModuleKeepsItsRicherRoad:
    """Метод добавлен в миксин, который наследуют 100+ классов — чей он теперь?

    Опасность конкретная и названа в коммите механизма: у ``ProcessModule`` УЖЕ
    был свой ``report_error``, делегирующий процесс-общему ``HealthState``
    (health-счётчик, ``last_error``, breaker). Одноимённый метод на миксине
    обязан остаться ПОД ним по MRO: перехвати он вызов — процесс бы продолжал
    писать факты, но статус здоровья не деградировал бы НИКОГДА, а это ровно
    Major 2 ревью Task 1.3a, только приехавший с другой стороны.

    Тест смотрит на MRO и на НАБЛЮДАЕМЫЙ эффект (счётчик health вырос), а не на
    имя вызванного метода: спай на имя охранял бы имя, а не свойство.
    """

    def test_process_module_road_wins_over_the_mixin_and_still_counts_health(self) -> None:
        from multiprocess_framework.modules.process_module.core.process_module import ProcessModule

        assert ProcessModule.report_error is not ObservableMixin.report_error, (
            "ObservableMixin.report_error перехватил дорогу процесса — health-счётчик и breaker "
            "перестанут наполняться, статус не деградирует никогда"
        )

        from multiprocess_framework.modules.process_module.health import get_or_create_health_state

        process = ProcessModule("mro_probe")
        health = get_or_create_health_state(process)
        before = health.error_count
        process.report_error(DeviceOpenFailed("камера не открылась"), context="capture.start", camera_id=1)
        after = get_or_create_health_state(process).error_count

        assert after == before + 1, (
            f"инцидент не долетел до health процесса: было {before}, стало {after} — "
            f"значит вызов ушёл в голый миксин, а не в дорогу процесса"
        )

        # Контроль: голый миксин ЭТОГО не делает — иначе тест выше был бы зелен
        # при любом из двух путей, и про MRO не говорил бы ничего.
        bare = _Probe()
        _wire(bare)
        bare.report_error(DeviceOpenFailed("тот же отказ"), context="capture.start")
        assert not hasattr(bare, "_health_state"), (
            "у голого миксина завёлся health — контроль перестал различать две дороги"
        )


class TestFieldNamesCannotCollideWithTheReceiversSignature:
    """Имя поля, занятое ПРОТОКОЛОМ дорог, не имеет права съесть деталь инцидента.

    Класс найден трижды, тремя разными способами, и это его главная
    характеристика — он не виден с одной точки наблюдения:

    * ``origin`` — чтением механизма автором;
    * ``message`` на дороге ГОЛОСА — исполнителем миграции Task 1.3b, который
      принёс поле с этим именем с реального сайта ``dispatcher.dispatch``;
    * ``message`` на дороге ФАКТА и пара ``manager_name``/``method_name`` —
      ревью, ЗАПУСКОМ против настоящего ``ErrorManager``, тогда как сторож
      автора (этот файл) проверял свойство против фейка и был зелен.

    Две двери резервируют имена ПО-РАЗНОМУ, и в этом ловушка. Голос роняет
    вызов громко (``TypeError``), а факт съедает имя ``message`` ТИХО: протокол
    ``track_error`` ``pop``-ает его в приставку к тексту, и поля не остаётся.
    Поэтому разводка стоит на ВХОДЕ, одна на обе дороги: иначе одно и то же
    поле приезжает в журнал под одним именем, а в стор под другим.
    """

    def test_a_field_named_like_the_log_parameter_does_not_kill_the_voice(self) -> None:
        """Поле ``message`` не роняет голос и доезжает переименованным."""
        probe = _Probe()
        plane, voices = _wire(probe)

        probe.report_error(
            SubsystemStartFailed("диспетчер не разобрал"),
            context="dispatcher.dispatch",
            message="сырое тело сообщения",
            key="cmd.run",
        )

        assert len(voices) == 1, f"голос не прозвучал — коллизия имени уронила вызов: {voices}"
        _text, kwargs = voices[0]
        assert kwargs["field_message"] == "сырое тело сообщения", f"деталь сайта потеряна при разводке имён: {kwargs}"
        assert kwargs["key"] == "cmd.run", f"соседнее поле пострадало от разводки: {kwargs}"

    def test_the_same_field_arrives_under_the_same_name_on_both_planes(self) -> None:
        """Имя поля не зависит от того, куда смотришь — журнал или стор.

        Первая редакция механизма разводила ТОЛЬКО голос, и это само было
        дефектом: фильтр по полю работал бы в журнале и не работал бы в сторе.
        """
        probe = _Probe()
        plane, voices = _wire(probe)

        probe.report_error(DeviceOpenFailed("нет связи"), context="hub.forward", message="хаб отказал")

        _exc, ctx = plane.rows[0]
        _text, kwargs = voices[0]
        assert "field_message" in ctx and "field_message" in kwargs, (
            f"поле приехало под РАЗНЫМИ именами: стор {sorted(ctx)}, журнал {sorted(kwargs)}"
        )
        assert "message" not in ctx, f"занятое имя осталось в записи и будет съедено протоколом: {ctx}"

    def test_against_the_real_error_manager_not_a_fake(self) -> None:
        """Пара к фейку: то же свойство против НАСТОЯЩЕГО ``ErrorManager``.

        Сторож выше проверяет ``_ErrorPlane`` — дублёра, который кладёт словарь
        дословно. Против настоящей двери утверждение «поле лежит под своим
        именем» было ЛОЖНЫМ: ``track_error`` ``pop``-ает ``message`` в приставку
        к тексту. Ревью нашло это запуском, и без этого теста следующий сайт
        положил бы имя снова.
        """
        from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager

        em = ErrorManager(config={"app_name": "hazard_probe"})
        captured: List[Dict[str, Any]] = []
        em.log_exception = lambda error, message="", module="unknown", **kw: captured.append(  # type: ignore[method-assign]
            {"message": message, "module": module, **kw}
        )

        probe = _Probe()
        probe.register_manager("error", em, enabled=True)
        probe._log_error = lambda msg, **kw: None  # type: ignore[method-assign]

        probe.report_error(
            DeviceOpenFailed("устройство не отвечает"),
            context="robot_io.forward.refused",
            message="хаб отказал",
            device_id="dev_alpha",
        )

        assert len(captured) == 1, f"инцидент не доехал до настоящей двери: {captured}"
        row = captured[0]
        assert row["field_message"] == "хаб отказал", (
            f"деталь съедена протоколом настоящей двери — то, что фейк показать не мог: {row}"
        )
        assert row["message"] == "robot_io.forward.refused", (
            f"приставкой к тексту обязан остаться САЙТ-ТЕГ, а не поле сайта: {row}"
        )
        assert row["device_id"] == "dev_alpha", f"соседнее поле потеряно: {row}"

    def test_the_reserved_set_is_exactly_the_chain_not_one_hop(self) -> None:
        """Набор сверяется со ВСЕЙ цепочкой вызова, а не с памятью автора.

        Первая редакция теста смотрела подпись ``_log_error`` и называла себя
        «exactly the receiver's signature», пропуская второй хоп
        ``_call_manager(manager_name, method_name, ...)``: поля с такими именами
        теряли ГОЛОС целиком, а сторож оставался зелёным. Считаем объединение.
        """
        import inspect

        from multiprocess_framework.modules.base_manager.mixins.observable_mixin import (
            _RESERVED_FIELD_NAMES,
        )

        def _named(fn) -> set:
            return {
                name
                for name, prm in inspect.signature(fn).parameters.items()
                if name != "self" and prm.kind not in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)
            }

        chain = _named(ObservableMixin._log_error) | _named(ObservableMixin._call_manager)
        assert chain == set(_RESERVED_FIELD_NAMES), (
            f"цепочка разошлась с набором зарезервированных имён: "
            f"цепочка {sorted(chain)}, набор {sorted(_RESERVED_FIELD_NAMES)}"
        )

    def test_a_second_hop_name_does_not_silently_swallow_the_voice(self) -> None:
        """``manager_name`` как поле — голос жив, а не потерян в счётчике."""
        probe = _Probe()
        _plane, voices = _wire(probe)

        probe.report_error(DeviceOpenFailed("сбой"), context="op", manager_name="чужое имя")

        assert len(voices) == 1, (
            f"голос потерян на втором хопе цепочки: {voices}, отказы={getattr(probe, 'manager_call_failures', {})}"
        )
        assert voices[0][1]["field_manager_name"] == "чужое имя", f"деталь потеряна: {voices[0][1]}"


class TestTheWindowContextCannotBeShadowedByASite:
    """``context`` — половина ключа окна; подменить его полем сайта НЕЛЬЗЯ."""

    def test_a_field_named_context_cannot_even_reach_the_mechanism(self) -> None:
        """Одноимённое поле роняет вызов НА САЙТЕ и до механизма не долетает.

        Тест записывает ОТРИЦАТЕЛЬНЫЙ результат разбора, и в этом его ценность.
        Автор (я) сперва счёл тихую подмену контекста реальной опасностью и
        переставил слияние словарей «чтобы механизм выигрывал». Прогон показал
        обратное: ``context`` — именованный параметр ``report_error``, поэтому
        поле с таким именем связывается С НИМ, а в ``**fields`` не попадает
        никогда. Дыры нет, страховка бесплатна, но комментарий, объявлявший
        опасность реальной, был бы ровно тем «уверенным неверным объяснением»,
        которое переживает баг.

        Красным тест станет в день, когда ``context`` перестанет быть
        параметром: тогда подмена станет достижима и её придётся закрывать
        по-настоящему.
        """
        import inspect

        params = inspect.signature(ObservableMixin.report_error).parameters
        assert params["context"].kind is inspect.Parameter.KEYWORD_ONLY or params["context"].kind is (
            inspect.Parameter.POSITIONAL_OR_KEYWORD
        ), f"context перестал быть именованным параметром — подмена стала достижима: {params}"

        probe = _Probe()
        _wire(probe)
        with pytest.raises(TypeError, match="context"):
            probe.report_error(
                DeviceOpenFailed("камера не открылась"),
                context="capture.start",
                **{"context": "совсем другое место"},
            )

    def test_the_real_context_reaches_the_store_row(self) -> None:
        """Контроль к предыдущему: настоящий ``context`` в записи есть.

        Без него тест выше зелен и в мире, где ``context`` не доезжает вообще.
        """
        probe = _Probe()
        plane, voices = _wire(probe)

        probe.report_error(DeviceOpenFailed("камера не открылась"), context="capture.start", camera_id=3)

        _exc, ctx = plane.rows[0]
        assert ctx["context"] == "capture.start", f"контекст не доехал до записи: {ctx}"
        assert len(voices) == 1 and "capture.start" in voices[0][0], f"голос назвал не то место: {voices}"
