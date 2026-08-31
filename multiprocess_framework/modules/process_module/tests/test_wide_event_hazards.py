# -*- coding: utf-8 -*-
"""Опасные места МЕХАНИЗМА широкой записи (Ф4, задача 4.1) — тесты автора.

Здесь не приёмка. Приёмку от критериев пишет независимый тестер, не видевший
реализации; эти тесты сторожат ровно то, что видно только автору: гонку счёта,
атомарность подмены ручек, поведение без сшивки, конверт поверх нагрузки, форму
заглушки вложенного контекста и потолок карты родов.

Каждый класс ниже отвечает на вопрос «что сломается в ЭТОМ механизме, учитывая,
как он собран», а не «делает ли он то, что просили».
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.process_module.generic import frame_trace
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    EVENT_SELECTOR_ATTR,
    WideEventSelector,
    apply_event_selector,
    event_plane_report,
    wire_event_selector,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, SubPluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices


def _ctx(**kwargs: Any) -> PluginContext:
    """Контекст поверх дубля сервисов. Селектор передаётся НАСТОЯЩИЙ."""
    return PluginContext(services=MockProcessServices(**kwargs), plugin_name="probe")


def _events(svc: MockProcessServices) -> List[Dict[str, Any]]:
    """Записи, доехавшие до плоскости логов (у дубля она — список)."""
    return [entry for entry in svc.logs if str(entry.get("msg", "")).startswith("event ")]


class TestDisabledMeansOneThingNotTwo:
    """Отключённость обязана иметь ОДНО исполнение, а не два похожих.

    Селектора может не быть вовсе (сшивки не было), а может быть настроенный на
    дефолт 0/0. Разъедься эти два случая — «поток молчит» означало бы разное на
    соседних процессах, и разбор начинался бы с вопроса «а сшивка-то была?».
    """

    def test_no_selector_at_all_writes_fronts_and_drops_the_stream(self) -> None:
        ctx = _ctx()  # event_selector=None — процесс без сшивки

        assert ctx.write_event("inspection", "поток") is False
        assert ctx.write_event("verdict", "фронт", decisive=True) is True

        texts = [e["msg"] for e in _events(ctx.services)]
        assert texts == ["event verdict: фронт trace="]

    def test_default_selector_decides_exactly_the_same(self) -> None:
        ctx = _ctx(event_selector=WideEventSelector())  # first_n=0, every_mth=0

        assert ctx.write_event("inspection", "поток") is False
        assert ctx.write_event("verdict", "фронт", decisive=True) is True

        assert len(_events(ctx.services)) == 1

    def test_missing_road_is_a_named_answer_not_an_attribute_error(self) -> None:
        """У процесса без плоскости и без селектора вызов не падает, а отвечает.

        Тот самый класс, что дважды чинили на ``log_warning``: метод объявлен
        протоколом, а на живом объекте его нет — и ветка штатной деградации
        роняет линию вместо записи.
        """
        ctx = _ctx()
        for road in ("write_event",):
            assert callable(getattr(ctx, road, None))
        assert ctx.write_event("inspection", "", unit=None, decisive=False) is False


class TestEnvelopeOutranksPayload:
    """Прикладное поле не имеет права увести запись в чужой род (правило конверта)."""

    def test_application_field_named_event_does_not_change_the_kind(self) -> None:
        ctx = _ctx(event_selector=WideEventSelector(first_n=1))

        assert ctx.write_event("inspection", "суть", event="чужое", trace_id="подделка") is True

        entry = _events(ctx.services)[0]
        assert entry["event"] == "inspection"
        assert entry["trace_id"] == ""

    def test_a_payload_key_named_kind_does_not_raise_on_the_line(self) -> None:
        """``kind``/``summary`` позиционные ровно ради этого (урок write_document).

        Будь они обычными параметрами, вызов с ключом ``kind`` в нагрузке падал бы
        ``TypeError: got multiple values`` — то есть запись терялась бы С
        ИСКЛЮЧЕНИЕМ прямо на линии, что хуже подмены, от которой защита ставилась.
        """
        ctx = _ctx(event_selector=WideEventSelector(first_n=1))
        payload = {"kind": "прикладной род", "summary": "прикладная суть"}

        assert ctx.write_event("inspection", "суть", **payload) is True

        entry = _events(ctx.services)[0]
        assert entry["event"] == "inspection"
        assert entry["kind"] == "прикладной род"


class TestCarrierParameterNameCostsTheRecordNotTheLine:
    """Третий, более глубокий случай того же класса: имя ЧУЖОЙ сигнатуры.

    Позиционность фасада тут не спасает — параметр принадлежит носителю
    (``msg`` у протокола, ``message`` у ``ObservableMixin``). Проверяем, что цена
    — запись, а не линия, и что потеря названа и посчитана.
    """

    def test_line_survives_and_the_loss_is_counted(self) -> None:
        ctx = _ctx(event_selector=WideEventSelector(first_n=10))

        # `msg` — имя первого параметра `MockProcessServices.log_info`.
        assert ctx.write_event("inspection", "суть", msg="столкновение") is False

        report = event_plane_report(ctx.services)["events"]
        assert report["refused"] == 1
        assert report["kinds"]["inspection"]["selected"] == 1, "отбор запись пропустил — отказал носитель"

    def test_the_cause_is_named_exactly_once(self) -> None:
        ctx = _ctx(event_selector=WideEventSelector(first_n=10))

        for _ in range(5):
            ctx.write_event("inspection", "суть", msg="столкновение")

        warnings = [e for e in ctx.services.logs if e["level"] == "WARNING" and "[events]" in e["msg"]]
        assert len(warnings) == 1, "голос на каждую единицу превратил бы отказ в шторм"
        assert event_plane_report(ctx.services)["events"]["refused"] == 5, "а число обязано расти дальше"

    def test_the_real_carrier_parameter_name_is_covered_too(self) -> None:
        """У живого носителя первый параметр зовётся ``message``, а не ``msg``.

        Два разных имени у одной дороги — не выдумка теста: ``IProcessServices``
        объявляет ``msg``, ``ObservableMixin`` реализует ``message``. Списка
        запретных имён в фасаде поэтому и нет — он был бы копией чужой сигнатуры.
        """

        class _RealShapeServices(MockProcessServices):
            def log_info(self, message: str, **kwargs: Any) -> None:  # type: ignore[override]
                self._record("INFO", message, kwargs)

        ctx = PluginContext(services=_RealShapeServices(event_selector=WideEventSelector(first_n=10)))

        assert ctx.write_event("inspection", "суть", message="столкновение") is False
        assert event_plane_report(ctx.services)["events"]["refused"] == 1


class TestSpansAreNamedNotGuessed:
    """«Не мерили» и «мерили, спанов нет» — разные факты, и путать их нельзя."""

    def test_flag_off_says_off_in_the_record_itself(self) -> None:
        ctx = _ctx(event_selector=WideEventSelector(first_n=1))
        unit = {"trace_id": "abc", "trace": [{"kind": "process", "ms": 1.0}]}

        assert frame_trace.enabled() is False, "предпосылка: в тестовой среде флаг снят"
        ctx.write_event("inspection", "суть", unit=unit)

        assert _events(ctx.services)[0]["spans"] == "off"

    def test_flag_on_carries_the_spans_of_the_unit(self) -> None:
        ctx = _ctx(event_selector=WideEventSelector(first_n=2))
        unit = {"trace_id": "abc", "trace": [{"kind": "process", "ms": 1.0}]}
        saved = frame_trace._ENABLED
        frame_trace._ENABLED = True
        try:
            ctx.write_event("inspection", "со спанами", unit=unit)
            ctx.write_event("inspection", "без единицы", unit=None)
        finally:
            frame_trace._ENABLED = saved

        with_unit, without_unit = _events(ctx.services)
        assert with_unit["spans"] == [{"kind": "process", "ms": 1.0}]
        assert without_unit["spans"] == [], "мерили, но единицы не дали — это не 'off'"

    def test_trace_id_rides_in_the_text_because_the_index_ignores_extra(self) -> None:
        """Полнотекстовый индекс стора смотрит в ``message``, а не в ``extra``."""
        ctx = _ctx(event_selector=WideEventSelector(first_n=1))

        ctx.write_event("inspection", "суть", unit={"trace_id": "deadbeef"})

        entry = _events(ctx.services)[0]
        assert "deadbeef" in entry["msg"]
        assert entry["msg"] == "event inspection: суть trace=deadbeef"

    def test_the_text_shape_is_constant_without_a_trace(self) -> None:
        """Форма постоянна и без следа: переменная сломала бы поиск по образцу."""
        ctx = _ctx(event_selector=WideEventSelector(first_n=1))

        ctx.write_event("inspection", "суть")

        assert _events(ctx.services)[0]["msg"] == "event inspection: суть trace="


class TestSelectorArithmetic:
    """Лесенка отбора: что именно проходит и чего она не сдвигает."""

    def test_zero_zero_lets_nothing_through(self) -> None:
        sel = WideEventSelector(0, 0)
        assert [sel.select("u") for _ in range(5)] == [False] * 5

    def test_zero_is_off_here_unlike_the_logger_sampler(self) -> None:
        """Ловушка имён: у дросселя логгера ``every_mth=0`` приводится к 1.

        Там ноль означал бы деление на ноль на горячем пути и потому запрещён
        (``min=1``); здесь он — штатное «после первых N не проходит ничего».
        Одинаковые слова, противоположный смысл нуля — сверено тестом, а не глазом.
        """
        from multiprocess_framework.modules.logger_module.core.sampling import RateSampler

        assert RateSampler(first_n=1, every_mth=0)._every_mth == 1
        assert WideEventSelector(1, 0).knobs == (1, 0)
        sel = WideEventSelector(1, 0)
        assert [sel.select("u") for _ in range(4)] == [True, False, False, False]

    def test_first_n_then_every_mth(self) -> None:
        sel = WideEventSelector(2, 3)
        assert [sel.select("u") for _ in range(9)] == [
            True,
            True,  # первые два
            False,
            False,
            True,  # затем каждая третья
            False,
            False,
            True,
            False,
        ]

    def test_the_ladder_is_counted_inside_the_kind(self) -> None:
        sel = WideEventSelector(1, 0)
        assert sel.select("a") is True
        assert sel.select("b") is True, "у соседнего рода своя лесенка"
        assert sel.select("a") is False

    def test_decisive_does_not_shift_the_stream_ladder(self) -> None:
        """Серия фронтов не имеет права менять выборку рядовых единиц.

        Считай мы фронты общим счётчиком — «каждая третья» означала бы разное в
        спокойную минуту и под серией отбраковок, то есть выборка зависела бы от
        того, что она измеряет.

        **Параметры выбраны так, чтобы совпадения не было.** Первая редакция брала
        ``(0, 3)`` и оставалась ЗЕЛЁНОЙ под инъекцией «фронт двигает счётчик»: при
        одном фронте на каждую потоковую номер удваивается, а ``2n % 3 == 0``
        равносильно ``n % 3 == 0`` — тест сверял совпадение, а не свойство.
        Найдено собственной инъекцией; ``first_n=2`` вместе с ``every_mth=3``
        разводит две последовательности с первого же шага.
        """
        sel = WideEventSelector(2, 3)
        seen = []
        for _ in range(8):
            sel.select("u", decisive=True)  # фронты между потоковыми
            seen.append(sel.select("u"))
        assert seen == [True, True, False, False, True, False, False, True]

    def test_counters_split_the_three_facts(self) -> None:
        sel = WideEventSelector(1, 0)
        sel.select("u", decisive=True)
        sel.select("u")
        sel.select("u")
        assert sel.counters()["u"] == {"selected": 1, "skipped": 1, "decisive": 1}


class TestKnobsSwapDoesNotEatTheState:
    """Пересборка меняет ПАРАМЕТРЫ, а не состояние."""

    def test_reconfigure_keeps_the_per_kind_count(self) -> None:
        """Иначе оператор, дёрнувший конфиг под штормом, получил бы шторм заново.

        Сброс счёта означал бы ``first_n`` заново на каждом ``config.reload`` —
        то есть «идемпотентность ≠ монотонность» ровно там, где ручку и крутят.
        """
        sel = WideEventSelector(2, 0)
        assert [sel.select("u") for _ in range(3)] == [True, True, False]

        sel.configure(2, 0)  # та же пара, новая пересборка

        assert sel.select("u") is False, "счёт продолжился, а не начался"
        assert sel.counters()["u"]["selected"] == 2

    def test_knobs_are_read_as_one_pair(self) -> None:
        """Подмена — одним кортежем: читатель не может застать полусмену."""
        sel = WideEventSelector(1, 2)
        before = sel.knobs
        sel.configure(7, 9)
        assert before == (1, 2) and sel.knobs == (7, 9)
        assert isinstance(sel.knobs, tuple) and len(sel.knobs) == 2

    def test_negative_is_clamped_not_refused(self) -> None:
        """Границы держит схема на входе в слой; здесь — последняя черта, не вторая."""
        assert WideEventSelector(-5, -1).knobs == (0, 0)


class TestKindMapIsSaturable:
    """Карта родов растёт от того, что кладёт приложение, — значит обязана насыщаться."""

    def test_a_kind_built_from_data_does_not_leak_the_map(self) -> None:
        sel = WideEventSelector(1, 0)
        for i in range(WideEventSelector.KIND_CEILING + 20):
            sel.select(f"unit_{i}")

        counters = sel.counters()
        assert len(counters) == WideEventSelector.KIND_CEILING + 1, "потолок + общий бакет"
        assert WideEventSelector.OVERFLOW_KIND in counters
        assert sel.kinds_saturated == 20

    def test_the_overflow_bucket_keeps_deciding(self) -> None:
        """Насыщение — не отказ: записи продолжают отбираться, просто общей лесенкой."""
        sel = WideEventSelector(1, 0)
        for i in range(WideEventSelector.KIND_CEILING):
            sel.select(f"unit_{i}")
        assert sel.select("перелив-1") is True, "первая в общем бакете проходит по first_n"
        assert sel.select("перелив-2") is False


class TestConcurrentUnitsAreNotLost:
    """Решение об отборе — три шага (чтение, арифметика, запись), и потоков много."""

    def test_two_threads_are_never_inside_the_decision_together(self) -> None:
        """Взаимное исключение проверяется НАПРЯМУЮ, а не через шторм потоков.

        **Почему не шторм.** Восемь потоков по 2000 записей оставались ЗЕЛЁНЫМИ
        под инъекцией «лок снят» — измерено, в том числе с
        ``sys.setswitchinterval(1e-6)`` и с картой, отдающей GIL внутри чтения.
        Причина названа честно: в CPython 3.12 ``slot[0] += 1`` идёт
        прямолинейной цепочкой байт-кодов без проверки eval-breaker, а
        ``time.sleep(0)`` отпускает GIL, но не обязан отдать его ждущему. Тест на
        гонку, которая не воспроизводится, — не доказательство, а его имитация.

        Здесь проверяется само СВОЙСТВО: барьер на двоих стоит внутри критической
        секции (в чтении карты родов). Под локом второй поток до него не доходит
        — барьер разваливается по сроку, и это ОЖИДАЕМЫЙ исход. Без лока оба
        оказываются внутри одновременно, барьер срабатывает, и факт совместного
        входа записывается. Свидетельство прямое: не «числа сошлись», а «двоих
        внутри не было».

        Что защищает лок на самом деле: составную последовательность «прочитал
        графу → решил → записал» и заведение новой графы (``get`` + запись — два
        шага). На сборке без GIL (3.13t и дальше) сюда добавятся и сами
        инкременты; проверка от этого не меняется.
        """
        together: List[str] = []
        gate = threading.Barrier(2)

        class _Probe(dict):
            """Карта родов, отмечающая совместный вход в критическую секцию."""

            def get(self, key, default=None):  # type: ignore[override]
                try:
                    gate.wait(timeout=0.5)
                    together.append(str(key))
                except threading.BrokenBarrierError:
                    pass  # второго внутри не было — ровно то, чего мы ждём
                return super().get(key, default)

        sel = WideEventSelector(1, 0)
        sel._kinds = _Probe()  # type: ignore[assignment]

        threads = [threading.Thread(target=lambda: sel.select("u")) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            # Дедлайн, а не бесконечный join: тест, который ВИСНЕТ вместо
            # падения, прячет регрессию за таймаутом прогона.
            t.join(timeout=30)
        assert not any(t.is_alive() for t in threads), "зависший тест хуже отсутствующего"

        assert together == [], "два потока оказались внутри решения одновременно — исключения нет"
        stats = sel.counters()["u"]
        assert stats["selected"] + stats["skipped"] == 2, "и обе единицы посчитаны"

    def test_the_facade_writes_exactly_what_the_selector_selected(self) -> None:
        """Число строк в плоскости обязано сойтись со счётчиком ``selected``."""
        ctx = _ctx(event_selector=WideEventSelector(0, 3))
        lock = threading.Lock()
        original = ctx.services.log_info

        def synchronized(msg: str, **kwargs: Any) -> None:
            # Список дубля — не потокобезопасный приёмник; синхронизируем ЕГО,
            # чтобы тест судил селектор, а не list.append.
            with lock:
                original(msg, **kwargs)

        ctx.services.log_info = synchronized  # type: ignore[method-assign]
        ctx.log_info = synchronized  # type: ignore[method-assign]

        def worker() -> None:
            for _ in range(300):
                ctx.write_event("inspection", "поток")

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not any(t.is_alive() for t in threads)

        selected = event_plane_report(ctx.services)["events"]["kinds"]["inspection"]["selected"]
        assert len(_events(ctx.services)) == selected == 400


class TestSubContextCarriesTheRoadVerbatim:
    """Урок четырёх заглушек 1.1: заглушка «по форме» роняет именованный вызов."""

    def test_the_stub_accepts_the_reference_signature_by_name(self) -> None:
        sub = SubPluginContext()
        assert sub.write_event("inspection", "суть", unit={"trace_id": "x"}, decisive=True, roi=[]) is False

    def test_the_stub_accepts_a_payload_key_named_kind(self) -> None:
        sub = SubPluginContext()
        assert sub.write_event("inspection", "суть", **{"kind": "прикладной"}) is False

    def test_from_parent_forwards_the_road(self) -> None:
        ctx = _ctx(event_selector=WideEventSelector(first_n=1))
        sub = SubPluginContext.from_parent(ctx, config={})

        assert sub.write_event("inspection", "из вложенного") is True
        assert len(_events(ctx.services)) == 1

    def test_the_road_is_listed_in_the_single_enumeration(self) -> None:
        """Список дорог живёт в ОДНОМ месте — три копии уже расходились (Н-6)."""
        import inspect

        source = inspect.getsource(SubPluginContext.from_parent)
        assert source.count('"write_event"') == 1

    def test_the_stub_signature_repeats_the_facade_verbatim(self) -> None:
        """Оракул сигнатуры, а не обещание про оракул.

        Докстринг заглушки ссылался на «оракул, который это сторожит», а оракула
        для ЭТОЙ дороги не было: замена заглушки на ``(*args, **kwargs)`` не
        красила ни одного теста (найдено ревью 4.1). Уверенное объяснение без
        воспроизведения переживает баг — вот воспроизведение.

        Сверяется полная форма, включая косую черту позиционных: именно она
        держит правило «прикладной ключ ``kind`` не роняет линию», и потерять её
        в заглушке значит потерять правило на половине дорог.
        """
        import inspect

        from multiprocess_framework.modules.process_module.plugins.base import _noop_event

        facade = list(inspect.signature(PluginContext.write_event).parameters.values())[1:]  # без self
        stub = list(inspect.signature(_noop_event).parameters.values())

        assert [(p.name, p.kind, p.default) for p in stub] == [(p.name, p.kind, p.default) for p in facade]


class TestWiringAndTheThirdPointOfTheRoad:
    """Сшивка и пересборка: ручка обязана доехать до ЖИВОГО объекта."""

    class _Svc:
        """Процесс в объёме, который читают сшивка и readback."""

        def __init__(self, section: Any = None) -> None:
            self.name = "probe"
            self._config = {"observability_app": {"events": section} if section is not None else {}}
            self.warnings: List[str] = []

        def get_config(self, key: str, default: Any = None) -> Any:
            return self._config.get(key, default)

        def log_warning(self, msg: str, **kwargs: Any) -> None:
            self.warnings.append(msg)

        def log_info(self, msg: str, **kwargs: Any) -> None:
            pass

    def test_wiring_reads_the_resolved_layers(self) -> None:
        svc = self._Svc({"first_n": 3, "every_mth": 7})

        selector = wire_event_selector(svc)

        assert selector is not None and selector.knobs == (3, 7)
        assert getattr(svc, EVENT_SELECTOR_ATTR) is selector

    def test_a_process_without_the_section_still_gets_a_selector(self) -> None:
        """«Ключа нет» — не «механизма нет»: фронты обязано быть где считать."""
        svc = self._Svc()

        selector = wire_event_selector(svc)

        assert selector is not None and selector.knobs == (0, 0)
        assert event_plane_report(svc)["events"]["declared"] is True

    def test_report_of_a_process_without_wiring_is_distinguishable(self) -> None:
        """Ноль без сшивки и ноль при полном отсеве обязаны различаться."""
        assert event_plane_report(self._Svc())["events"] == {
            "declared": False,
            "first_n": 0,
            "every_mth": 0,
            "kinds": {},
            "refused": 0,
            "kinds_saturated": 0,
        }

    def test_a_missing_section_returns_to_the_bottom_layer(self) -> None:
        """Ключ ушёл из слоёв → ручка возвращается к дефолту, а не залипает.

        Пересборка есть ЕДИНСТВЕННЫЙ способ выразить «ключ удалён»: дельта
        удаления не умеет по построению. Верни мы здесь прежнюю пару вместо
        дефолта — истечение срока и сброс `observability_reset` объявлялись бы
        успешными, а отбор оставался бы на снятой правке. Это «следствие без
        причины», худший из исходов: readback показывает старое число и он ПРАВ,
        потому что оно и действует.
        """
        selector = WideEventSelector(9, 9)

        applied = apply_event_selector(selector, None)

        assert selector.knobs == (0, 0), "снятый ключ обязан вернуть дефолт L0"
        assert applied == {"first_n": 0, "every_mth": 0}

    def test_garbage_keeps_the_previous_knobs_and_says_so(self) -> None:
        """Опечатка в отборе не имеет права стоить применения всей секции."""
        svc = self._Svc()
        selector = WideEventSelector(4, 5)

        applied = apply_event_selector(selector, {"first_n": -5}, svc)

        assert selector.knobs == (4, 5), "действует прежнее"
        assert applied == {"first_n": 4, "every_mth": 5}
        assert any("observability.events" in w for w in svc.warnings), "и это названо вслух"

    def test_apply_reaches_the_live_object_through_the_rebuild_seam(self) -> None:
        """Проверка стоит в ШВЕ пересборки, а не в обход него.

        Правку, не дошедшую до селектора, видно только отсюда: сам селектор
        согласится с любой парой, которую ему передадут, а вопрос в том, передаст
        ли её пересборка.
        """
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            ObservabilityLayers,
        )
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            apply_observability_layers,
        )

        layers = ObservabilityLayers(app={"events": {"first_n": 1, "every_mth": 4}})
        selector = WideEventSelector()
        assert selector.knobs == (0, 0)

        applied = apply_observability_layers(layers, event_selector=selector, origin="test")

        assert selector.knobs == (1, 4), "живой объект перенастроен пересборкой"
        assert applied["events"] == {"first_n": 1, "every_mth": 4}

    def test_the_knob_is_confirmable_not_merely_applied(self) -> None:
        """Ручка обязана ПОДТВЕРЖДАТЬСЯ тем же вердиктом, что соседи по секции.

        Живой стенд 2026-08-16: `config_reload_verified` на восьми процессах
        отвечал `unverifiable` при `checked=0` — секция `events` идёт мимо
        `expand_observability` (менеджера у неё нет), поэтому в `expected`
        сверщика её не было, и подтверждать оказалось нечем. Применение при этом
        работало: `events_applied={'first_n': 3, 'every_mth': 7}`, readback
        показывал новую пару. То есть «применено» и «подтверждено» разошлись —
        ровно тот зазор, который правило трёх точек и закрывает.
        """
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            observability_effective,
            observability_verified,
        )

        selector = WideEventSelector(5, 11)
        effective = observability_effective(event_selector=selector)
        assert effective["events"] == {"first_n": 5, "every_mth": 11}, "readback живого объекта"

        good = observability_verified({"events": {"first_n": 5, "every_mth": 11}}, effective)
        assert good["verdict"] == "confirmed" and good["checked"] == 2

        # Пара к предыдущему: расхождение обязано называться расхождением, иначе
        # «confirmed» держался бы на том, что сверщик согласен со всем подряд.
        bad = observability_verified({"events": {"first_n": 5, "every_mth": 12}}, effective)
        assert bad["verdict"] == "failed"
        assert [m["key"] for m in bad["mismatches"]] == ["events.every_mth"]

    def test_the_file_watcher_road_reaches_the_live_selector_too(self) -> None:
        """У ручки ДВЕ дороги, и вторая была мертва (найдено инъекцией 2026-08-16).

        ``config.reload`` доносил ручку до селектора, а правка ФАЙЛА — нет:
        ``make_observability_on_reload`` собирал пересборку без него, и та же
        секция в ``system.yaml`` меняла слой, не меняя отбор. Разошлись бы они
        молча: обе дороги отвечают «применено», а ведут себя по-разному. Урок
        «одна дверь — две дороги, нужны два стража» дословно.
        """
        from multiprocess_framework.modules.config_module import Config
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            ObservabilityLayers,
        )
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            make_observability_on_reload,
        )

        selector = WideEventSelector()
        layers = ObservabilityLayers()
        on_reload = make_observability_on_reload(event_selector=selector, layers=layers)

        on_reload(Config(initial_data={"observability": {"events": {"first_n": 6, "every_mth": 9}}}))

        assert selector.knobs == (6, 9), "правка файла обязана дойти до живого селектора"

    def test_rebuild_without_a_selector_does_not_fail(self) -> None:
        """Пересборка идёт и на процессах, где широких записей никто не пишет."""
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            ObservabilityLayers,
        )
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            apply_observability_layers,
        )

        applied = apply_observability_layers(
            ObservabilityLayers(app={"events": {"first_n": 2}}),
            event_selector=None,
            origin="test",
        )
        assert "events" not in applied


class TestEveryRoadOfTheKnobReachesTheLiveSelector:
    """Дорог у ручки ЧЕТЫРЕ, и сторожить надо каждую — по отдельности.

    Ревью 4.1: сторожилась ровно одна (`config.reload`), а инъекция по одной
    строке в каждой из остальных давала НОЛЬ красных. Дороги при этом были
    исправны — не хватало именно стражей, и «исправна сегодня» без стража
    означает «сломается молча завтра».

    Точка входа у каждого теста — ПРОДОВАЯ функция, а не фабрика внутри неё:
    страж на фабрике оставляет незакрытым как раз то место, где аргумент
    забывают передать.
    """

    class _Clock:
        def __init__(self) -> None:
            self.now = 1000.0

        def __call__(self) -> float:
            return self.now

        def advance(self, delta: float) -> None:
            self.now += delta

    class _Svc:
        """Процесс в объёме, который читают подметальщик и пересборка."""

        name = "seg"
        logger_manager = None
        error_manager = None
        stats_manager = None
        _heartbeat = None

        def __init__(self, app_events: dict) -> None:
            self._config = {"observability_app": {"events": app_events}}
            self.event_selector = WideEventSelector(app_events["first_n"], app_events["every_mth"])

        def get_config(self, key: str, default: Any = None) -> Any:
            return self._config.get(key, default)

        def _log_info(self, *a: Any, **k: Any) -> None: ...

        def _log_warning(self, *a: Any, **k: Any) -> None: ...

        def _log_debug(self, *a: Any, **k: Any) -> None: ...

        def _log_error(self, *a: Any, **k: Any) -> None: ...

        log_info = _log_info

    def test_ttl_return_reaches_the_live_selector(self) -> None:
        """Дорога 2 — истечение срока правки (продовый вход ``sweep_session_ttl``).

        Не передай подметальщик селектор — возврат ОБЪЯВЛЯЛСЯ бы (ключ снят,
        отчёт написан), а отбор остался бы на истёкшей правке. Ровно тот дефект,
        который на телеметрии уже ловили: следствие без причины.
        """
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            process_observability_layers,
        )
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            apply_observability_layers,
        )
        from multiprocess_framework.modules.process_module.managers.observability_ttl import (
            sweep_session_ttl,
        )

        svc = self._Svc({"first_n": 1, "every_mth": 2})
        layers = process_observability_layers(svc)
        clock = self._Clock()
        layers.clock = clock
        layers.session_set("events.first_n", 50, ttl=60, origin="test")
        apply_observability_layers(layers, event_selector=svc.event_selector, origin="test")
        assert svc.event_selector.knobs == (50, 2), "предпосылка: правка подействовала"

        clock.advance(61)
        report = sweep_session_ttl(svc)

        assert report is not None and report["keys"] == ["events.first_n"]
        assert svc.event_selector.knobs == (1, 2), "срок вышел, а отбор остался на снятой правке"

    def test_recipe_switch_returns_the_selector_on_the_orchestrator(self) -> None:
        """Дорога 3 — switch рецепта у ПМ (продовый вход ``_reset_observability_sessions``).

        Оркестратор чистит СВОЙ слой сессии сам, минуя ``config.reload``. Без
        селектора в этой пересборке ПМ после switch держал бы прежний отбор при
        пустом L3 — то есть провенанс и действующее расходились бы молча. Ровно
        та асимметрия, от которой эта функция и должна защищать (R6).
        """
        from multiprocess_framework.modules.process_manager_module.process.process_manager_process import (
            ProcessManagerProcess,
        )
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            process_observability_layers,
        )
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            apply_observability_layers,
        )

        # Оркестратор собирается через `__new__` с минимальным набором полей, а не
        # конструктором: полный `ProcessManagerProcess` тянет реестр процессов, и
        # `_broadcast_command` в конце метода ходит по нему. На общем прогоне это
        # дало ОДИН случайный красный из шести — флейк по чужой причине, который
        # прячет настоящую регрессию за «перезапусти». Тело проверяемого метода
        # при этом исполняется целиком, включая строку, ради которой тест и стоит.
        pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
        pm.name = "ProcessManager"
        pm.logger_manager = pm.error_manager = pm.stats_manager = None
        pm._heartbeat = None
        pm._config = {"observability_app": {"events": {"first_n": 1, "every_mth": 2}}}
        pm.get_config = lambda key, default=None: pm._config.get(key, default)  # type: ignore[method-assign]
        pm._log_info = lambda *a, **k: None  # type: ignore[method-assign]
        pm._log_error = lambda *a, **k: None  # type: ignore[method-assign]
        pm._broadcast_command = lambda *a, **k: 0  # type: ignore[method-assign]
        pm.event_selector = WideEventSelector(1, 2)
        layers = process_observability_layers(pm)
        layers.session_set("events.first_n", 50, ttl=0, origin="test")
        apply_observability_layers(layers, event_selector=pm.event_selector, origin="test")
        assert pm.event_selector.knobs == (50, 2), "предпосылка: правка подействовала"

        pm._reset_observability_sessions("switch:тест")

        assert layers.session_keys() == (), "слой сессии очищен"
        assert pm.event_selector.knobs == (1, 2), "L3 пуст, а отбор остался на снятой ручке"

    # Сторож дороги 4 (оба файловых watcher'а оркестратора) живёт в
    # `app_module/tests/test_observability_watcher_events.py`, а не здесь:
    # `process_module` слоем НИЖЕ `app_module`, и импорт оркестратора отсюда
    # ломает контракт слоёв (`test_no_other_framework_module_imports_app_module`).
    # Найдено корневым гейтом после первой редакции этого файла.

    def test_config_reload_answers_with_the_applied_knobs(self) -> None:
        """Дорога 1 — ответ команды несёт ПРИМЕНЁННОЕ, а не эхо запроса.

        ``events_applied`` задокументирован в CONTROL_PANEL как то, по чему судит
        оператор. Без него ответ ``success: true`` означал бы «команда не упала»,
        а не «отбор стал таким» — различие, ради которого поле и заведено.
        """
        from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands

        class _Cmds:
            def __init__(self) -> None:
                self.handlers: Dict[str, Any] = {}

            def register_command(self, name, handler, **kw):
                self.handlers[name] = handler
                return True

        svc = self._Svc({"first_n": 0, "every_mth": 0})
        svc.command_manager = _Cmds()  # type: ignore[attr-defined]
        bc = BuiltinCommands(svc)
        bc._register_observability_commands()

        handler = svc.command_manager.handlers["config.reload"]
        res = handler({"observability": {"events": {"first_n": 3, "every_mth": 4}}})

        assert res["success"] is True
        assert res["events_applied"] == {"first_n": 3, "every_mth": 4}
        assert svc.event_selector.knobs == (3, 4)


class TestSchemaGuardsTheDoor:
    """Границы держит схема на входе в слой — второго предохранителя нет."""

    @pytest.mark.parametrize("section", [{"first_n": -1}, {"every_mth": -1}, {"first_n": "много"}])
    def test_bad_values_are_refused_by_the_schema(self, section: dict) -> None:
        from multiprocess_framework.modules.process_module.configs.observability_config import (
            ObservabilityEventsConfig,
        )

        with pytest.raises(Exception):
            ObservabilityEventsConfig.model_validate(section)

    def test_the_key_is_known_to_the_session_layer(self) -> None:
        """Иначе ``config.reload`` отверг бы ручку как незнакомое имя (5.4)."""
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            validate_layer_section,
        )

        validate_layer_section({"events": {"first_n": 1, "every_mth": 2}}, layer="session")
        with pytest.raises(ValueError):
            validate_layer_section({"events": {"first_n": -1}}, layer="session")
