# -*- coding: utf-8 -*-
"""Task 5.8 — срок жизни рантайм-правки наблюдаемости (L3) и авто-возврат.

Резидуал R1 задачи 5.12, названный в плане: до слоёв «включил DEBUG и забыл»
стиралось любым ``config.reload``; после 5.12 ручка переживает reload, а через
``observability.persist`` становится вечной — то есть инцидент «messages.log
645 МБ за прогон» стал вероятнее. Здесь L3 делается временным по построению.

Гоняем РЕАЛЬНЫЙ ``LoggerManager``, реальные обработчики команд и (в одном тесте)
реальный цикл ``ProcessHeartbeat`` — проверка на фейках доказала бы фейки.
Часы — зависимость объекта (``layers.clock``), глобальный ``time.monotonic``
не патчится ни разу: такой патч на этом проекте уже давал StopIteration в
невиновном тесте.
"""

from __future__ import annotations

import pickle
import sys
import threading
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.logger_module.configs import LoggerManagerConfig
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.observability_audit import (
    ACTION_EXPIRE,
    ACTION_SET,
)
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    ObservabilityLayers,
    process_observability_layers,
)
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.managers.observability_ttl import (
    sweep_session_ttl,
    ttl_enforced,
)


class _Clock:
    """Монотонные часы под управлением теста."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Cm:
    def __init__(self) -> None:
        self.handlers: Dict[str, Any] = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler


class _Wm:
    """Минимальный worker_manager: ``start()`` heartbeat'а требует его наличия."""

    def __init__(self) -> None:
        self.created: List[str] = []

    def create_worker(self, name, target, config=None, auto_start=True) -> None:
        self.created.append(name)


class _Svc:
    """Процесс: живой LoggerManager, слои и (опционально) heartbeat."""

    def __init__(self, logger: LoggerManager, config: Dict[str, Any] | None = None) -> None:
        self.command_manager = _Cm()
        self.name = "seg"
        self.logger_manager = logger
        self.error_manager = None
        self.stats_manager = None
        self.worker_manager = None
        self.router_manager = None
        self._state_proxy = None
        self._heartbeat = None
        self._config = dict(config or {})
        self.log_calls: List[tuple] = []
        self.sent: List[tuple] = []

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def send_message(self, target, message) -> None:
        self.sent.append((target, message))

    def _log_debug(self, msg, **kw):
        self.log_calls.append(("DEBUG", msg, kw))

    def _log_info(self, msg, **kw):
        self.log_calls.append(("INFO", msg, kw))

    def _log_warning(self, msg, **kw):
        self.log_calls.append(("WARNING", msg, kw))

    def _log_error(self, msg, **kw):
        self.log_calls.append(("ERROR", msg, kw))

    # ProcessHeartbeat зовёт публичные имена
    log_info = _log_info
    log_debug = _log_debug

    def messages(self, level: str) -> List[str]:
        return [msg for lvl, msg, _ in self.log_calls if lvl == level]


@pytest.fixture
def wired(tmp_path):
    """Живой логгер на дефолтных каналах + команды + управляемые часы слоёв."""
    logger = LoggerManager(
        config=LoggerManagerConfig(
            app_name="ttl_layer",
            log_directory=str(tmp_path),
            enable_batching=False,
        )
    )
    svc = _Svc(logger)
    bc = BuiltinCommands(svc)
    bc._register_observability_commands()
    bc._register_introspect_commands()
    clock = _Clock()
    process_observability_layers(svc).clock = clock
    try:
        yield svc, svc.command_manager.handlers, clock
    finally:
        logger.shutdown()


class _SweeperSeam:
    """Запустить подметальщика ИЗ ДРУГОГО ПОТОКА в середине критического блока.

    Лок стека реентерабелен: вызов из того же потока прошёл бы сквозь него и
    доказал бы не лок, а его отсутствие. Поток даёт настоящий интерливинг —
    под локом он паркуется до конца блока (``join`` истекает по дедлайну, и это
    норма), без лока успевает отработать целиком.
    """

    def __init__(self, svc: Any, grace: float = 0.5) -> None:
        self._svc = svc
        self._grace = grace
        self._thread: threading.Thread | None = None
        self.started = False
        self.report: Any = None

    def trigger(self) -> None:
        """Пустить подметальщика один раз и дать ему шанс отработать."""
        if self.started:
            return
        self.started = True
        self._thread = threading.Thread(target=self._sweep, daemon=True)
        self._thread.start()
        # Дедлайн, а не бесконечное ожидание: тест, который ВИСНЕТ вместо
        # падения, прячет регресс за таймаутом. Под локом дедлайн истекает —
        # это норма, поток доработает после критического блока.
        self._thread.join(timeout=self._grace)

    def wrap(self, inner):
        def _seam(*args, **kwargs):
            self.trigger()
            return inner(*args, **kwargs)

        return _seam

    def _sweep(self) -> None:
        self.report = sweep_session_ttl(self._svc)

    def finish(self) -> None:
        if self._thread is not None:
            self._thread.join(timeout=5)
            assert not self._thread.is_alive(), "подметальщик не отпустил лок после критического блока"


