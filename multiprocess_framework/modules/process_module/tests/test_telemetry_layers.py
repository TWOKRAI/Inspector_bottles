# -*- coding: utf-8 -*-
"""Task 5.10.f — publish-плоскость телеметрии в слоях и под сроком.

Что закрепляется:

  * рантайм-правка ``telemetry.reconfigure publish=…`` переживает **файловый**
    ``config.reload`` — до задачи файл применялся напрямую и стирал её молча;
  * у правки есть срок, и по истечении гейт возвращается к **загрузочной**
    секции, а не остаётся на последней правке;
  * ``throttle`` в слои НЕ входит, и команда говорит об этом полем ответа, а не
    умолчанием.

Гейт здесь настоящий (``ProcessHeartbeat`` из общего харнесса) — проверка на
фейковом гейте доказывала бы фейк.
"""

from __future__ import annotations

import pytest
import yaml

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    process_observability_layers,
)
from multiprocess_framework.modules.process_module.managers.observability_ttl import (
    sweep_session_ttl,
)
from multiprocess_framework.modules.state_store_module.middleware.throttle import ThrottleMiddleware

from .test_telemetry_commands import _FakeLogger, _FakeServices

BOOT_PUBLISH = {"tick_sec": 1.0, "metrics": {"fps": {"enabled": True, "interval_sec": 5.0}}}


