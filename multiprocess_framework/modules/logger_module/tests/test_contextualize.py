# -*- coding: utf-8 -*-
"""Ф4.3: опасности механизма ``contextualize`` — тесты АВТОРА.

Это не тесты контракта «поля доезжают до записи» (его сторожит
``test_context_isolation.py``, написанный независимым тестировщиком по
постановке Ф0.5), а тесты того, что ломается именно в ЭТОМ механизме, потому
что он так устроен:

  * значение форточки — общий словарь, и правка на месте видна всем потокам
    сразу (тот же класс, что у ``_context_stacks``);
  * возврат идёт по токену, и ровно на нём держатся вложенность и
    исключения — ``set({})`` вместо ``reset(token)`` выглядит эквивалентно и
    молча стирает слой, положенный снаружи;
  * форточка живёт в самом низком слое приоритета, поэтому имя, занятое базой
    процесса, отсюда до записи не доедет — и никто об этом не узнает.

Почему ``contextualize`` вообще заведён, хотя те же четыре строки писались
руками: правила «пересоздавать целиком» и «возвращать по токену» нарушаются
тихо, а цена нарушения — чужой ``trace_id`` в записях следующего кадра.
"""

from __future__ import annotations

import threading

from multiprocess_framework.modules.logger_module.core.log_config import LogLevel
from multiprocess_framework.modules.logger_module.core.logger_manager import (
    LoggerManager,
    contextualize,
    log_context,
)