class _SeamSection(dict):
    """Секция, обход которой в ``deep_merge`` пускает подметальщика в зазор.

    ``deep_merge`` копирует базу и только потом идёт по ``overlay.items()`` —
    значит вызов отсюда приходится строго между чтением ``layers.session`` и
    присваиванием результата, то есть в то самое окно блокера.
    """

    def __init__(self, seam: "_SweeperSeam", **payload: Any) -> None:
        super().__init__(**payload)
        self._seam = seam

    def items(self):  # noqa: D102 — поведение описано в docstring класса
        self._seam.trigger()
        return super().items()


def _active(svc) -> list:
    from multiprocess_framework.modules.process_module.managers.observability_reload import (
        observability_effective,
    )

    return observability_effective(logger=svc.logger_manager)["logger"]["channels_active"]


def _level(svc) -> str:
    return svc.logger_manager.config.default_level


class TestDeadlineIsReal:
    """Ключ живёт ровно до срока и снимается ПРИМЕНЁННО, а не только в словаре."""

    def test_handle_survives_until_the_deadline_and_not_a_tick_longer(self, wired) -> None:
        """Главная пара задачи: до срока держится, после — вернулось само."""
        svc, handlers, clock = wired
        handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 60})
        assert "messages_file" not in _active(svc)

        clock.advance(59)
        assert sweep_session_ttl(svc) is None, "возврат наступил раньше срока"
        assert "messages_file" not in _active(svc)

        clock.advance(2)
        report = sweep_session_ttl(svc)
        assert report is not None and report["keys"] == ["channels.messages_file.enabled"]
        # Применено к ЖИВОМУ менеджеру, а не только к слою: приёмник в реестре.
        assert "messages_file" in _active(svc), "срок вышел, а приёмник не вернулся"
        assert process_observability_layers(svc).session_keys() == ()
        # Отметка «снят оператором» тоже снята — иначе маршрут продолжал бы его вычитать.
        assert svc.logger_manager._sinks_disabled_by_operator == set()

    def test_expired_level_falls_back_to_the_layer_below(self, wired) -> None:
        """Возврат = наследование снизу, а не присвоение запомненного значения."""
        svc, handlers, clock = wired
        layers = process_observability_layers(svc)
        layers.app = {"log_level": "WARNING"}

        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}, "ttl": 30})
        assert _level(svc) == "DEBUG"

        clock.advance(31)
        sweep_session_ttl(svc)
        assert _level(svc) == "WARNING", "вернулись не к слою L1, а куда-то ещё"

    def test_write_without_ttl_still_gets_a_deadline(self, wired) -> None:
        """Оператор, забывший про DEBUG, забыл бы и про ttl — срок по умолчанию."""
        svc, handlers, clock = wired
        res = handlers["logger.sink.disable"]({"sink": "messages_file"})
        assert res["ttl_sec"] == 300.0, "правка без ttl оказалась бессрочной"

        clock.advance(301)
        assert sweep_session_ttl(svc) is not None
        assert "messages_file" in _active(svc)

    def test_ttl_zero_is_forever_and_is_declared(self, wired) -> None:
        """Вечность — решение, а не умолчание: она названа в ответе."""
        svc, handlers, clock = wired
        res = handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 0})
        assert res["ttl_sec"] is None and res["expires_in_sec"] is None

        clock.advance(100000)
        assert sweep_session_ttl(svc) is None
        assert "messages_file" not in _active(svc)

    def test_rewrite_restarts_the_deadline(self, wired) -> None:
        """Повторная правка не наследует дедлайн прошлой — иначе вернётся раньше просимого."""
        svc, handlers, clock = wired
        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}, "ttl": 60})
        clock.advance(50)
        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}, "ttl": 60})

        clock.advance(20)  # 70с от ПЕРВОЙ правки, 20с от второй
        assert sweep_session_ttl(svc) is None, "срок унаследован от прошлой записи"
        clock.advance(45)
        assert sweep_session_ttl(svc) is not None

    def test_repeat_without_ttl_does_not_extend_but_says_so(self, wired) -> None:
        """Повтор по инерции не двигает чужой дедлайн — и говорит об этом.

        ``sink.disable`` уже снятого приёмника отказывает («его и не было») и
        ничего не записывает. Если бы он при этом молча продлевал срок, такая
        команда в цикле опроса держала бы правку вечно — «включил DEBUG и забыл»
        через заднюю дверь. Опасно тут не поведение, а молчание: оператор ушёл
        бы с догадкой вместо остатка.
        """
        svc, handlers, clock = wired
        handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 60})
        clock.advance(50)

        res = handlers["logger.sink.disable"]({"sink": "messages_file"})
        assert res["success"] is False
        assert res["session_key_held"] == "channels.messages_file.enabled"
        assert res["expires_in_sec"] == 10.0
        assert "НЕ продлён" in res["ttl_hint"]
        assert "ttl_extended" not in res

        clock.advance(11)
        assert sweep_session_ttl(svc) is not None, "срок всё-таки продлился вопреки отказу"

    def test_repeat_with_explicit_ttl_extends_the_deadline(self, wired) -> None:
        """Task 5.10.d (резидуал T3): продление — той же командой, а не другой.

        Пара к предыдущему тесту: различие держится на ЯВНОСТИ ``ttl``, а не на
        факте правки. До 5.10 продлить срок ручкой приёмника было нельзя вовсе —
        только через ``config.reload`` с секцией, то есть через другой синтаксис
        для того же намерения.
        """
        svc, handlers, clock = wired
        handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 60})
        clock.advance(50)

        res = handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 60})
        assert res["success"] is False, "состояние не изменилось — это по-прежнему отказ"
        assert res["ttl_extended"] is True
        assert res["expires_in_sec"] == 60.0

        clock.advance(11)  # 61с от первой правки: по старому сроку было бы истечение
        assert sweep_session_ttl(svc) is None, "продление не сработало"
        clock.advance(50)
        assert sweep_session_ttl(svc) is not None, "продлённый срок так и не истёк"

    def test_failed_enable_does_not_extend_the_deadline_of_the_disable(self, wired) -> None:
        """Замечание 4 ревью 5.10: продлевать можно только достигнутое состояние.

        Живьём: `sink.disable module_camera ttl=30` (успех) → канал исчез из
        конфига → `sink.enable module_camera ttl=600` (провал). Прежняя редакция
        отвечала `ttl_extended: true` внутри `success: false` и растягивала срок
        записи **disable** с 30 до 600 секунд. Оператор просил временно вернуть
        приёмник, а команда в двадцать раз продлила его отсутствие.
        """
        svc, handlers, clock = wired
        assert handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 30})["success"] is True
        clock.advance(10)
        # Приёмник, которого больше нет в конфиге, вернуть неоткуда — так и
        # получается провал возврата (живьём это состояние после смены рецепта).
        # Условие строится, а не выпрашивается у окружения: пропущенный тест
        # ничего не доказывает.
        svc.logger_manager.config.channels.pop("messages_file", None)

        res = handlers["logger.sink.enable"]({"sink": "messages_file", "ttl": 600})
        assert res["success"] is False, "возврат удался — сценарий не построен"
        assert "ttl_extended" not in res
        assert res["expires_in_sec"] == 20.0, "срок противоположной записи всё-таки сдвинут"
        assert "противоположное состояние" in res["ttl_hint"]

    def test_ttl_of_one_key_does_not_extend_another(self, wired) -> None:
        """Срок ставится ключам ЭТОЙ команды: иначе свежая правка вечно продлевает забытую."""
        svc, handlers, clock = wired
        handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 60})
        clock.advance(50)
        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}, "ttl": 600})

        clock.advance(20)
        report = sweep_session_ttl(svc)
        assert report is not None and report["keys"] == ["channels.messages_file.enabled"]
        assert _level(svc) == "DEBUG", "чужой ключ снят вместе с просроченным"


