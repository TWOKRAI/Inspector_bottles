# -*- coding: utf-8 -*-
"""Аудит смен наблюдаемости (Task 5.9).

Проверяется не «есть ли поле», а свойство: **каждая** смена оставляет след с
названным механизмом, а читающая команда следа не оставляет. Отдельно — исходы,
которые до задачи были невидимы: провал пересборки и переполнение кольца.
"""

from __future__ import annotations

import threading

import pytest

from multiprocess_framework.modules.logger_module import LoggerManager
from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
    LoggerManagerConfig,
)
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.observability_audit import (
    ACTION_CLEAR,
    ACTION_EXPIRE,
    ACTION_LAYER,
    ACTION_REBUILD,
    ACTION_RESET,
    ACTION_SET,
    ACTION_TOUCH,
    AUDIT_HISTORY,
    ObservabilityAudit,
    format_entry,
)
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    LAYER_APP,
    ObservabilityLayers,
    process_observability_layers,
)
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    apply_observability_layers,
)
from multiprocess_framework.modules.process_module.managers.observability_ttl import sweep_session_ttl


class _Clock:
    """Часы как зависимость объекта: глобальный патч доедают чужие потоки."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Heartbeat:
    def is_running(self) -> bool:
        return True


class _Svc:
    """Минимальный процесс: реальный LoggerManager + перехват строк журнала."""

    def __init__(self, tmp_path) -> None:
        self.name = "audited"
        self.logger_manager = LoggerManager(
            config=LoggerManagerConfig(app_name="audited", log_directory=str(tmp_path), enable_batching=False)
        )
        self.error_manager = None
        self.stats_manager = None
        self._heartbeat = _Heartbeat()
        self.lines: list[tuple[str, str]] = []

    def get_config(self, key, default=None):
        return default

    def _log_info(self, message, **kw):
        self.lines.append(("INFO", str(message)))

    def _log_warning(self, message, **kw):
        self.lines.append(("WARNING", str(message)))

    def _log_error(self, message, **kw):
        self.lines.append(("ERROR", str(message)))

    def _log_debug(self, message, **kw): ...

    def said(self, needle: str) -> list[tuple[str, str]]:
        return [(lvl, m) for lvl, m in self.lines if needle in m]


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    # Пересборка берёт каталог логов из машинного контекста (Task 5.12), а не из
    # живого конфига — без подмены env содержательные проверки писали бы в ./logs
    # репозитория.
    monkeypatch.setenv("INSPECTOR_LOG_DIR", str(tmp_path))
    process = _Svc(tmp_path)
    yield process
    process.logger_manager.shutdown()


@pytest.fixture()
def handlers(svc):
    class _Cm:
        def __init__(self) -> None:
            self.handlers: dict = {}

        def register_command(self, name, handler, metadata=None, tags=None):
            self.handlers[name] = handler

    svc.command_manager = _Cm()
    builtins = BuiltinCommands(svc)
    builtins._register_observability_commands()
    builtins._register_introspect_commands()
    return svc.command_manager.handlers


def _actions(layers) -> list[str]:
    return [e["action"] for e in layers.audit.entries()]


class TestEveryChangeLeavesATrace:
    """«Каждая смена видна в аудите» — по одному механизму на пару."""

    def test_command_change_names_key_value_ttl_and_mechanism(self, svc, handlers) -> None:
        handlers["observability.sink.disable"]({"sink": "messages_file", "ttl": 30})

        entries = process_observability_layers(svc).audit.entries()
        written = [e for e in entries if e["action"] == ACTION_SET]
        assert len(written) == 1, entries
        assert written[0]["key"] == "channels.messages_file.enabled"
        assert written[0]["value"] is False
        assert written[0]["ttl_sec"] == 30
        assert written[0]["origin"] == "command:observability.sink"
        assert written[0]["ok"] is True

    def test_reading_command_writes_nothing(self, svc, handlers) -> None:
        """Читающая команда, оставляющая след, делает журнал шумом о самом себе."""
        handlers["observability.sink.disable"]({"sink": "messages_file"})
        layers = process_observability_layers(svc)
        before = layers.audit.entries()

        handlers["introspect.observability"]({})
        handlers["introspect.observability"]({"audit_limit": 5})

        assert layers.audit.entries() == before

    def test_file_reload_is_visible_as_a_layer_change(self, svc, handlers, tmp_path) -> None:
        """До задачи правка файла не оставляла следа ВООБЩЕ — только она и меняла L1."""
        cfg = tmp_path / "system.yaml"
        cfg.write_text("observability:\n  log_level: WARNING\n", encoding="utf-8")

        handlers["config.reload"]({"path": str(cfg)})

        entries = process_observability_layers(svc).audit.entries()
        layer = [e for e in entries if e["action"] == ACTION_LAYER]
        assert len(layer) == 1, entries
        assert layer[0]["key"] == LAYER_APP
        assert layer[0]["keys"] == ["log_level"]
        assert layer[0]["origin"] == "command:config.reload"
        assert layer[0]["source"] == str(cfg)

    def test_switch_is_one_record_listing_what_it_took(self, svc, handlers) -> None:
        handlers["observability.sink.disable"]({"sink": "messages_file"})
        handlers["config.reload"]({"observability_session_clear": True})

        cleared = [e for e in process_observability_layers(svc).audit.entries() if e["action"] == ACTION_CLEAR]
        assert len(cleared) == 1
        assert cleared[0]["keys"] == ["channels.messages_file.enabled"]
        assert cleared[0]["origin"] == "switch:broadcast"

    def test_inline_section_is_recorded_by_its_keys(self, svc, handlers) -> None:
        """Секция мержится целиком, минуя session_set: перечисляет её `touch`."""
        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}, "ttl": 60})

        touched = [e for e in process_observability_layers(svc).audit.entries() if e["action"] == ACTION_TOUCH]
        assert len(touched) == 1
        assert touched[0]["keys"] == ["log_level"]
        assert touched[0]["ttl_sec"] == 60

    def test_manual_reset_is_recorded_even_when_it_removed_nothing(self, svc, handlers) -> None:
        """«Сбросил, а там ничего не было» и «сбросил, ключи ушли» — разные исходы."""
        handlers["config.reload"]({"observability_reset": ["log_level"]})

        reset = [e for e in process_observability_layers(svc).audit.entries() if e["action"] == ACTION_RESET]
        assert len(reset) == 1
        assert reset[0]["key"] == "log_level" and reset[0]["keys"] == []

    def test_auto_revert_is_the_same_record_reverts_reads(self, svc, handlers) -> None:
        layers = process_observability_layers(svc)
        clock = _Clock()
        layers.clock = clock
        handlers["observability.sink.disable"]({"sink": "messages_file", "ttl": 10})
        clock.advance(11)
        sweep_session_ttl(svc)

        expired = [e for e in layers.audit.entries() if e["action"] == ACTION_EXPIRE]
        assert len(expired) == 1
        assert expired[0]["origin"] == "ttl-sweeper"
        # Кольца session_reverts больше нет — это выборка из ТОГО ЖЕ кольца.
        assert list(layers.session_reverts) == expired


class TestFailureIsVisible:
    """Провал пересборки — задокументированный на проекте класс «проглоченный сбой»."""

    def test_failed_rebuild_is_recorded_with_its_reason(self, svc) -> None:
        layers = ObservabilityLayers()

        class _Broken:
            config = object()

            def reconfigure(self, _payload):
                raise RuntimeError("канал не поднялся")

        with pytest.raises(RuntimeError):
            apply_observability_layers(layers, logger=_Broken(), origin="test:broken")

        failed = [e for e in layers.audit.entries() if e["action"] == ACTION_REBUILD]
        assert len(failed) == 1
        assert failed[0]["ok"] is False
        assert "канал не поднялся" in failed[0]["error"]

    def test_successful_rebuild_says_ok_explicitly(self, svc, handlers) -> None:
        """«Удалось» не опознаётся по ОТСУТСТВИЮ ключа: читатель отказов не должен гадать."""
        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}})

        rebuilt = [e for e in process_observability_layers(svc).audit.entries() if e["action"] == ACTION_REBUILD]
        assert rebuilt and all(e["ok"] is True for e in rebuilt)
        assert rebuilt[-1]["log_level"] == "DEBUG"

    def test_journal_failure_is_named_in_the_entry_not_swallowed(self) -> None:
        """Сбой журнала не роняет смену — но и не исчезает бесследно."""

        def _boom(_message, _failed):
            raise OSError("диск кончился")

        audit = ObservabilityAudit(log=_boom)
        entry = audit.record(ACTION_SET, origin="test", key="log_level", value="DEBUG")

        assert entry["key"] == "log_level", "смена обязана состояться"
        assert "диск кончился" in entry["log_failed"]
        assert audit.entries()[-1]["log_failed"] == entry["log_failed"]


class TestTheRingIsHonestAboutItsLimits:
    def test_overflow_is_counted_not_silent(self) -> None:
        """«Аудит полон» и «смен не было» обязаны различаться."""
        audit = ObservabilityAudit()
        for i in range(AUDIT_HISTORY + 7):
            audit.record(ACTION_SET, origin="test", key=f"k{i}", value=i)

        assert len(audit.entries()) == AUDIT_HISTORY
        assert audit.dropped() == 7
        assert audit.view()["seq"] == AUDIT_HISTORY + 7

    def test_limit_zero_returns_nothing_not_everything(self) -> None:
        """Срез items[-0:] == items[0:] — классическая ловушка, зеркалим backend_ctl."""
        audit = ObservabilityAudit()
        audit.record(ACTION_SET, origin="test", key="a", value=1)

        assert audit.entries(0) == []
        assert audit.entries(-3) == []
        assert len(audit.entries(1)) == 1

    def test_explicit_none_value_differs_from_no_value(self) -> None:
        """У троттла None — маркер снятия правила, а не «значения не было»."""
        audit = ObservabilityAudit()
        audit.record(ACTION_SET, origin="test", key="telemetry.throttle", value=None)
        audit.record(ACTION_CLEAR, origin="test", keys=())

        assert audit.entries()[0]["value"] is None
        assert "value" not in audit.entries()[1]

    def test_large_value_is_truncated_with_a_marker(self) -> None:
        """Аудит не имеет права стать вторым местом хранения конфига."""
        audit = ObservabilityAudit()
        audit.record(ACTION_SET, origin="test", key="scopes", value={"x": "y" * 5000})

        stored = audit.entries()[0]["value"]
        assert stored["_truncated"] is True and stored["size"] > 5000


class TestOriginCannotBeForgotten:
    """Полнота держится сигнатурой, а не памятью автора."""

    @pytest.mark.parametrize(
        "call",
        [
            lambda ly: ly.session_set("log_level", "DEBUG"),
            lambda ly: ly.session_touch(["log_level"]),
            lambda ly: ly.session_reset("log_level"),
            lambda ly: ly.session_reset_keys("log_level"),
            lambda ly: ly.session_clear(),
            lambda ly: ly.replace_layer(LAYER_APP, {}),
        ],
    )
    def test_mutating_without_origin_is_a_loud_typeerror(self, call) -> None:
        layers = ObservabilityLayers()
        with pytest.raises(TypeError, match="origin"):
            call(layers)

    def test_rebuild_without_origin_is_a_loud_typeerror(self) -> None:
        with pytest.raises(TypeError, match="origin"):
            apply_observability_layers(ObservabilityLayers())


class TestMechanismHazards:
    """Опасности, видимые только автору механизма."""

    def test_seq_and_ring_stay_paired_under_concurrent_writers(self) -> None:
        """Инкремент seq и append — одна атомарная пара, иначе дубли номеров."""
        audit = ObservabilityAudit()
        barrier = threading.Barrier(4)

        def _writer(tag: int) -> None:
            barrier.wait()
            for i in range(50):
                audit.record(ACTION_SET, origin=f"t{tag}", key=f"k{tag}.{i}", value=i)

        threads = [threading.Thread(target=_writer, args=(t,), daemon=True) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert not any(t.is_alive() for t in threads), "запись в аудит подвисла"

        assert audit.view()["seq"] == 200
        numbers = [e["seq"] for e in audit.entries()]
        assert len(set(numbers)) == len(numbers), "дубли номеров: seq и append разъехались"
        assert numbers == sorted(numbers), "порядок кольца разошёлся с порядком номеров"

    def test_record_does_not_hold_the_layer_lock_while_writing_the_journal(self) -> None:
        """Журнал пишется ВНЕ лока стека: иначе файловое I/O держит всех писателей.

        Шов — внутри колбэка журнала: если лок стека всё ещё занят, соседний
        поток не сможет его взять за отведённое время.
        """
        layers = ObservabilityLayers()
        seen: list[bool] = []

        def _log(_message, _failed):
            other = threading.Thread(target=lambda: seen.append(layers.lock.acquire(timeout=2.0)), daemon=True)
            other.start()
            other.join(timeout=5)

        layers.audit.log = _log
        layers.session_set("log_level", "DEBUG", origin="test")

        assert seen == [True], "лок стека удерживался на время записи в журнал"

    def test_audit_survives_pickle_without_its_lock_or_callback(self) -> None:
        """Стек едет в снимок процесса; непиклимое — лок и колбэк журнала."""
        # pickle здесь не десериализация чужих данных, а воспроизведение того,
        # что делает сам фреймворк: стек слоёв едет в снимке процесса. Вход —
        # объект, созданный строкой выше, в этом же процессе.
        import pickle

        layers = ObservabilityLayers()
        layers.audit.log = lambda message, failed: None
        layers.session_set("log_level", "DEBUG", origin="test")

        restored = pickle.loads(pickle.dumps(layers))

        assert [e["key"] for e in restored.audit.entries()] == ["log_level"]
        assert restored.audit.log is None, "колбэк журнала чужого процесса воскрес бы мёртвым"
        restored.session_set("log_level", "INFO", origin="test")
        assert restored.audit.view()["seq"] == 2


class TestFoundByTheReview:
    """Четыре дефекта, которых не увидели ни тесты, ни живой прогон (ревью 5.9)."""

    def test_reload_carrying_telemetry_is_not_signed_by_another_command(self, svc, handlers) -> None:
        """Замечание 1: обработчик секции телеметрии зовут ДВОЕ, имя было зашито.

        Оператор, применивший файл через `config.reload`, видел в журнале
        `command:telemetry.reconfigure` — команду, которую никто не вызывал.
        """
        handlers["config.reload"]({"telemetry": {"publish": {"metrics": {"fps": True}}}, "ttl": 60})

        origins = {e["origin"] for e in process_observability_layers(svc).audit.entries()}
        assert origins == {"command:config.reload"}, origins

    def test_replace_names_the_keys_it_took_away(self, svc, handlers) -> None:
        """Замечание 2: `replace` снимал ручку оператора БЕЗ следа.

        Пара: до фикса запись перечисляла только новые ключи, и снятый `latency`
        не встречался в аудите нигде.
        """
        handlers["telemetry.reconfigure"]({"publish": {"metrics": {"latency": True}}, "ttl": 600})
        handlers["telemetry.reconfigure"]({"publish": {"metrics": {"fps": True}}, "mode": "replace"})

        layers = process_observability_layers(svc)
        assert layers.session_keys() == ("telemetry.publish.metrics.fps",)
        touches = [e for e in layers.audit.entries() if e["action"] == ACTION_TOUCH]
        assert touches[-1]["removed"] == ["telemetry.publish.metrics.latency"]

    def test_rebuild_record_cannot_claim_a_key_it_did_not_apply(self, svc) -> None:
        """Замечание 3: содержимое записи считалось ПОСЛЕ снятия лока.

        Шов — писатель, выигрывающий гонку ровно в окне между `release` лока и
        сбором `keys`. До фикса его ключ попадал в запись пересборки, которая
        его не применяла.
        """
        layers = ObservabilityLayers()

        class _RacingLock:
            """Прокси лока: отпустив его ПОЛНОСТЬЮ, пускает чужого писателя вперёд нас.

            Глубину считаем сами. Первая редакция шва этого не делала и стреляла
            на первом же ВЛОЖЕННОМ выходе — лок оставался занят внешним `with`,
            писатель блокировался, `join` истекал по таймауту, и тест зеленел
            при любой реализации. Найдено слом-инъекцией: тест пережил свой слом
            и потому не существовал.
            """

            def __init__(self, real, stack) -> None:
                self._real, self._stack = real, stack
                self._depth, self._armed = 0, True
                self.fired = False

            def __enter__(self):
                self._depth += 1
                return self._real.__enter__()

            def __exit__(self, *exc):
                out = self._real.__exit__(*exc)
                self._depth -= 1
                if self._depth == 0 and self._armed:
                    self._armed = False
                    writer = threading.Thread(
                        target=lambda: self._stack.session_set("smuggled.key", 1, ttl=0, origin="race"),
                        daemon=True,
                    )
                    writer.start()
                    writer.join(timeout=5)
                    self.fired = not writer.is_alive()
                return out

            def __getattr__(self, name):
                return getattr(self._real, name)

        seam = _RacingLock(layers._lock, layers)
        object.__setattr__(layers, "_lock", seam)
        apply_observability_layers(layers, origin="test:race")

        assert seam.fired, "шов не сработал: чужой писатель не успел вклиниться в окно"
        assert "smuggled.key" in layers.session_keys(), "правка гонщика вообще не легла"
        rebuilt = [e for e in layers.audit.entries() if e["action"] == ACTION_REBUILD]
        assert rebuilt, layers.audit.entries()
        assert "smuggled.key" not in rebuilt[-1]["keys"], "запись приписала себе чужую правку"

    def test_sweeper_tick_writes_one_record_not_two(self, svc, handlers) -> None:
        """Замечание 4: две записи на такт выедали кольцо вдвое быстрее.

        На залипшем отказе такт повторяется каждые ~5с — и вытесняет ровно то,
        что нужно в инциденте: «кто поставил ключ».
        """
        layers = process_observability_layers(svc)
        clock = _Clock()
        layers.clock = clock
        handlers["observability.sink.disable"]({"sink": "messages_file", "ttl": 10})
        before = layers.audit.view()["seq"]

        clock.advance(11)
        sweep_session_ttl(svc)

        added = [e for e in layers.audit.entries() if e["seq"] > before]
        assert [e["action"] for e in added] == [ACTION_EXPIRE], added
        assert added[0]["ok"] is True and added[0]["log_level"] is not None


class TestTheJournalLine:
    def test_change_leaves_one_readable_line_in_the_process_journal(self, svc, handlers) -> None:
        """Долговечность даёт журнал процесса, а не своё кольцо: оно умрёт с процессом."""
        handlers["observability.sink.disable"]({"sink": "messages_file", "ttl": 30})

        said = svc.said("[observability-audit] set")
        assert said, svc.lines
        level, message = said[0]
        assert level == "INFO"
        assert "channels.messages_file.enabled" in message and "ttl=30" in message

    def test_failed_change_is_a_warning_not_an_info(self) -> None:
        entry = {"action": ACTION_REBUILD, "origin": "test", "ok": False, "error": "RuntimeError('нет')"}
        assert "НЕ УДАЛОСЬ" in format_entry(entry)

    def test_actions_recorded_by_a_full_reload_cycle(self, svc, handlers, tmp_path) -> None:
        """Страж последовательности: смена → пересборка, обе записи и в этом порядке."""
        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}})

        assert _actions(process_observability_layers(svc)) == [ACTION_TOUCH, ACTION_REBUILD]


class TestStuckFailureDoesNotEatTheRing:
    """A-A6-1 (корзина 2 п.5): залипший отказ пересборки прятал истину.

    Подметальщик повторяет попытку каждый такт (~5 с), и каждая писала свою
    запись: кольцо на 100 выедалось за ~8.3 минуты. `session_reverts` и
    `ttl_report` — выборки из ТОГО ЖЕ кольца, поэтому в инциденте становились
    невидимы и авто-возвраты, и авторство ключей: следствие вытесняло причину.

    Схлопывание — только ПОДРЯД идущих одинаковых записей: между ними ничего не
    произошло, значит это одно длящееся условие, а не история. Разбавь их чужой
    записью — и схлопывание обязано прекратиться, иначе оно переставит историю.
    """

    def _fail(self, audit: ObservabilityAudit) -> None:
        audit.record(ACTION_EXPIRE, origin="ttl-sweeper", keys=[], ok=False, error="boom", reason="retry")

    def test_repeats_collapse_into_one_entry_with_a_counter(self) -> None:
        audit = ObservabilityAudit()
        for _ in range(100):
            self._fail(audit)
        assert len(audit.entries()) == 1, "повторы одного условия не схлопнулись"
        assert audit.entries()[0]["repeats"] == 100

    def test_the_real_revert_survives_a_hundred_retries(self) -> None:
        """Ровно репро ревьюера: настоящий возврат обязан остаться видимым."""
        audit = ObservabilityAudit()
        audit.record(ACTION_EXPIRE, origin="ttl-sweeper", keys=["log_level"], ok=True, reason="ttl")
        for _ in range(100):
            self._fail(audit)
        visible = [e for e in audit.entries(action=ACTION_EXPIRE) if e.get("ok")]
        assert len(visible) == 1, f"настоящий возврат вытеснен отказами: {audit.entries()}"

    def test_authorship_of_keys_survives_too(self) -> None:
        """Записи ДРУГОГО вида (кто менял ключи) кольцо тоже обязано сохранить."""
        audit = ObservabilityAudit()
        audit.record(ACTION_SET, origin="command:config.reload", key="log_level", value="DEBUG")
        for _ in range(100):
            self._fail(audit)
        assert len(audit.entries(action=ACTION_SET)) == 1

    def test_nothing_was_dropped_so_the_counter_says_so(self) -> None:
        """`dropped()` = seq − len(ring): схлопывание не имеет права врать о вытеснении.

        Считай схлопнутый повтор новым `seq` — и `dropped()` отрапортовал бы
        сотню вытесненных записей, которых не было.
        """
        audit = ObservabilityAudit()
        for _ in range(100):
            self._fail(audit)
        assert audit.dropped() == 0
        # Проверяется именно `seq`, а не только `dropped()`: на ровно сотне
        # записей кольцо ещё не переполнено, и `dropped()` отдал бы ноль и без
        # схлопывания — тест был бы зелёным ни от чего.
        assert audit.seq == 1, "схлопнутый повтор посчитан новой записью кольца"

    def test_an_interleaved_entry_stops_the_collapse(self) -> None:
        """Не подряд — не одно условие: между повторами что-то произошло."""
        audit = ObservabilityAudit()
        self._fail(audit)
        audit.record(ACTION_SET, origin="op", key="log_level", value="DEBUG")
        self._fail(audit)
        assert len(audit.entries(action=ACTION_EXPIRE)) == 2

    def test_a_different_error_is_a_different_condition(self) -> None:
        """Сменился текст отказа — сменилось условие, слипаться им нельзя."""
        audit = ObservabilityAudit()
        self._fail(audit)
        audit.record(ACTION_EXPIRE, origin="ttl-sweeper", keys=[], ok=False, error="другое", reason="retry")
        assert len(audit.entries()) == 2

    def test_same_key_with_a_different_value_is_not_a_repeat(self) -> None:
        """Контроль на пере-схлопывание: две РАЗНЫЕ правки одного ключа — две записи.

        Слипнись они — аудит потерял бы вторую правку, и оператор читал бы в
        истории значение, которого больше нет. Это было бы хуже исходного дефекта.
        """
        audit = ObservabilityAudit()
        audit.record(ACTION_SET, origin="op", key="log_level", value="DEBUG")
        audit.record(ACTION_SET, origin="op", key="log_level", value="ERROR")
        assert len(audit.entries()) == 2
        assert [e["value"] for e in audit.entries()] == ["DEBUG", "ERROR"]

    def test_first_occurrence_detail_is_kept_and_last_seen_is_recorded(self) -> None:
        """Держим ПЕРВОЕ вхождение (когда началось) + отметку последнего.

        Для длящегося отказа информативно именно начало; «когда видели в
        последний раз» несёт `last_ts`.
        """
        ticks = iter([10.0, 11.0, 12.0])
        audit = ObservabilityAudit(clock=lambda: next(ticks))
        self._fail(audit)
        self._fail(audit)
        self._fail(audit)
        entry = audit.entries()[0]
        assert entry["ts"] == 10.0
        assert entry["last_ts"] == 12.0
        assert entry["repeats"] == 3