class _Clock:
    """Монотонные часы под управлением теста — зависимость объекта, не глобальный патч."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _wired(tmp_path, *, throttle=None):
    """Процесс с загрузочной publish-секцией, живым гейтом и часами теста."""
    svc = _FakeServices(logger=_FakeLogger(), throttle=throttle)
    svc._config["telemetry"] = {"publish": BOOT_PUBLISH}
    svc._heartbeat._services._config["telemetry"] = {"publish": BOOT_PUBLISH}
    svc._heartbeat._telemetry_gate = svc._heartbeat._build_telemetry_gate()

    cfg_path = tmp_path / "system.yaml"
    cfg_path.write_text(yaml.safe_dump({"observability": {"log_level": "INFO"}}), encoding="utf-8")
    svc._config["observability_config_path"] = str(cfg_path)

    bc = BuiltinCommands(svc)
    bc._register_observability_commands()
    clock = _Clock()
    process_observability_layers(svc).clock = clock
    return svc, svc.command_manager.handlers, clock, cfg_path


def _fps_interval(svc) -> float | None:
    publish = svc._heartbeat.current_telemetry_publish()
    if not publish:
        return None
    return publish.get("metrics", {}).get("fps", {}).get("interval_sec")


class TestPublishSurvivesFileReload:
    def test_boot_section_is_the_starting_point(self, tmp_path) -> None:
        """Контроль: гейт собран из загрузочной секции — иначе проверять нечего."""
        svc, _, _, _ = _wired(tmp_path)
        assert _fps_interval(svc) == 5.0

    def test_runtime_publish_survives_reload_from_file(self, tmp_path) -> None:
        """Главная пара 5.10.f: правка пережила перечитывание файла.

        До задачи ``config.reload`` из файла применял telemetry-секцию напрямую
        (а её в файле нет), и правка оператора исчезала бесследно.
        """
        svc, handlers, _, cfg_path = _wired(tmp_path)
        res = handlers["telemetry.reconfigure"](
            {"publish": {"metrics": {"fps": {"enabled": True, "interval_sec": 0.5}}}}
        )
        assert res["success"] is True
        assert res["survives_reload"] is True
        assert _fps_interval(svc) == 0.5

        reload_res = handlers["config.reload"]({"path": str(cfg_path)})
        assert reload_res["success"] is True
        assert _fps_interval(svc) == 0.5, "файловый reload стёр рантайм-правку телеметрии"

    def test_the_layer_key_is_named_in_the_answer(self, tmp_path) -> None:
        """Что держится сессией — видно, а не выясняется по поведению процесса."""
        svc, handlers, _, _ = _wired(tmp_path)
        handlers["telemetry.reconfigure"]({"publish": {"metrics": {"fps": {"interval_sec": 0.5}}}})
        held = list(process_observability_layers(svc).session_keys())
        assert "telemetry.publish.metrics.fps.interval_sec" in held


class TestPublishReturnsByDeadline:
    def test_expiry_returns_the_gate_to_the_boot_section(self, tmp_path) -> None:
        """Срок истёк → гейт вернулся к ЗАГРУЗОЧНОЙ секции, а не к последней правке."""
        svc, handlers, clock, _ = _wired(tmp_path)
        res = handlers["telemetry.reconfigure"]({"publish": {"metrics": {"fps": {"interval_sec": 0.5}}}, "ttl": 60})
        assert res["ttl_sec"] == 60.0
        assert _fps_interval(svc) == 0.5

        clock.advance(30)
        assert sweep_session_ttl(svc) is None, "возврат наступил ДО срока"
        assert _fps_interval(svc) == 0.5

        clock.advance(31)
        entry = sweep_session_ttl(svc)
        assert entry is not None and entry["success"] is True
        assert _fps_interval(svc) == 5.0, "гейт не вернулся к загрузочной секции"

    def test_expired_keys_are_named_in_the_revert_record(self, tmp_path) -> None:
        """Возврат объявлен поимённо: «что-то вернулось» — не ответ."""
        svc, handlers, clock, _ = _wired(tmp_path)
        handlers["telemetry.reconfigure"]({"publish": {"metrics": {"fps": {"interval_sec": 0.5}}}, "ttl": 10})
        clock.advance(11)
        entry = sweep_session_ttl(svc)
        assert entry is not None
        assert "telemetry.publish.metrics.fps.interval_sec" in entry["keys"]


class TestThrottleDeltaLivesAsOneLeaf:
    """Task 5.10.g — дельта троттла в слоях, но ОДНИМ непрозрачным листом.

    Класс перевёрнут решением по рекомендации ревью: до 5.10.g он закреплял
    честность границы («в слоях не живёт — и мы это говорим»), теперь —
    саму жизнь в слое. Форма выбрана не из вкуса: per-rule ключ там сломан по
    построению, потому что точки внутри паттерна режутся как разделители пути
    (см. ``OPAQUE_LAYER_PATHS`` и тест ``test_pattern_with_dots_stays_one_key``).
    """

    def test_delta_is_applied_over_boot_rules(self, tmp_path) -> None:
        """Дельта собирается из ИСТОЧНИКОВ: загрузочные правила + правка."""
        throttle = ThrottleMiddleware({"keep": 5.0})
        svc, handlers, _, _ = _wired(tmp_path, throttle=throttle)
        svc._config["state_throttle_rules"] = {"keep": 5.0}
        res = handlers["telemetry.reconfigure"]({"throttle": {"a.b": 2.0}})
        assert res["success"] is True
        assert res["applied"]["throttle"] is True
        assert res["survives_reload"] is True
        assert throttle.rules == {"keep": 5.0, "a.b": 2.0}

    def test_pattern_with_dots_stays_one_key(self, tmp_path) -> None:
        """Ключ слоя ОДИН, каким бы ни был паттерн внутри.

        Воспроизведение дефекта, ради которого лист непрозрачен: per-rule путь
        `telemetry.throttle.processes.**.state.fps` резался по точкам, заводил в
        слое вложенное дерево РЯДОМ с настоящим правилом, и сброс снимал дерево,
        рапортуя успех, — правило при этом оставалось жить.
        """
        throttle = ThrottleMiddleware({})
        svc, handlers, _, _ = _wired(tmp_path, throttle=throttle)
        handlers["telemetry.reconfigure"]({"throttle": {"processes.**.state.fps": 2.0}})
        assert list(process_observability_layers(svc).session_keys()) == ["telemetry.throttle"]
        assert throttle.rules == {"processes.**.state.fps": 2.0}

    def test_delta_expires_back_to_boot_rules(self, tmp_path) -> None:
        """Единственная выгода переезда: срок и возврат к загрузочным правилам."""
        throttle = ThrottleMiddleware({"keep": 5.0})
        svc, handlers, clock, _ = _wired(tmp_path, throttle=throttle)
        svc._config["state_throttle_rules"] = {"keep": 5.0}
        res = handlers["telemetry.reconfigure"]({"throttle": {"a.b": 2.0}, "ttl": 30})
        assert res["ttl_sec"] == 30.0
        assert throttle.rules == {"keep": 5.0, "a.b": 2.0}

        clock.advance(31)
        entry = sweep_session_ttl(svc)
        assert entry is not None and entry["keys"] == ["telemetry.throttle"]
        assert throttle.rules == {"keep": 5.0}, "возврат не к загрузочным правилам"

    def test_removal_marker_survives_the_move_to_layers(self, tmp_path) -> None:
        """``None`` у паттерна по-прежнему означает «правила нет» (контракт Ф1)."""
        throttle = ThrottleMiddleware({"keep": 5.0, "drop.me": 1.0})
        svc, handlers, _, _ = _wired(tmp_path, throttle=throttle)
        svc._config["state_throttle_rules"] = {"keep": 5.0, "drop.me": 1.0}
        handlers["telemetry.reconfigure"]({"throttle": {"drop.me": None}})
        assert throttle.rules == {"keep": 5.0}

    def test_both_planes_in_one_command(self, tmp_path) -> None:
        """Одна команда — обе плоскости, и обе под сроком."""
        throttle = ThrottleMiddleware({})
        svc, handlers, _, _ = _wired(tmp_path, throttle=throttle)
        res = handlers["telemetry.reconfigure"](
            {"publish": {"metrics": {"fps": {"interval_sec": 0.5}}}, "throttle": {"a.b": 2.0}}
        )
        assert res["success"] is True
        assert res["survives_reload"] is True
        assert "точки" in res["throttle_ttl_scope"], "разница в гранулярности срока не названа"
        assert _fps_interval(svc) == 0.5
        assert throttle.rules == {"a.b": 2.0}

    def test_no_receiver_is_an_answer_not_silence(self, tmp_path) -> None:
        """Нет центрального троттла (обычный процесс) → это сказано, а не умолчано."""
        svc, handlers, _, _ = _wired(tmp_path)  # без throttle
        res = handlers["telemetry.reconfigure"]({"throttle": {"a.b": 2.0}})
        assert res["applied"]["throttle"] is False


class TestReviewFindings:
    """Четыре замечания ревью 5.10 — каждое со своей парой."""

    def test_ttl_on_a_throttle_only_command_is_honoured_not_swallowed(self, tmp_path) -> None:
        """З-1: срок не теряется молча.

        В редакции 5.10.f адресата у него не было, и правильным ответом был
        отказ. С 5.10.g дельта троттла живёт в слое — и срок к ней применим;
        проверяется то же самое свойство (срок не исчезает без слова), но теперь
        его исполняют, а не отвергают.
        """
        throttle = ThrottleMiddleware({})
        svc, handlers, clock, _ = _wired(tmp_path, throttle=throttle)
        res = handlers["telemetry.reconfigure"]({"throttle": {"a.b": 2.0}, "ttl": 60})
        assert res["success"] is True
        assert res["ttl_sec"] == 60.0
        assert process_observability_layers(svc).session_expires_in("telemetry.throttle") == 60.0

    def test_unknown_mode_is_refused_on_the_observability_path_too(self, tmp_path) -> None:
        """З-2: опечатка в режиме не должна проходить из-за соседней секции.

        Отказ зависел от того, приехала ли рядом секция observability: ветка
        наблюдаемости вливала publish в слой раньше валидации.
        """
        svc, handlers, _, _ = _wired(tmp_path)
        res = handlers["config.reload"](
            {
                "observability": {"log_level": "DEBUG"},
                "telemetry": {"publish": {"metrics": {"fps": {"interval_sec": 0.25}}}},
                "telemetry_mode": "bogus",
            }
        )
        assert res["success"] is False
        assert "bogus" in res["reason"]
        assert _fps_interval(svc) == 5.0, "секция применена вопреки отказу"

    def test_replace_drops_the_previous_session_subtree(self, tmp_path) -> None:
        """З-3(а): режим «замена» обязан заменять, а не ложиться поверх.

        Прежняя редакция звала тот же deep_merge, и правка предыдущей команды
        выживала: сессия держала оба ключа, гейт — обе метрики.
        """
        svc, handlers, _, _ = _wired(tmp_path)
        handlers["telemetry.reconfigure"]({"publish": {"metrics": {"latency_ms": {"enabled": False}}}})
        handlers["telemetry.reconfigure"]({"publish": {"metrics": {"fps": {"interval_sec": 0.5}}}})
        held = list(process_observability_layers(svc).session_keys())
        assert held == ["telemetry.publish.metrics.fps.interval_sec"], f"прошлая правка пережила замену: {held}"

    def test_merge_does_not_extend_the_deadline_of_foreign_keys(self, tmp_path) -> None:
        """З-3(б): срок ставится ключам ЭТОЙ правки.

        Иначе «включил и забыл» возвращается через заднюю дверь внутри одной
        секции: свежая правка вечно продлевает давно забытую соседнюю.
        """
        svc, handlers, clock, _ = _wired(tmp_path)
        handlers["telemetry.reconfigure"]({"publish": {"metrics": {"latency_ms": {"enabled": False}}}, "ttl": 10})
        clock.advance(8)
        handlers["telemetry.reconfigure"](
            {"publish": {"metrics": {"fps": {"interval_sec": 0.5}}}, "telemetry_mode": "merge", "ttl": 600}
        )
        layers = process_observability_layers(svc)
        assert layers.session_expires_in("telemetry.publish.metrics.latency_ms.enabled") == 2.0
        assert layers.session_expires_in("telemetry.publish.metrics.fps.interval_sec") == 600.0


class TestPlaneIsNotTouchedUntilALayerSpeaks:
    def test_observability_reload_alone_does_not_rebuild_the_gate(self, tmp_path) -> None:
        """Пока слои о телеметрии не сказали — плоскость чужая.

        Иначе пересборка наблюдаемости клобберила бы гейт, собранный на старте
        самим heartbeat'ом (а на оркестраторе — ещё и применённое его
        собственным watcher'ом, который идёт ПОСЛЕ неё).
        """
        svc, handlers, _, _ = _wired(tmp_path)
        gate_before = svc._heartbeat._telemetry_gate
        res = handlers["config.reload"]({"observability": {"log_level": "DEBUG"}})
        assert res["success"] is True
        assert svc._heartbeat._telemetry_gate is gate_before, "гейт пересобран без единого слова слоёв"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