class TestPolicyLivesInTheLayers:
    """``session_ttl_sec`` — такой же ключ слоёв, как всё остальное."""

    def test_app_layer_changes_the_default_ttl(self, wired) -> None:
        svc, handlers, clock = wired
        process_observability_layers(svc).app = {"session_ttl_sec": 30}

        res = handlers["logger.sink.disable"]({"sink": "messages_file"})
        assert res["ttl_sec"] == 30.0

        clock.advance(31)
        assert sweep_session_ttl(svc) is not None

    def test_policy_zero_disables_deadlines_entirely(self, wired) -> None:
        """Отказ от защиты допустим — но декларативный, а не по забывчивости."""
        svc, handlers, clock = wired
        process_observability_layers(svc).app = {"session_ttl_sec": 0}

        res = handlers["logger.sink.disable"]({"sink": "messages_file"})
        assert res["ttl_sec"] is None

        clock.advance(100000)
        assert sweep_session_ttl(svc) is None

    def test_broken_policy_value_falls_back_to_the_framework_default(self, wired) -> None:
        """Опечатка в конфиге не имеет права молча снять защиту."""
        svc, _handlers, _clock = wired
        layers = process_observability_layers(svc)
        layers.app = {"session_ttl_sec": "пятьсот"}
        assert layers.effective_session_ttl() == 300.0


