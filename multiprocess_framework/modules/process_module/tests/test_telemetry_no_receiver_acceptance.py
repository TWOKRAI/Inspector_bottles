# -*- coding: utf-8 -*-
"""Приёмочные тесты Task 3.1 — «нет получателя: отказ с адресом, а не успех с мёртвым слотом».

Независимый прогон: контракт взят из формулировки требования (см. промпт задачи),
реализация НЕ читалась. Харнесс переиспользован из ``test_telemetry_commands`` и
``test_telemetry_layers`` (образец, не источник контракта) — те же фейковые сервисы,
тот же способ регистрации команд через ``BuiltinCommands``.

Требуемое поведение (после правки):

  1. ``telemetry.throttle``-подсекция на процессе БЕЗ receiver'а (нет
     ``StateStoreManager`` с троттлом) → ``success=False``, в ``reason`` названы
     и ``throttle``, и ``ProcessManager`` (адрес, куда слать).
  2. Сессионный слой L3 при таком отказе НЕ занимается, TTL не тратится —
     как будто команды не было.
  3. Тот же вход на процессе-получателе (оркестратор, троттл-middleware есть) →
     ``success=True``, применение видно в ``applied``/``telemetry_applied`` И
     в самом состоянии троттла (readback).
  4. Обе двери — ``telemetry.reconfigure`` и ``config.reload`` — ведут себя
     одинаково; проверяются поимённо.
  5. Отказ по throttle не отравляет сосед: publish на том же процессе после
     отказа по-прежнему проходит и применяется.
  6. Файловая дорога (``config.reload`` c ``path=``) не сломана: throttle,
     приехавший из ``system.yaml``, применяется на процессе-получателе.
  7. Симметрия: publish на процессе без heartbeat тоже не должен отчитаться
     успехом-с-применением. Прочтение зафиксировано в докстринге класса ниже.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    process_observability_layers,
)
from multiprocess_framework.modules.process_module.managers.observability_ttl import (
    sweep_session_ttl,
)
from multiprocess_framework.modules.state_store_module.middleware.throttle import (
    ThrottleMiddleware,
)

from .test_telemetry_commands import _FakeCommandManager, _FakeLogger, _FakeServices, _make


class _Clock:
    """Управляемые тестом монотонные часы — зависимость объекта, не глобальный патч.

    Паттерн один-в-один с ``test_telemetry_layers._Clock`` / ``test_observability_ttl._Clock``:
    дублирование мелкого класса — устоявшаяся практика в этом наборе тестов
    (обе сестры-задачи делают так же, а не наследуют друг у друга).
    """

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _ServicesNoHeartbeat:
    """Процесс без heartbeat вовсе (``_heartbeat is None``).

    Легитимное состояние: ``test_observability_ttl._Svc`` заводит его же ради
    ``ttl_enforced(svc) is False``. Здесь используется, чтобы проверить П.7 —
    симметрию с throttle, у которого «нет receiver'а» уже означает явный отказ.
    """

    def __init__(self) -> None:
        self.command_manager = _FakeCommandManager()
        self.name = "boot_stub"
        self.logger_manager = None
        self.error_manager = None
        self.stats_manager = None
        self.router_manager = None
        self._config: dict = {}
        self._heartbeat = None
        self._state_store_manager = None

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def _log_info(self, *a, **k) -> None: ...

    def _log_debug(self, *a, **k) -> None: ...


def _wired_no_receiver():
    """Процесс без получателя throttle (обычный дочерний, например camera_0),
    с управляемыми часами L3 — для проверки, что отказ не трогает сессионный слой.
    """
    svc = _FakeServices(logger=_FakeLogger())  # throttle не передан => нет receiver'а
    bc = BuiltinCommands(svc)
    bc._register_observability_commands()
    clock = _Clock()
    process_observability_layers(svc).clock = clock
    return svc, svc.command_manager.handlers, clock


class TestThrottleNoReceiverRefusesWithAddress:
    """П.1 и П.4: отказ на ОБЕИХ дверях, с адресом в reason."""

    def test_reconfigure_door_refuses_and_names_the_address(self) -> None:
        """telemetry.reconfigure c throttle на процессе без receiver'а → success=False,
        reason называет и throttle, и ProcessManager."""
        svc, cm = _make()  # без throttle => _state_store_manager is None
        res = cm.dispatch("telemetry.reconfigure", {"throttle": {"a.b": 1.0}})
        assert res["success"] is False
        reason = str(res.get("reason", "")).lower()
        assert "throttle" in reason
        assert "process" in reason and "manager" in reason

    def test_reload_door_refuses_and_names_the_address(self) -> None:
        """Та же подсекция через config.reload (data["telemetry"]["throttle"]) — тот же отказ."""
        svc, cm = _make()
        res = cm.dispatch("config.reload", {"telemetry": {"throttle": {"a.b": 1.0}}})
        assert res["success"] is False
        reason = str(res.get("reason", "")).lower()
        assert "throttle" in reason
        assert "process" in reason and "manager" in reason


class TestSessionLayerNotConsumedOnRefusal:
    """П.2: отказ не занимает L3 и не тратит TTL — будто команды не было.

    Без явного ``ttl`` в payload — намеренно. Живая проверка (до правки, вне
    этого теста) показала: даже БЕЗ ``ttl`` throttle-подсекция без receiver'а
    сегодня всё равно попадает в L3 под дефолтным сроком (у ``config.reload``
    подстановка ``ttl`` в payload throttle-only команды вдобавок ловит
    ОТДЕЛЬНЫЙ, не связанный с этой задачей отказ — «ttl нечему адресовать: нет
    ни inline-секции observability, ни telemetry.publish» — который путал бы
    результат теста, не проверяя нужное свойство. Опуская явный ``ttl``, тест
    сторожит именно дефект «мёртвый слот съедает TTL-слот по умолчанию», не
    подсекции ttl-адресации.
    """

    def test_reconfigure_door_l3_not_armed_on_refusal(self) -> None:
        svc, handlers, clock = _wired_no_receiver()
        res = handlers["telemetry.reconfigure"]({"throttle": {"a.b": 1.0}})
        assert res["success"] is False

        layers = process_observability_layers(svc)
        held = list(layers.session_keys())
        assert "telemetry.throttle" not in held, f"L3 занят отказом: {held}"

        clock.advance(1000)  # далеко за любой дефолтный TTL, если бы он был поставлен
        assert sweep_session_ttl(svc) is None, "подметальщик нашёл что снимать — TTL был потрачен отказом"

    def test_reload_door_l3_not_armed_on_refusal(self) -> None:
        svc, handlers, clock = _wired_no_receiver()
        res = handlers["config.reload"]({"telemetry": {"throttle": {"a.b": 1.0}}})
        assert res["success"] is False

        layers = process_observability_layers(svc)
        held = list(layers.session_keys())
        assert "telemetry.throttle" not in held, f"L3 занят отказом: {held}"

        clock.advance(1000)
        assert sweep_session_ttl(svc) is None, "подметальщик нашёл что снимать — TTL был потрачен отказом"


class TestThrottleWithReceiverSucceeds:
    """П.3: тот же вход на процессе-получателе (оркестратор) — success=True и readback."""

    def test_reconfigure_door_applies_and_readback_matches(self) -> None:
        throttle = ThrottleMiddleware({})
        svc, cm = _make(throttle=throttle)
        res = cm.dispatch("telemetry.reconfigure", {"throttle": {"processes.**.state.fps": 2.0}})
        assert res["success"] is True
        assert res["applied"]["throttle"] is True
        assert throttle.rules == {"processes.**.state.fps": 2.0}

    def test_reload_door_applies_and_readback_matches(self) -> None:
        throttle = ThrottleMiddleware({})
        svc, cm = _make(throttle=throttle)
        res = cm.dispatch("config.reload", {"telemetry": {"throttle": {"a.b": 3.0}}})
        assert res["success"] is True
        assert res["telemetry_applied"]["throttle"] is True
        assert throttle.rules == {"a.b": 3.0}


class TestNeighbourNotPoisoned:
    """П.5: попытка throttle-подсекции на процессе без receiver'а не отравляет
    соседнюю (законную) правку publish на том же процессе.

    Намеренно НЕ проверяет исход самой throttle-команды (это предмет П.1) — тот
    факт, что сегодня она отвечает ``success=True`` вместо будущего отказа, не
    имеет отношения к свойству «сосед не отравлен». Свойство обязано держаться
    ДО фикса (throttle сегодня безвредна для publish, просто врёт про себя) И
    ПОСЛЕ (когда throttle станет честным отказом) — поэтому тест зелёный уже
    сейчас и обязан остаться зелёным после Task 3.1.
    """

    def test_publish_still_applies_after_a_throttle_attempt_on_same_process(self) -> None:
        svc, cm = _make()  # без throttle => у throttle-подсекции нет адресата
        cm.dispatch("telemetry.reconfigure", {"throttle": {"a.b": 1.0}})  # исход — не предмет этого теста

        res = cm.dispatch("telemetry.reconfigure", {"publish": {"metrics": {"fps": {"enabled": False}}}})
        assert res["success"] is True
        assert res["applied"]["publish"] is True
        gate = svc._heartbeat._telemetry_gate
        assert gate is not None
        assert "fps" not in gate.due_metrics(now=0.0)


class TestFileRouteStillAppliesThrottleOnReceiver:
    """П.6: файловая дорога (config.reload path=) для throttle не сломана правкой."""

    def test_throttle_section_from_file_applies_on_process_with_receiver(self, tmp_path) -> None:
        throttle = ThrottleMiddleware({"keep": 5.0})
        svc, cm = _make(throttle=throttle)
        cfg_path = tmp_path / "system.yaml"
        cfg_path.write_text("telemetry:\n  throttle:\n    a.b: 2.0\n", encoding="utf-8")

        res = cm.dispatch("config.reload", {"path": str(cfg_path)})
        assert res["success"] is True
        assert throttle.rules == {"a.b": 2.0}  # replace-семантика — как в характеризационных тестах


class TestPublishNoReceiverSymmetry:
    """П.7: публикация без heartbeat тоже не имеет права отчитаться успехом-с-применением.

    Прочтение зафиксировано так: ожидается ОТКАЗ (``success=False``), а не падение
    ``AttributeError`` и не молчаливый ``success=True``. Выбрано по двум причинам:

      (а) ``_heartbeat is None`` — легитимное состояние сервиса в этом же наборе
          тестов (``test_observability_ttl._Svc`` заводит его намеренно), значит
          обработчик команды обязан его пережить, не рухнув;
      (б) «доказанная недостижимость ветки» с уровня unit-теста не проверяема —
          что ``ProcessHeartbeat`` создаётся в конструкторе services безусловно,
          известно из чтения кода сервисов, а не из поведения, наблюдаемого
          обработчиком команды. Unit-тест обязан либо получить словарь-ответ
          с явным отказом, либо (если это единственный технически верный вариант)
          задокументированно упасть, но НЕ отчитаться успехом.
    """

    def test_publish_without_heartbeat_refuses_instead_of_reporting_success(self) -> None:
        svc = _ServicesNoHeartbeat()
        bc = BuiltinCommands(svc)
        bc._register_observability_commands()
        res = svc.command_manager.dispatch(
            "telemetry.reconfigure", {"publish": {"metrics": {"fps": {"enabled": False}}}}
        )
        assert res["success"] is False
        reason = str(res.get("reason", "")).lower()
        assert "publish" in reason or "heartbeat" in reason