class _Tap:
    """Tap-приёмник (IChannel-совместим по ``write``), безопасный для потоков.

    Копирует ``extra`` на месте: снимок обязан зафиксировать состояние на
    момент ``write()``, иначе разделяемая мутация пряталась бы в самом тапе.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.records: list[dict] = []

    def write(self, record: dict) -> None:
        snapshot = dict(record)
        snapshot["extra"] = dict(record.get("extra") or {})
        with self._lock:
            self.records.append(snapshot)

    def close(self) -> None:
        pass


def _make_logger(name: str) -> LoggerManager:
    mgr = LoggerManager(manager_name=name)
    mgr.initialize()
    return mgr


def _extra_of(tap: _Tap, module: str) -> list[dict]:
    """Только наши записи: ``shutdown()`` пишет свою служебную."""
    return [r["extra"] for r in tap.records if r["module"] == module]


class TestWindowRestored:
    """Возврат по токену: то, ради чего механизм и заведён."""

    def test_nested_inner_overrides_outer_and_outer_survives_exit(self) -> None:
        """Внутренний блок перекрывает внешний, выход возвращает ВНЕШНЕЕ.

        Слом ``reset(token)`` → ``set({})`` проходит все проверки «внутри
        видно» и умирает ровно здесь: после выхода из внутреннего блока
        внешний слой оказался бы стёрт.
        """
        with contextualize(trace_id="outer", stage="a"):
            with contextualize(trace_id="inner"):
                assert log_context.get() == {"trace_id": "inner", "stage": "a"}
            assert log_context.get() == {"trace_id": "outer", "stage": "a"}, (
                "выход из внутреннего блока обязан вернуть ВНЕШНЕЕ значение целиком"
            )
        assert log_context.get() == {}

    def test_exception_inside_block_still_restores(self) -> None:
        """Исключение в теле не оставляет поле в форточке.

        Без ``finally`` след одного кадра протёк бы в записи следующего —
        причём тем вероятнее, чем хуже идут дела.
        """
        marker = RuntimeError("тело блока упало")
        try:
            with contextualize(trace_id="эфемерный"):
                raise marker
        except RuntimeError as exc:
            assert exc is marker, "contextualize не вправе подменять исключение тела"
        assert log_context.get() == {}, "после исключения форточка обязана быть пуста"

    def test_empty_call_keeps_previous_fields(self) -> None:
        """``contextualize()`` без полей — no-op, а не очистка форточки."""
        with contextualize(trace_id="держится"):
            with contextualize():
                assert log_context.get() == {"trace_id": "держится"}
            assert log_context.get() == {"trace_id": "держится"}


class TestNoSharedMutation:
    """Значение пересоздаётся целиком; чужой словарь не трогается."""

    def test_previous_window_dict_is_not_mutated(self) -> None:
        """Словарь, взятый ДО блока, внутри блока не меняется.

        Слом ``{**get(), **fields}`` → ``get().update(fields)`` даёт снаружи
        тот же результат при последовательном чтении и виден только так: по
        удержанному алиасу прежнего значения. Тот же класс, что у
        ``_context_stacks`` — мутация общего словаря видна всем потокам сразу.
        """
        token = log_context.set({"stage": "исходное"})
        try:
            before = log_context.get()
            with contextualize(trace_id="новое"):
                assert before == {"stage": "исходное"}, f"прежнее значение форточки мутировано на месте: {before}"
            assert before == {"stage": "исходное"}
        finally:
            log_context.reset(token)

    def test_neighbour_thread_does_not_see_the_field(self) -> None:
        """Поток, стартовавший ВНУТРИ блока, полей не наследует.

        Это не придирка, а рабочий случай: кадр идёт через два-три потока, и
        ставить надо в каждом. Тест закрепляет то, на что опирается
        ``frame_trace.log_correlation`` (постановка в каждом потоке отдельно —
        не дублирование).
        """
        mgr = _make_logger("CtxualizeThreads")
        tap = _Tap()
        mgr.add_tap(tap, min_level=LogLevel.DEBUG)
        try:
            with contextualize(trace_id="только-мой"):
                mgr.info("из своего потока", module="ctxualize")

                def worker() -> None:
                    mgr.info("из соседнего потока", module="ctxualize")

                t = threading.Thread(target=worker)
                t.start()
                t.join(timeout=10)
                assert not t.is_alive(), "поток завис"
        finally:
            mgr.shutdown()

        extras = _extra_of(tap, "ctxualize")
        assert len(extras) == 2, f"ожидались две записи, получено {len(extras)}"
        assert extras[0].get("trace_id") == "только-мой"
        assert "trace_id" not in extras[1], f"поле форточки протекло в соседний поток: {extras[1]}"


class TestFieldReachesRecord:
    """Сквозь настоящий менеджер: поле доезжает и исчезает вместе с блоком."""

    def test_inside_block_record_carries_field_outside_it_does_not(self) -> None:
        mgr = _make_logger("CtxualizeReach")
        tap = _Tap()
        mgr.add_tap(tap, min_level=LogLevel.DEBUG)
        try:
            with contextualize(trace_id="кадр-1"):
                mgr.info("внутри", module="ctxualize")
            mgr.info("снаружи", module="ctxualize")
        finally:
            mgr.shutdown()

        extras = _extra_of(tap, "ctxualize")
        assert len(extras) == 2, f"ожидались две записи, получено {len(extras)}"
        assert extras[0].get("trace_id") == "кадр-1"
        assert "trace_id" not in extras[1], f"поле пережило блок: {extras[1]}"

    def test_base_context_wins_over_window(self) -> None:
        """Форточка — САМЫЙ НИЗКИЙ слой: имя, занятое базой процесса, теряется.

        Свойство слоя уже стережёт ``test_context_isolation`` (постановка через
        ``log_context.set``); здесь тот же факт закрепляется через новую
        дверь — иначе «доехало» и «проиграло базе» различались бы только на
        глаз. Заодно это единственное место, где потеря названа: она молчаливая.
        """
        mgr = _make_logger("CtxualizePrecedence")
        tap = _Tap()
        mgr.add_tap(tap, min_level=LogLevel.DEBUG)
        try:
            mgr.set_base_context(proc_name="из-базы")
            with contextualize(proc_name="из-форточки", trace_id="кадр-2"):
                mgr.info("коллизия имени", module="ctxualize")
        finally:
            mgr.clear_base_context()
            mgr.shutdown()

        extras = _extra_of(tap, "ctxualize")
        assert len(extras) == 1
        assert extras[0]["proc_name"] == "из-базы", (
            "база процесса обязана перекрывать форточку — иначе proc_name можно было бы подменить снаружи"
        )
        assert extras[0]["trace_id"] == "кадр-2", "непересекающееся поле обязано доехать"