class TestTheRevertIsAnnounced:
    """Возврат без объявления = «куда делись мои DEBUG-записи» через час."""

    def test_revert_is_logged_and_kept_in_the_ring(self, wired) -> None:
        svc, handlers, clock = wired
        handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 10})
        clock.advance(11)
        sweep_session_ttl(svc)

        warnings = svc.messages("WARNING")
        assert any("channels.messages_file.enabled" in m and "TTL" in m for m in warnings), warnings

        # Task 5.9: кольцо возвратов стало ВЫБОРКОЙ из аудита, и форма записи
        # сменилась вместе с переездом: `ok` вместо `success`, `ts` вместо `at`,
        # плюс `origin`/`seq`. Два написания одного факта не заводятся даже ради
        # совместимости поля.
        ring = list(process_observability_layers(svc).session_reverts)
        assert len(ring) == 1
        assert ring[0]["keys"] == ["channels.messages_file.enabled"]
        assert ring[0]["ok"] is True and ring[0]["reason"] == "ttl"
        assert ring[0]["origin"] == "ttl-sweeper", "возврат по сроку обязан быть отличим от отката руками"

    def test_introspect_shows_deadlines_and_the_last_reverts(self, wired) -> None:
        """readback отвечает и «что висит», и «что уже вернулось»."""
        svc, handlers, clock = wired
        handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 100})

        view = handlers["introspect.observability"]({})["layers"]
        assert view["ttl"] == {"channels.messages_file.enabled": 100.0}
        assert view["ttl_default_sec"] == 300.0
        assert view["reverts"] == []

        clock.advance(101)
        # readback НЕ мутирует: срок вышел, а возврата ещё не было — и это видно.
        view = handlers["introspect.observability"]({})["layers"]
        assert view["ttl"]["channels.messages_file.enabled"] == -1.0
        assert view["session_keys"] == ["channels.messages_file.enabled"]

        sweep_session_ttl(svc)
        view = handlers["introspect.observability"]({})["layers"]
        assert view["ttl"] == {} and view["session_keys"] == []
        assert len(view["reverts"]) == 1

    def test_failed_rebuild_is_loud_and_retried_on_the_next_tick(self, wired) -> None:
        """Ключ уже снят с L3 — молчаливый отказ оставил бы менеджеры вечно расходящимися."""
        svc, handlers, clock = wired
        handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 10})
        clock.advance(11)

        broken = svc.logger_manager.reconfigure
        calls: List[int] = []

        def _fail(payload):
            calls.append(1)
            raise RuntimeError("reconfigure упал")

        svc.logger_manager.reconfigure = _fail
        report = sweep_session_ttl(svc)
        assert report is not None and report["success"] is False
        assert any("не удалось" in m for m in svc.messages("ERROR")), svc.messages("ERROR")
        assert process_observability_layers(svc).rebuild_pending is True

        # Следующий такт: истёкших ключей уже нет, но повтор обязан состояться.
        svc.logger_manager.reconfigure = broken
        retry = sweep_session_ttl(svc)
        assert retry is not None and retry["reason"] == "retry" and retry["success"] is True
        assert "messages_file" in _active(svc), "повтор не довёл возврат до менеджеров"
        assert process_observability_layers(svc).rebuild_pending is False
        assert len(calls) == 1

    def test_successful_command_rebuild_pays_off_the_sweeper_debt(self, wired) -> None:
        """Долг пересборки гасит ЛЮБАЯ удачная пересборка, не только повтор такта.

        Иначе после неудачного возврата и последующего успешного ``config.reload``
        такт клал бы в кольцо запись о возврате, которого не было (advisory ревью).
        """
        svc, handlers, clock = wired
        layers = process_observability_layers(svc)
        handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 10})
        clock.advance(11)

        real = svc.logger_manager.reconfigure
        svc.logger_manager.reconfigure = lambda payload: (_ for _ in ()).throw(RuntimeError("упал"))
        assert sweep_session_ttl(svc)["success"] is False
        svc.logger_manager.reconfigure = real
        assert layers.rebuild_pending is True

        handlers["config.reload"]({"observability": {"log_level": "WARNING"}, "ttl": 0})
        assert layers.rebuild_pending is False, "успешная пересборка не погасила долг"
        assert sweep_session_ttl(svc) is None, "такт объявил возврат, которого не было"
        assert len(layers.session_reverts) == 1


