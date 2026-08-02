# -*- coding: utf-8 -*-
"""Task 5.7, драйверная половина: «значение действует» И «записи идут» — разные факты.

План: `plans/observability-unified-routing.md`, Task 5.7 (A4/A6).

Фреймворк судит о значении в ОДИН момент (`config.reload` → `verified`), а поток
записей — это разница во времени: знать её может только тот, кто делает два
замера. Здесь проверяется вторая половина: сведение двух снимков счётчика
доставки в различимые состояния `delivering` / `losing` / `silent_source` и то,
что молчащий источник НЕ выдаётся за поломку.

Транспорт мокается по образцу `test_restart_verified.py` — судим логику вердикта,
а не сокет. `settle=0` убирает выдержку: живому процессу она нужна, тесту нет.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend_ctl.driver import BackendDriver
from backend_ctl.protocol import delivery_window


def _plane(
    written: int,
    *,
    at: float = 100.0,
    by_channel: Optional[Dict[str, int]] = None,
    **losses: int,
) -> Dict[str, Any]:
    """Секция одной плоскости в форме, в какой её отдаёт `introspect.observability`."""
    section: Dict[str, Any] = {
        "channel_written_records": written,
        "observed_at": at,
        "channel_written_by_channel": dict(by_channel or {}),
    }
    section.update(losses)
    return section


class TestDeliveryWindowIsAboutTheWindowNotTheTotal:
    """Один снимок отвечает «сколько за всю жизнь». Спрашивают про окно."""

    def test_counter_growth_means_delivering(self) -> None:
        w = delivery_window({"logger": _plane(10)}, {"logger": _plane(25, at=101.0)})
        assert w.delivering is True
        assert w.silent_source is False
        assert (w.written_delta, w.written_net) == (15, 15)
        assert w.window_sec == 1.0

    def test_flat_counter_is_silence_not_failure(self) -> None:
        """Вторая половина пары: не выросло ничего → `silent_source`, и это НЕ провал.

        Схлопни это в провал — «ничего не писали» стало бы неотличимо от «пишем в
        никуда», то есть вернулся бы класс дефекта, который задача закрывает.
        """
        w = delivery_window({"logger": _plane(10)}, {"logger": _plane(10, at=101.0)})
        assert w.silent_source is True
        assert (w.delivering, w.losing) == (False, False)

    def test_by_channel_is_a_delta_not_the_lifetime_total(self) -> None:
        """Разбивка по приёмникам за ОКНО. Абсолютные числа отвечали бы не на тот вопрос."""
        w = delivery_window(
            {"logger": _plane(10, by_channel={"main_file": 8, "console": 2})},
            {"logger": _plane(16, at=101.0, by_channel={"main_file": 13, "console": 3})},
        )
        assert w.by_channel == {"main_file": 5, "console": 1}


class TestSilenceMustNotMaskLoss:
    """Счётчик доставки не вырос — это ещё не тишина: записи могли быть ПОТЕРЯНЫ."""

    def test_loss_growth_is_losing_not_silent(self) -> None:
        w = delivery_window(
            {"logger": _plane(10, records_without_channels=0)},
            {"logger": _plane(10, at=101.0, records_without_channels=7)},
        )
        assert w.losing is True
        assert w.loss_delta == 7
        assert w.silent_source is False, "потеря записей выдана за тишину источника"
        assert w.losses == {"logger": {"records_without_channels": 7}}

    def test_written_and_lost_together_are_both_reported(self) -> None:
        """Состояния не исключают друг друга: часть доехала, часть отброшена."""
        w = delivery_window(
            {"logger": _plane(10, channel_refused_records=0)},
            {"logger": _plane(14, at=101.0, channel_refused_records=3)},
        )
        assert (w.delivering, w.losing, w.silent_source) == (True, True, False)

    def test_buffer_losses_count_too(self) -> None:
        """Потери буфера — тот же класс: запись была и не доехала."""
        w = delivery_window(
            {"logger": {**_plane(10), "buffer": {"dropped": 0}}},
            {"logger": {**_plane(10, at=101.0), "buffer": {"dropped": 4}}},
        )
        assert (w.losing, w.silent_source) == (True, False)
        assert w.losses == {"logger": {"buffer.dropped": 4}}


class TestProbeDoesNotProveItself:
    """Читающая команда сама пишет записи. Цена опроса ИЗМЕРЯЕТСЯ, а не считается нулевой."""

    def test_growth_equal_to_self_cost_is_still_silence(self) -> None:
        """ГЛАВНОЕ. На процессе с DEBUG опрос пишет о себе — без вычета `delivering`
        был бы истинным всегда, включая молчащий источник.

        Прирост 3 = цена одного опроса (третий снимок), значит источник молчал.
        """
        w = delivery_window(
            {"logger": _plane(10)},
            {"logger": _plane(13, at=101.0)},
            control={"logger": _plane(16, at=101.0)},
        )
        assert w.self_cost == 3
        assert w.written_net == 0
        assert w.delivering is False
        assert w.silent_source is True

    def test_growth_above_self_cost_is_real_delivery(self) -> None:
        """Вторая половина: вычет не должен съедать настоящий поток."""
        w = delivery_window(
            {"logger": _plane(10)},
            {"logger": _plane(50, at=101.0)},
            control={"logger": _plane(53, at=101.0)},
        )
        assert (w.self_cost, w.written_net, w.delivering) == (3, 37, True)

    def test_self_cost_is_zero_without_a_control_sample(self) -> None:
        """Без третьего снимка цена не выдумывается — она ноль, и это видно в ответе."""
        w = delivery_window({"logger": _plane(10)}, {"logger": _plane(13, at=101.0)})
        assert (w.self_cost, w.written_net, w.delivering) == (0, 3, True)


class TestNoShowingIsNotZero:
    """«Показания нет» и «записей не было» — разные факты, и путать их нельзя."""

    def test_missing_counter_is_named_not_treated_as_silence(self) -> None:
        w = delivery_window({"logger": {"observed_at": 100.0}}, {"logger": _plane(10, at=101.0)})
        assert w.missing == ["before.channel_written_records"]
        assert (w.delivering, w.silent_source, w.losing) == (False, False, False)

    def test_counters_reset_is_its_own_state(self) -> None:
        """Второй снимок МЕНЬШЕ первого: менеджеры пересобраны, окно недостоверно.

        Прежде такое выглядело бы тишиной — то есть «наблюдаемость молчит» вместо
        «мерить было нечем».
        """
        w = delivery_window({"logger": _plane(100)}, {"logger": _plane(3, at=101.0)})
        assert w.counters_reset is True
        assert (w.delivering, w.silent_source, w.losing) == (False, False, False)

    def test_partial_reset_of_one_plane_is_not_hidden_by_a_growing_neighbour(self) -> None:
        """C-3-1: пересобрана ОДНА плоскость, соседняя выросла — сумма это скрывает.

        Счётчики живут в объектах менеджеров, а менеджер у каждой плоскости свой:
        пересборка обнуляет ровно одну. Судить по сумме — это вердикт по одному
        маркеру: logger 500→0 и stats 100→700 дают прирост +100, и окно объявляется
        достоверным при сдвинутой базе. Прод-триггер: авто-рестарт процесса внутри
        settle-окна `config_reload_verified`.
        """
        w = delivery_window(
            {"logger": _plane(500), "stats": _plane(100)},
            {"logger": _plane(0, at=101.0), "stats": _plane(700, at=101.0)},
        )
        assert w.counters_reset is True
        assert w.reset_planes == ["logger"], "плоскость-виновник названа, а не только факт"
        assert (w.delivering, w.silent_source, w.losing) == (False, False, False)

    def test_growth_in_every_plane_is_not_a_reset(self) -> None:
        """Контроль на вакуумность: детектор, срабатывающий всегда, не доказывает ничего."""
        w = delivery_window(
            {"logger": _plane(500), "stats": _plane(100)},
            {"logger": _plane(510, at=101.0), "stats": _plane(700, at=101.0)},
        )
        assert w.counters_reset is False
        assert w.reset_planes == []
        assert w.delivering is True

    def test_plane_that_stopped_reporting_is_a_reset(self) -> None:
        """Плоскость была в первом снимке и пропала во втором: база сдвинута молча.

        Её вклад исчезает из суммы — ровно тот же сдвиг базы, что и обнуление,
        только без отрицательной дельты, по которой его ловили раньше.
        """
        w = delivery_window(
            {"logger": _plane(500), "stats": _plane(100)},
            {"stats": _plane(700, at=101.0)},
        )
        assert w.counters_reset is True
        assert w.reset_planes == ["logger"]

    def test_loss_counter_going_backwards_in_one_plane_is_detected(self) -> None:
        """То же правило для потерь: рост соседней плоскости не отменяет обнуления."""
        w = delivery_window(
            {"logger": _plane(10, channel_refused_records=50), "stats": _plane(10)},
            {
                "logger": _plane(20, at=101.0, channel_refused_records=0),
                "stats": _plane(20, at=101.0, channel_refused_records=90),
            },
        )
        assert w.counters_reset is True
        assert w.reset_planes == ["logger"]

    def test_missing_total_does_not_deny_a_reset_it_can_see(self) -> None:
        """Ф-4 ревью корзины 2: два поля одного ответа не имеют права спорить.

        Ранняя ветка «нет суммарного счётчика» возвращала ``counters_reset=False``
        РЯДОМ с непустым ``reset_planes``: читатель, спрашивающий «база уезжала?»,
        получал «нет» при уехавшей базе. Отсутствие суммы не отменяет того, что по
        конкретной плоскости перезапуск виден.
        """
        # Счётчика доставки нет НИ В ОДНОМ снимке (ранняя ветка), но потери
        # плоскости уехали вниз — база сдвинулась, и это видно поимённо.
        w = delivery_window(
            {"logger": {"observed_at": 100.0, "channel_refused_records": 50}},
            {"logger": {"observed_at": 101.0, "channel_refused_records": 0}},
        )
        assert w.missing, "контроль: ветка та самая — суммарного счётчика нет"
        assert w.reset_planes == ["logger"]
        assert w.counters_reset is True, "ответ противоречит сам себе: reset_planes есть, а reset=False"

    def test_missing_total_without_a_reset_stays_honest(self) -> None:
        """Контроль на вакуумность: без признаков перезапуска флаг не поднимается."""
        w = delivery_window({"stats": {"observed_at": 100.0}}, {"stats": {"observed_at": 101.0}})
        assert w.missing
        assert (w.reset_planes, w.counters_reset) == ([], False)

    def test_total_losses_going_backwards_is_a_reset_even_without_a_named_plane(self) -> None:
        """Пояс к per-plane признаку: суммарные потери НАЗАД — тоже сдвиг базы.

        Плоскость может исчезнуть из снимка не целиком, а лишь потерять секцию
        потерь — тогда виновника поимённо не назвать, а сумма всё равно уехала
        вниз. Без пояса `losing` считался бы «не теряем», то есть отсутствие
        данных выдавалось бы за благополучие.
        """
        w = delivery_window(
            {"logger": _plane(10, channel_refused_records=50)},
            {"logger": _plane(20, at=101.0)},
        )
        assert w.loss_delta < 0, "контроль: сумма потерь действительно уехала назад"
        assert w.counters_reset is True
        assert (w.delivering, w.losing, w.silent_source) == (False, False, False)

    def test_self_cost_larger_than_the_whole_window_is_not_silence(self) -> None:
        """C-2-1: чужой писатель в зазоре after→control съедает вычетом чужую работу.

        `self_cost` меряется зазором и вычитается как «цена своего опроса» — это
        верно ровно в ЭКСКЛЮЗИВНОМ окне. Второй клиент (или GUI-панель, ~5 записей
        на опрос на DEBUG) кладёт свои записи в тот же зазор, и вычет обнуляет
        реально написанное: источник написал 10, вычлось 20 → `silent_source`.
        «Пишем» прочиталось бы как «молчим» — ровно тот класс, который 5.7 закрывала.

        Арифметика вычета тут заведомо недостоверна, и вердикт обязан сказать это
        вслух, а не выдать уверенную тишину.
        """
        w = delivery_window(
            {"logger": _plane(100)},
            {"logger": _plane(110, at=101.0)},
            control={"logger": _plane(130, at=101.1)},
        )
        assert w.self_cost == 20
        assert w.written_delta == 10
        assert w.cost_exceeds_window is True
        assert w.silent_source is False, "тишина НЕ установлена — вычет съел больше окна"
        assert (w.delivering, w.losing) == (False, False)

    def test_cost_equal_to_the_window_is_honest_silence(self) -> None:
        """Контроль: молчащий источник и цена опроса совпадают — это НЕ спорное окно.

        Схлопни этот случай в `cost_exceeds_window` — и молчание по делу снова стало
        бы неотличимо от поломки.
        """
        w = delivery_window(
            {"logger": _plane(100)},
            {"logger": _plane(105, at=101.0)},
            control={"logger": _plane(110, at=101.1)},
        )
        assert (w.self_cost, w.written_delta) == (5, 5)
        assert w.cost_exceeds_window is False
        assert w.silent_source is True

    def test_window_seconds_absent_when_no_timestamps(self) -> None:
        w = delivery_window({"logger": {"channel_written_records": 1}}, {"logger": {"channel_written_records": 2}})
        assert w.window_sec is None
        assert w.delivering is True, "отсутствие часов не отменяет факта прироста"


# --------------------------------------------------------------------------
# Драйвер: два утверждения в одном ответе
# --------------------------------------------------------------------------


def _driver(
    monkeypatch,
    *,
    reload_reply: Dict[str, Any],
    samples: List[Dict[str, Any]],
):
    """Driver, чей `config.reload` отдаёт заготовленный ответ, а `introspect.observability`
    — последовательность снимков (последний повторяется)."""
    d = BackendDriver()
    calls: List[str] = []
    sent_args: List[Any] = []
    state = {"i": 0}

    def fake_send(process, command, args=None, **kw):
        calls.append(command)
        sent_args.append(args)
        if command == "config.reload":
            return {"success": True, "result": dict(reload_reply)}
        if command == "introspect.observability":
            idx = min(state["i"], len(samples) - 1)
            state["i"] += 1
            return {"success": True, "result": {"success": True, "counters": samples[idx]}}
        return {"success": True, "result": {"success": True}}

    monkeypatch.setattr(d, "send_command", fake_send)
    return d, calls, sent_args


def _reload(verified: Optional[Dict[str, Any]], written: int = 10) -> Dict[str, Any]:
    reply: Dict[str, Any] = {
        "success": True,
        "process": "lines",
        "source": "inline",
        "applied": {"log_level": "DEBUG"},
        "counters": {"logger": _plane(written)},
    }
    if verified is not None:
        reply["verified"] = verified
    return reply


class TestVerdictComesFromTheProcess:
    def test_confirmed_verdict_rides_through(self, monkeypatch) -> None:
        d, calls, sent = _driver(
            monkeypatch,
            reload_reply=_reload({"verdict": "confirmed", "checked": 1, "mismatches": [], "unknown_keys": []}),
            samples=[{"logger": _plane(40, at=101.0)}, {"logger": _plane(41, at=101.0)}],
        )
        res = d.config_reload_verified("lines", observability={"log_level": "DEBUG"}, settle=0)
        assert res["verdict"] == "confirmed"
        assert res["delivering"] is True
        # Ровно три обращения: одна смена + два замера (второй измеряет цену опроса).
        assert calls == ["config.reload", "introspect.observability", "introspect.observability"]

    def test_both_samples_ask_for_a_coherent_snapshot(self, monkeypatch) -> None:
        """Оба замера просят `flush=True`, иначе вычет цены опроса — фикция.

        Счётчик считает записи в момент записи, а батчинг сдвигает его на такт
        flush'а: замерено живьём, что без flush контрольный снимок отдаёт РОВНО
        НОЛЬ при реальных ~5 записях на опрос. Тест стережёт не имя параметра, а
        условие, при котором механизм вообще работает.
        """
        d, calls, sent = _driver(
            monkeypatch,
            reload_reply=_reload({"verdict": "confirmed", "checked": 1, "mismatches": [], "unknown_keys": []}),
            samples=[{"logger": _plane(40, at=101.0)}],
        )
        d.config_reload_verified("lines", observability={"log_level": "DEBUG"}, settle=0)
        polls = [args for cmd, args in zip(calls, sent) if cmd == "introspect.observability"]
        assert polls == [{"flush": True}, {"flush": True}], polls

    def test_failed_verdict_rides_through_while_success_stays_true(self, monkeypatch) -> None:
        """A3: `success` и вердикт — РАЗНЫЕ поля и расходятся.

        «Команда сломалась» и «команда ничего не изменила» — разные диагнозы;
        слипнись поля, различие исчезло бы вместе с возможностью его увидеть.
        """
        d, _calls, sent = _driver(
            monkeypatch,
            reload_reply=_reload({"verdict": "failed", "checked": 0, "mismatches": [], "unknown_keys": ["log_levl"]}),
            samples=[{"logger": _plane(10, at=101.0)}],
        )
        res = d.config_reload_verified("lines", observability={"log_levl": "DEBUG"}, settle=0)
        assert res["success"] is True
        assert res["verdict"] == "failed"
        assert res["verified"]["unknown_keys"] == ["log_levl"]

    def test_file_reload_has_no_judgement_and_says_so(self, monkeypatch) -> None:
        """Файловый reload не несёт inline-секции: сравнивать запрошенное не с чем.

        Отсутствие суждения называется вслух, а не выдаётся за подтверждение.
        """
        d, _calls, sent = _driver(
            monkeypatch,
            reload_reply=_reload(None),
            samples=[{"logger": _plane(30, at=101.0)}],
        )
        res = d.config_reload_verified("lines", path="cfg.yaml", settle=0)
        assert res["verdict"] == "unverifiable"
        assert "inline" in res["verdict_reason"]
        assert res["verified"] is None


class TestSilentProcessIsNotAFailure:
    """A4: на пишущей системе `delivering`, на молчащем процессе `silent_source`."""

    def test_silent_process_reports_silence_with_a_confirmed_verdict(self, monkeypatch) -> None:
        d, _calls, sent = _driver(
            monkeypatch,
            reload_reply=_reload({"verdict": "confirmed", "checked": 1, "mismatches": [], "unknown_keys": []}),
            samples=[{"logger": _plane(10, at=101.0)}],
        )
        res = d.config_reload_verified("lines", observability={"log_level": "DEBUG"}, settle=0)
        assert res["silent_source"] is True
        assert res["delivering"] is False
        # Вердикт значения — подтверждён: тишина источника его не отменяет.
        assert res["verdict"] == "confirmed"
        assert res["success"] is True

    def test_missing_baseline_is_named_not_silently_zero(self, monkeypatch) -> None:
        """Без снимка-базы в ответе окно не строится — и это сказано, а не подменено тишиной."""
        reply = _reload({"verdict": "confirmed", "checked": 1, "mismatches": [], "unknown_keys": []})
        reply.pop("counters")
        d, _calls, sent = _driver(monkeypatch, reload_reply=reply, samples=[{"logger": _plane(99, at=101.0)}])
        res = d.config_reload_verified("lines", observability={"log_level": "DEBUG"}, settle=0)
        assert "baseline_missing" in res
        assert (res["delivering"], res["silent_source"]) == (False, False)
        assert res["missing"] == ["before.channel_written_records"]
