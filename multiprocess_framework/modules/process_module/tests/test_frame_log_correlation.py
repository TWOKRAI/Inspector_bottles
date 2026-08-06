# -*- coding: utf-8 -*-
"""Ф3.3 — след кадра доходит до записей лога, не трогая call-site'ы.

``trace_id`` уже существовал (Ф7 G.6): ``uuid4().hex`` рождается у источника и
едет в ``item["trace_id"]``. Не хватало другого — чтобы его несли ЗАПИСИ, а не
два места, где его передали руками. Механизм для этого тоже уже был:
``log_context`` — публичная форточка контекста логгера, попадающая в ``extra``
на обоих путях эмиссии.

Опасности, которые проверяются здесь (их видно автору правки, не постановке):

1. **Граница потока.** ``ContextVar`` её не пересекает, а кадр в процессе идёт
   через приём и обработку — РАЗНЫЕ потоки. Одна точка постановки выглядела бы
   как сквозная корреляция, а накрывала бы записи одного потока.
2. **Протечка между кадрами.** Невозврат форточки означает, что следующий кадр
   (или холостой такт) унесёт чужой след — корреляция, указывающая не туда,
   врёт увереннее, чем её отсутствие.
3. **Смешанная пачка.** У неё одного следа нет; приписывать чей-то — та же ложь.
4. **Исключение внутри такта** обязано возвращать форточку так же, как успех.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.logger_module.core.logger_core import log_context
from multiprocess_framework.modules.process_module.generic import frame_trace


@pytest.fixture(autouse=True)
def _clean_window():
    """Форточка обязана стартовать и заканчиваться пустой в каждом тесте."""
    token = log_context.set({})
    try:
        yield
    finally:
        log_context.reset(token)


class TestWindowCarriesTheFrameTrace:
    def test_trace_id_visible_inside_and_gone_after(self) -> None:
        item = {"trace_id": "a" * 32, "seq_id": 7}
        with frame_trace.log_correlation(item):
            assert log_context.get()["trace_id"] == "a" * 32
        assert "trace_id" not in log_context.get(), "след кадра остался в форточке после такта"

    def test_existing_window_keys_survive(self) -> None:
        """Форточка общая: корреляция добавляет ключ, а не подменяет содержимое."""
        log_context.set({"recipe": "webcam_sketch"})
        with frame_trace.log_correlation({"trace_id": "b" * 32}):
            assert log_context.get() == {"recipe": "webcam_sketch", "trace_id": "b" * 32}
        assert log_context.get() == {"recipe": "webcam_sketch"}

    def test_exception_still_restores_the_window(self) -> None:
        with pytest.raises(RuntimeError):
            with frame_trace.log_correlation({"trace_id": "c" * 32}):
                raise RuntimeError("плагин упал")
        assert "trace_id" not in log_context.get(), "исключение унесло форточку с чужим следом"

    def test_nesting_restores_the_outer_trace_not_the_empty_one(self) -> None:
        """Вложенность: возврат по токену, а не «стереть ключ».

        Стирание ключа вместо токена выглядит эквивалентно ровно до первой
        вложенной постановки — и там наружный след пропал бы молча.
        """
        with frame_trace.log_correlation({"trace_id": "d" * 32}):
            with frame_trace.log_correlation({"trace_id": "e" * 32}):
                assert log_context.get()["trace_id"] == "e" * 32
            assert log_context.get()["trace_id"] == "d" * 32, "вложенный такт потерял наружный след"


class TestAmbiguousInputIsNoOp:
    @pytest.mark.parametrize(
        "items",
        [
            pytest.param([], id="пустая пачка"),
            pytest.param(None, id="ничего"),
            pytest.param({"seq_id": 1}, id="кадр без trace_id"),
            pytest.param([{"trace_id": "f" * 32}, {"trace_id": "0" * 32}], id="смешанная пачка"),
            pytest.param(["не словарь"], id="мусор"),
        ],
    )
    def test_window_is_not_touched(self, items: Any) -> None:
        log_context.set({"recipe": "r"})
        with frame_trace.log_correlation(items):
            assert log_context.get() == {"recipe": "r"}, f"форточку тронули на входе {items!r}"

    def test_homogeneous_batch_is_correlated(self) -> None:
        """Пара к смешанной: одинаковый след у всей пачки — законный случай fan-in."""
        same = [{"trace_id": "9" * 32}, {"trace_id": "9" * 32}]
        with frame_trace.log_correlation(same):
            assert log_context.get()["trace_id"] == "9" * 32


class TestThreadBoundary:
    """Почему точек постановки три, а не одна."""

    def test_context_does_not_cross_into_another_thread(self) -> None:
        """Соседний поток НЕ видит след — это и есть причина ставить его в каждом.

        Тест закрепляет свойство платформы, на котором держится решение. Если
        оно однажды станет неверным (контекст начнут копировать в потоки),
        три точки постановки превратятся в дублирование, и знать об этом надо
        отсюда, а не из расследования.
        """
        seen: List[Any] = []
        done = threading.Event()

        def worker() -> None:
            seen.append(log_context.get().get("trace_id"))
            done.set()

        with frame_trace.log_correlation({"trace_id": "7" * 32}):
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            assert done.wait(timeout=5.0), "поток-наблюдатель не отработал за 5с"
        thread.join(timeout=5.0)

        assert seen == [None], f"контекст пересёк границу потока: {seen}"


class TestWiringOfTheThreePoints:
    """Проводка, а не помощник.

    Тесты выше доказывают контекст-менеджер. Если бы дело кончилось ими, они
    доказывали бы сам харнес: помощник корректен, а вызвать его в проде забыли.
    Здесь гоняются настоящие ``PipelineExecutor`` и ``DataReceiver``, а «логом»
    служит проба, читающая форточку в момент работы плагина.
    """

    @staticmethod
    def _drive_pipeline(batches: List[List[Dict[str, Any]]]) -> List[Any]:
        """Прогнать батчи через НАСТОЯЩИЙ ``run_loop`` и вернуть увиденные следы.

        Через ``run_loop``, а не ``_run_batch``: корреляция стоит в цикле, и
        вызов внутреннего метода напрямую проверял бы что угодно, только не
        проводку. (Первая редакция теста делала именно так и была зелёной по
        неверной причине — точнее, красной: она и поймала подмену предмета.)
        """
        import queue as _queue

        from multiprocess_framework.modules.process_module.generic.pipeline_executor import (
            PipelineExecutor,
        )

        seen: List[Any] = []
        stop = threading.Event()
        chain_queue: Any = _queue.Queue()
        for batch in batches:
            chain_queue.put(batch)

        class _ProbePlugin:
            name = "probe"

            def process(self, item: Dict[str, Any]) -> Dict[str, Any]:
                # Ровно то, что сделал бы любой лог плагина: читает контекст,
                # ничего не зная про trace_id.
                seen.append(log_context.get().get("trace_id"))
                if len(seen) >= len(batches):
                    stop.set()
                return item

        executor = PipelineExecutor(
            plugins=[_ProbePlugin()],
            chain_targets=["out"],
            shm_middleware=None,
            send_fn=lambda target, msg: None,
        )
        worker = threading.Thread(target=executor.run_loop, args=(chain_queue, stop, threading.Event()), daemon=True)
        worker.start()
        worker.join(timeout=5.0)
        assert not worker.is_alive(), "run_loop не завершился за 5с"
        return seen

    def test_pipeline_batch_records_carry_the_frame_trace(self) -> None:
        seen = self._drive_pipeline([[{"trace_id": "1" * 32, "val": 1}]])
        assert seen == ["1" * 32], "запись плагина не несёт след кадра — такт не накрыт корреляцией"

    def test_pipeline_does_not_leak_the_trace_into_the_next_batch(self) -> None:
        """Пара к предыдущему: следующий такт без следа не наследует прошлый."""
        seen = self._drive_pipeline([[{"trace_id": "2" * 32}], [{"no_trace": True}]])
        assert seen == ["2" * 32, None], f"след протёк в следующий такт: {seen}"

    def test_source_records_carry_the_freshly_born_trace(self) -> None:
        """Третья точка: рождение кадра. След назначается тут же и обязан накрыть отправку.

        ``send_fn`` играет роль любого кода, который на отправке пишет лог
        (например, отказ роутера): он читает форточку, ничего не зная про кадр.
        """
        from multiprocess_framework.modules.process_module.generic.source_producer import (
            SourceProducer,
        )

        seen: List[Any] = []
        stop = threading.Event()

        class _Source:
            name = "probe_source"

            def start(self, ctx: Any = None) -> None: ...

            def produce(self) -> List[Dict[str, Any]]:
                return [{"frame": "f", "seq_id": len(seen)}]

        def _send(_target: str, _msg: Dict[str, Any]) -> None:
            seen.append(log_context.get().get("trace_id"))
            stop.set()

        producer = SourceProducer(
            plugin=_Source(),
            shm_middleware=None,
            send_fn=_send,
            chain_targets=["out"],
            target_fps=100.0,
        )
        worker = threading.Thread(target=producer.run_loop, args=(stop, threading.Event()), daemon=True)
        worker.start()
        worker.join(timeout=5.0)
        assert not worker.is_alive(), "run_loop источника не завершился за 5с"

        assert seen and seen[0], "отправка кадра идёт без следа — корреляция у источника не поставлена"
        assert len(seen[0]) == 32, f"след не похож на trace_id W3C: {seen[0]!r}"

    def test_receiver_records_carry_the_frame_trace(self) -> None:
        import queue as _queue

        from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver

        seen: List[Any] = []
        stop = threading.Event()

        class _Inspector:
            def on_item(self, item: Dict[str, Any]) -> None:
                seen.append(log_context.get().get("trace_id"))
                stop.set()  # одного кадра достаточно — выходим из цикла приёма

        pending = [{"data": {"trace_id": "3" * 32, "seq_id": 1}}]

        def _receive(*_a: Any, **_kw: Any) -> Any:
            if pending:
                return pending.pop()
            stop.set()
            return None

        receiver = DataReceiver(
            receive_fn=_receive,
            shm_middleware=None,
            inspector_manager=_Inspector(),
            chain_queue=_queue.Queue(),
            node_name="probe",
        )
        receiver.run_loop(stop, threading.Event())

        assert seen == ["3" * 32], "запись приёмника не несёт след кадра"


class TestRecordsActuallyCarryIt:
    """Сквозная пара: не «форточка выставлена», а «запись несёт»."""

    def test_emitted_record_carries_trace_id_without_touching_the_call_site(self, tmp_path) -> None:
        from multiprocess_framework.modules.logger_module.core.log_config import LogLevel, LogScope
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        class _Sink:
            name = "collect"

            def __init__(self) -> None:
                self.records: List[Dict[str, Any]] = []

            def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
                self.records.append(data)
                return {"status": "success"}

            def close(self) -> None: ...

        logger = LoggerManager(
            manager_name="TraceProbe",
            config={
                "app_name": "trace",
                "log_directory": str(tmp_path),
                "enable_batching": False,
                "modules": {},
                "channels": {"f": {"type": "file", "enabled": True, "file_path": str(tmp_path / "a.log")}},
                "default_level": "DEBUG",
                "scopes": {"SYSTEM": {"channels": ["f"]}},
            },
        )
        logger.initialize()
        try:
            sink = _Sink()
            logger.add_tap(sink, min_level="DEBUG", name="collect")

            with frame_trace.log_correlation({"trace_id": "5" * 32}):
                # Call-site НИЧЕГО не знает про trace_id — в этом весь смысл.
                logger.log(LogScope.SYSTEM, LogLevel.INFO, "обработка кадра", module="plugin")
            logger.log(LogScope.SYSTEM, LogLevel.INFO, "вне кадра", module="plugin")

            inside, outside = sink.records[0], sink.records[1]
            assert inside["extra"].get("trace_id") == "5" * 32, "запись кадра без следа"
            assert "trace_id" not in outside["extra"], "запись вне кадра получила чужой след"
        finally:
            logger.shutdown()