class TestBoundariesOfTheDeadline:
    """persist / switch / отсутствие такта — где срок кончается по-другому."""

    def test_persist_clears_the_deadline_and_reports_it(self, wired, tmp_path) -> None:
        """Сохранённое в файл вечно по построению — срок на нём был бы ложью."""
        svc, handlers, clock = wired
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("processes: {}\n", encoding="utf-8")
        handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 60})

        res = handlers["observability.persist"]({"recipe_path": str(recipe)})
        assert res["success"] is True
        assert res["ttl_cleared"] == ["channels.messages_file.enabled"]

        clock.advance(600)
        assert sweep_session_ttl(svc) is None
        assert "messages_file" not in _active(svc), "сохранённая правка откатилась по чужому сроку"

    def test_session_clear_takes_the_deadlines_with_it(self, wired) -> None:
        """switch = новая сессия: срок не имеет права пережить свой ключ."""
        svc, handlers, clock = wired
        handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 60})

        handlers["config.reload"]({"observability_session_clear": True})
        layers = process_observability_layers(svc)
        assert layers.session_keys() == () and layers.session_ttl_view() == {}

        clock.advance(600)
        assert sweep_session_ttl(svc) is None, "призрачный возврат уже несуществующего ключа"
        assert list(layers.session_reverts) == []

    def test_explicit_reset_takes_the_deadline_with_it(self, wired) -> None:
        svc, handlers, clock = wired
        handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 60})
        handlers["config.reload"]({"observability_reset": ["channels.messages_file.enabled"]})

        layers = process_observability_layers(svc)
        assert layers.session_ttl_view() == {}
        clock.advance(600)
        assert sweep_session_ttl(svc) is None

    def test_process_without_heartbeat_says_the_deadline_is_not_enforced(self, wired) -> None:
        """Молчаливое «срок принят» там, где возврата не будет, — ложный сигнал."""
        svc, handlers, _clock = wired
        assert ttl_enforced(svc) is False

        res = handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 60})
        assert res["ttl_enforced"] is False
        assert "heartbeat" in res["ttl_warning"]

    def test_running_heartbeat_makes_the_deadline_enforced(self, wired) -> None:
        svc, handlers, _clock = wired
        svc.worker_manager = _Wm()
        svc._config["heartbeat_interval"] = 5.0
        svc._heartbeat = ProcessHeartbeat(svc)
        svc._heartbeat.start()

        assert ttl_enforced(svc) is True
        res = handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 60})
        assert res["ttl_enforced"] is True and "ttl_warning" not in res

    def test_heartbeat_disabled_by_config_is_not_running(self, wired) -> None:
        """Ветки раннего выхода start() — это и есть «процесс без авто-возврата»."""
        svc, _handlers, _clock = wired
        svc.worker_manager = _Wm()
        svc._config["heartbeat_interval"] = 0
        svc._heartbeat = ProcessHeartbeat(svc)
        svc._heartbeat.start()
        assert ttl_enforced(svc) is False

    def test_sweep_is_free_for_a_process_that_never_touched_a_handle(self) -> None:
        """Ни одной правки — ни стека, ни работы: подметальщик выходит на первой строке."""

        class _Bare:
            name = "bare"

        assert sweep_session_ttl(_Bare()) is None


class TestRefusals:
    """Опечатка в сроке обязана быть громкой и НИЧЕГО не менять."""

    @pytest.mark.parametrize("bad", [-1, "скоро", float("nan"), float("inf"), True])
    def test_bad_ttl_is_refused_and_the_sink_is_untouched(self, wired, bad) -> None:
        svc, handlers, _clock = wired
        res = handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": bad})
        assert res["success"] is False
        assert "ttl" in res["reason"]
        assert "messages_file" in _active(svc), "приёмник снят, хотя команда отказала"
        assert process_observability_layers(svc).session_keys() == ()

    def test_bad_ttl_in_reload_applies_nothing(self, wired) -> None:
        svc, handlers, _clock = wired
        res = handlers["config.reload"]({"observability": {"log_level": "DEBUG"}, "ttl": -5})
        assert res["success"] is False
        assert _level(svc) != "DEBUG"

    def test_ttl_above_the_schema_limit_is_refused(self, wired) -> None:
        """Параметр команды не имеет права обходить ``max`` поля схемы (advisory ревью)."""
        svc, handlers, _clock = wired
        res = handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 10**9})
        assert res["success"] is False and "предел" in res["reason"]
        assert "messages_file" in _active(svc)

    def test_ttl_on_a_file_reload_is_refused_not_ignored(self, wired, tmp_path) -> None:
        """Замечание 2 ревью: файл владеет БЕССРОЧНЫМ слоем L1.

        Прежняя редакция принимала ttl и молча теряла его: оператор уходил
        уверенным, что правка временная, а она вечная.
        """
        svc, handlers, clock = wired
        cfg = tmp_path / "system.yaml"
        cfg.write_text("observability:\n  log_level: DEBUG\n", encoding="utf-8")

        res = handlers["config.reload"]({"path": str(cfg), "ttl": 30})
        assert res["success"] is False and "ttl" in res["reason"]
        assert _level(svc) != "DEBUG", "секция применилась, хотя команда отказала"

        # Без ttl тот же вызов работает как раньше — отказ адресный, а не запрет.
        assert handlers["config.reload"]({"path": str(cfg)})["success"] is True
        assert _level(svc) == "DEBUG"
        clock.advance(100000)
        assert sweep_session_ttl(svc) is None, "слой приложения оказался срочным"


class TestMechanismHazards:
    """Опасности САМОГО механизма — то, что видно только автору."""

    def test_concurrent_writes_and_sweeps_lose_nothing(self, wired) -> None:
        """Четвёртый писатель ходит по тем же вложенным словарям, что и команды.

        Проверяемое свойство точечное: **своя запись жива до своего же сброса**.
        Соседи трогают только собственные ключи, поэтому под локом это строго
        детерминировано. Без лока теряется молча: ``session_set`` создаёт ветку
        ``channels`` пустой, соседний ``session_reset`` в этот момент подчищает
        её как опустевшую — и запись уходит в отцепленный словарь.

        ``setswitchinterval`` уменьшен намеренно: окно гонки — два байткода между
        созданием ветки и записью листа, и на дефолтных 5мс интерпретатор в него
        почти не попадает. Первая редакция теста этого не делала и **пережила
        собственный слом** (лок снят — зелено), то есть не существовала.
        """
        svc, _handlers, _clock = wired
        layers = process_observability_layers(svc)
        errors: List[BaseException] = []
        lost: List[str] = []
        stop = threading.Event()

        def _writer(index: int) -> None:
            key = f"channels.ch{index}.enabled"
            try:
                for _ in range(2000):
                    layers.session_set(key, False, ttl=0, origin="test")
                    if key not in layers.session_keys():
                        lost.append(key)
                    layers.session_reset(key, origin="test")
            except BaseException as exc:  # noqa: BLE001 — гонка обязана всплыть тестом
                errors.append(exc)

        def _sweeper() -> None:
            try:
                while not stop.is_set():
                    layers.expire_due()
                    layers.session_ttl_view()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        previous_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        threads = [threading.Thread(target=_writer, args=(i,), daemon=True) for i in range(6)]
        sweeper = threading.Thread(target=_sweeper, daemon=True)
        try:
            sweeper.start()
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)
                assert not t.is_alive(), "писатель завис — лок держится дольше операции"
        finally:
            stop.set()
            sweeper.join(timeout=10)
            sys.setswitchinterval(previous_interval)
        assert not sweeper.is_alive()
        assert errors == [], errors
        assert lost == [], f"записи потеряны гонкой: {len(lost)}"

    def test_sweep_between_read_and_write_of_a_reload_does_not_resurrect_a_key(self, wired) -> None:
        """Блокер ревью 5.8, воспроизведён его репро-скриптом.

        ``config.reload`` читал ``layers.session``, мержил и присваивал результат
        ВНЕ лока. Подметальщик, попавший в этот зазор, оказывался отменён: его
        ключ воскресал в присвоенном словаре — и уже БЕЗ срока (``session_touch``
        трогает только ключи текущей правки). Итог: журнал объявил возврат,
        приёмник остался снят навсегда, сроков на нём нет.

        Шов стоит РОВНО В ЗАЗОРЕ: ``deep_merge`` сначала копирует базу (чтение
        ``layers.session``), затем идёт по ``overlay.items()`` — оттуда и
        поднимается ОТДЕЛЬНЫЙ поток подметальщика, до присваивания результата.
        Второй поток обязателен: лок реентерабелен, и вызов из того же потока
        прошёл бы сквозь него, то есть проверял бы не лок. Первая редакция теста
        вешала шов на часы — то есть ПОСЛЕ присваивания — и слом пережила.
        """
        svc, handlers, clock = wired
        layers = process_observability_layers(svc)
        handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 10})
        clock.advance(11)

        sweeper = _SweeperSeam(svc)
        try:
            handlers["config.reload"]({"observability": _SeamSection(sweeper, log_level="DEBUG"), "ttl": 30})
        finally:
            sweeper.finish()

        assert sweeper.started, "шов не сработал: поток подметальщика не запускался"
        held = layers.session_keys()
        assert "channels.messages_file.enabled" not in held, (
            "просроченный ключ воскрес: возврат объявлен, а приёмник остался снят"
        )
        assert "messages_file" in _active(svc)
        assert layers.session_ttl_view().get("log_level") == 30.0

    def test_expiring_a_branch_reports_every_leaf_it_removed(self, wired) -> None:
        """Замечание 3 ревью 5.8: отчёт называл ветку, исчезали ещё и соседи.

        Срок на пути-родителе (``scopes`` — пустой под-словарь тоже лист) при
        истечении сносит всю ветку. Прежняя редакция отчитывалась словом
        ``scopes``, а сроки листьев под ним оставались сиротами в readback'е.
        """
        svc, handlers, clock = wired
        layers = process_observability_layers(svc)
        handlers["config.reload"]({"observability": {"scopes": {"DEBUG": {"enabled": True}}}, "ttl": 600})
        assert layers.session_ttl_view() == {"scopes.DEBUG.enabled": 600.0}

        handlers["config.reload"]({"observability": {"scopes": {}}, "ttl": 10})
        clock.advance(11)
        report = sweep_session_ttl(svc)

        assert report is not None
        assert report["keys"] == ["scopes.DEBUG.enabled"], "отчёт назвал не то, что реально снято"
        assert layers.session_ttl_view() == {}, "срок-сирота пережил свой ключ"
        assert layers.session_keys() == ()

    def test_explicit_reset_of_a_branch_reports_and_clears_its_leaves(self, wired) -> None:
        """Тот же дефект на пути ручного сброса — команда обязана назвать снятое."""
        svc, handlers, clock = wired
        layers = process_observability_layers(svc)
        handlers["config.reload"]({"observability": {"scopes": {"DEBUG": {"enabled": True}}}, "ttl": 600})

        res = handlers["config.reload"]({"observability_reset": ["scopes"]})
        assert res["reset"] == ["scopes.DEBUG.enabled"]
        assert layers.session_ttl_view() == {}
        assert layers.session_keys() == ()

    def test_persist_snapshot_and_clear_are_one_critical_section(self, wired, tmp_path) -> None:
        """Вторая половина блокера: правка между снимком и обнулением L3 не теряется.

        Шов — запись спутника: между снимком L3 и его обнулением. Подметальщик
        поднимается ОТДЕЛЬНЫМ потоком (лок реентерабелен — свой поток прошёл бы
        насквозь). Под локом он паркуется до конца блока и застаёт уже пустую
        сессию; без лока успевает снять просроченный ключ и пересобрать конфиг
        по слоям, где сохранённого ещё нет.
        """
        svc, handlers, clock = wired
        layers = process_observability_layers(svc)
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text("processes: {}\n", encoding="utf-8")
        handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 0})
        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}, "ttl": 5})
        clock.advance(6)

        from multiprocess_framework.modules.process_module.configs import observability_companion

        sweeper = _SweeperSeam(svc)
        real_persist = observability_companion.persist_session_to_companion
        observability_companion.persist_session_to_companion = sweeper.wrap(real_persist)
        try:
            res = handlers["observability.persist"]({"recipe_path": str(recipe)})
        finally:
            observability_companion.persist_session_to_companion = real_persist
            sweeper.finish()

        assert sweeper.started, "шов не сработал: поток подметальщика не запускался"
        assert res["success"] is True
        # Сохранено И снятие приёмника, и (просроченный, но ещё не снятый) уровень:
        # снимок взят до возврата, значит в L2 уезжает ровно он, целиком.
        assert res["ttl_cleared"] == ["log_level"]
        assert layers.session_keys() == ()
        assert "messages_file" not in _active(svc), "сохранённое снятие потеряно гонкой"

    def test_layers_survive_pickle(self, wired) -> None:
        """Стек живёт на объекте процесса — непиклимый лок сломал бы spawn."""
        layers = ObservabilityLayers(app={"log_level": "INFO"})
        layers.session_set("log_level", "DEBUG", ttl=60, origin="test")
        restored = pickle.loads(pickle.dumps(layers))
        assert restored.session == {"log_level": "DEBUG"}
        assert set(restored.session_expiry) == {"log_level"}
        # Лок пересоздан, а не потерян: иначе первая же правка в дочернем упала бы.
        restored.session_set("log_level", "INFO", ttl=0, origin="test")
        assert restored.session_ttl_view() == {}

    def test_real_heartbeat_tick_performs_the_revert(self, wired) -> None:
        """Провод, а не механизм: такт РЕАЛЬНОГО heartbeat действительно метёт.

        Тест на фейках доказал бы фейки — переименование метода в heartbeat'е
        оставило бы всё зелёным, а возврат перестал бы происходить.
        """
        svc, handlers, clock = wired
        svc._config["heartbeat_interval"] = 0.05
        handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 10})
        clock.advance(11)

        heartbeat = ProcessHeartbeat(svc)
        heartbeat._interval = 0.05
        stop = threading.Event()
        pause = threading.Event()
        # Цикл обязан идти в daemon-потоке с дедлайном: тест, который ВИСНЕТ
        # вместо падения, прячет регресс за таймаутом.
        worker = threading.Thread(target=heartbeat._loop, args=(stop, pause), daemon=True)
        worker.start()
        try:
            deadline = threading.Event()
            for _ in range(100):
                if "messages_file" in _active(svc):
                    break
                deadline.wait(0.05)
        finally:
            stop.set()
            worker.join(timeout=5)
        assert not worker.is_alive(), "heartbeat не остановился по stop_event"
        assert "messages_file" in _active(svc), "такт heartbeat не вернул просроченную правку"
        assert svc.sent, "такт не дошёл до отправки heartbeat — цикл не крутился"


class TestStuckRebuildDoesNotEatTheAuditRing:
    """A-A6-1 на ПРОДАКШН-пути: залипший отказ пересборки не выедает кольцо.

    Проверяется настоящим `sweep_session_ttl`, а не имитацией его записи: репро
    ревьюера строило запись руками и несло собственную отметку времени, из-за
    чего два такта повтора никогда не были одинаковыми. Именно эта отметка и
    снята — но доказывать это обязан тот код, который поедет в прод (урок «тест
    на фейковой обвязке доказывает обвязку»).
    """

    def test_a_hundred_failing_ticks_leave_the_real_revert_visible(self, wired) -> None:
        svc, handlers, clock = wired
        handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 10})
        clock.advance(11)

        def _fail(payload):
            raise RuntimeError("reconfigure упал")

        svc.logger_manager.reconfigure = _fail
        for _ in range(100):
            report = sweep_session_ttl(svc)
            assert report is not None and report["success"] is False

        audit = process_observability_layers(svc).audit
        failures = [e for e in audit.entries(action=ACTION_EXPIRE) if not e.get("ok")]
        # Две, а не одна, и это ПРАВИЛЬНО: первый такт несёт истёкшие ключи
        # («снятие не доехало до менеджеров»), а повторы идут с пустыми
        # («пересобрать всё ещё не удаётся») — разные факты для читателя.
        # Схлопывается ровно повторяющееся.
        assert len(failures) == 2, f"сто отказов легли {len(failures)} записями"
        assert failures[0]["keys"] == ["channels.messages_file.enabled"]
        assert failures[0].get("repeats") is None, "первый отказ не повтор"
        assert failures[1]["keys"] == [] and failures[1]["repeats"] == 99
        assert audit.dropped() == 0, "схлопывание сообщило о вытеснении, которого не было"
        # Причина (кто и когда трогал ключ) обязана пережить следствие
        assert audit.entries(action=ACTION_SET), "авторство ключей вытеснено отказами"

    def test_the_recovering_tick_is_its_own_entry(self, wired) -> None:
        """Контроль: успех после сотни отказов — отдельная запись, не 101-й повтор."""
        svc, handlers, clock = wired
        handlers["logger.sink.disable"]({"sink": "messages_file", "ttl": 10})
        clock.advance(11)

        broken = svc.logger_manager.reconfigure

        def _fail(payload):
            raise RuntimeError("reconfigure упал")

        svc.logger_manager.reconfigure = _fail
        for _ in range(100):
            sweep_session_ttl(svc)
        svc.logger_manager.reconfigure = broken
        recovered = sweep_session_ttl(svc)

        assert recovered is not None and recovered["success"] is True
        audit = process_observability_layers(svc).audit
        expires = audit.entries(action=ACTION_EXPIRE)
        assert [e.get("ok") for e in expires][-1] is True, expires
        # Успех не приклеился к схлопнутой серии отказов: условие сменилось.
        assert expires[-1].get("repeats") is None
        assert len([e for e in expires if not e.get("ok")]) == 2
