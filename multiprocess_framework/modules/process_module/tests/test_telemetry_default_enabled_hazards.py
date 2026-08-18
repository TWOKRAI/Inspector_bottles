# -*- coding: utf-8 -*-
"""Авторские тесты опасностей механизма ``TelemetryPublishConfig.default_enabled``.

Приёмка (``test_telemetry_default_enabled_acceptance.py``, независимый tester)
доказывает КОНТРАКТ по критериям постановки — прямыми вызовами конструктора и
``resolve()``. Эти тесты — другой объектив: они гоняют ``default_enabled`` через
механизмы, которые видит только автор и которые приёмка не обязана знать:

  1. Слияние per-process секции рецепта с глобальным дефолтом
     (``BlueprintAssembler._resolve_telemetry``,
     ``multiprocess_prototype/backend/assembly/assembler.py:206-226``) — реальный
     ``deep_merge``, а не голая kwargs-сборка ``TelemetryPublishConfig``.
  2. Различие «секции ``telemetry`` нет вовсе» (``_build_telemetry_gate()`` → None)
     и «``default_enabled=False``» (гейт есть, но молчит на всё). Выглядят похоже
     («метрик не видно»), физически противоположны в ``_loop``
     (``process_heartbeat.py:165``): ``allowed_metrics=None`` у
     ``build_worker_telemetry`` значит «всё разрешено», ``allowed_metrics=set()``
     значит «ничего не разрешено».
  3. Сериализация: ``False`` — самый частый тип значения, теряемый в
     самодельных «if value: …»-сериализаторах.
  4. Комбинация «глобально выключено + точечный per-process opt-in» — через тот
     же слитый dict, а не через прямые kwargs (критерии 3a/3b приёмки, но иным
     путём получения конфига).

Framework не имеет права импортировать prototype (R2, ``.sentrux/rules.toml``), и
``BlueprintAssembler`` в тесты не ввозится — вместо этого тест воспроизводит РОВНО
ТУ ЖЕ форму вызова (``deep_merge(global_publish, override)``), которой пользуется
сборщик, тем же framework-хелпером (``multiprocess_framework.modules.
data_schema_module.deep_merge`` — тот же символ, что импортирует
``assembler.py:21``).

Каталог метрик (``gated_metrics()``) наполняется ИМПОРТОМ производителей.
``build_worker_telemetry``/``gated_metrics`` импортируются из
``heartbeat.telemetry`` напрямую (не через реэкспорт) — этот импорт исполняет
модуль и наполняет каталог пятью фреймворковыми именами независимо от порядка
запуска тестов (тот же приём, что уже используется в соседнем
``test_telemetry_gate.py``).
"""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import deep_merge
from multiprocess_framework.modules.process_module.configs import (
    MetricRule,
    TelemetryPublishConfig,
)
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    build_worker_telemetry,
    gated_metrics,
)
from multiprocess_framework.modules.process_module.managers.telemetry_reload import (
    apply_telemetry_reconfigure,
)


class _Services:
    """Минимальный дубль сервисов процесса — дословно ``_MinimalServices`` из
    приёмочного файла (та же причина: ``_warn_capped_metrics``/
    ``_warn_unknown_metrics`` внутри ``_build_telemetry_gate`` достают логгер
    ТОЛЬКО когда есть что сказать — заданный ``tick_sec`` / непустой
    ``unknown_metrics()``; ни одна секция в этом файле их не задаёт, обе ветки
    выходят раньше, до обращения к атрибуту логгера)."""

    def __init__(self, config: dict) -> None:
        self._config = config

    def get_config(self, key: str, default: object = None) -> object:
        return self._config.get(key, default)


def _one_worker() -> dict:
    """Один running-воркер с ненулевыми ``effective_hz``/``cycle_duration_ms`` —
    чтобы агрегату ``state.*`` было из чего строиться. Воркер без измерений не
    отличил бы «выключено гейтом» от «публиковать было нечего» — оба дали бы
    одинаково пустой результат."""
    return {"w0": {"status": "running", "effective_hz": 10.0, "cycle_duration_ms": 5.0}}


class TestBlueprintMergePreservesGlobalDefaultEnabled:
    """Вопрос из спеки (п.5): per-process секция рецепта
    (``blueprint.processes[].telemetry``) мержится поверх глобальной ЧЕРЕЗ
    ``deep_merge`` (``assembler.py:225``), а не заменяет секцию целиком.

    Ловит: если бы слияние стало «overlay заменяет base на верхнем уровне»
    (частая регрессия при рефакторинге merge-функций — например замена
    рекурсивного ``deep_merge`` на ``{**base, **overlay}``), глобальный
    ``default_enabled=False`` молча терялся бы у КАЖДОГО процесса, чей рецепт
    вообще задаёт свою ``telemetry``-секцию — даже если рецепт не трогает
    ``default_enabled`` вовсе. Ровно та дыра, которую спрашивает спека.
    """

    def test_global_false_survives_metrics_only_override(self) -> None:
        """Глобально ``default_enabled=False``; per-process override трогает
        только ``metrics.fps`` → после ``deep_merge`` ``default_enabled``
        остаётся ``False``, а ``fps`` включена СВОИМ интервалом (точечный
        opt-in — критерий 3 приёмки, но через слитый dict, а не прямые kwargs)."""
        global_publish = TelemetryPublishConfig(default_enabled=False, default_interval_sec=2.0).to_dict()
        override = {"metrics": {"fps": {"enabled": True, "interval_sec": 0.5}}}

        merged = deep_merge(global_publish, override)
        cfg = TelemetryPublishConfig.from_dict(merged)

        assert cfg.default_enabled is False, "deep_merge потерял ключ, которого не было в overlay"
        assert cfg.resolve("fps") == (True, 0.5)
        assert cfg.resolve("effective_hz") == (False, 2.0)  # неперечисленная — по-прежнему молчит

    def test_explicit_per_process_default_enabled_overrides_global(self) -> None:
        """Если рецепт ЯВНО задаёт свой ``default_enabled`` — он побеждает
        (overlay побеждает при конфликте — контракт ``deep_merge`` вообще, не
        частный случай ``default_enabled``)."""
        global_publish = TelemetryPublishConfig(default_enabled=False).to_dict()
        override = {"default_enabled": True}

        merged = deep_merge(global_publish, override)
        cfg = TelemetryPublishConfig.from_dict(merged)

        assert cfg.default_enabled is True

    def test_global_off_plus_point_opt_in_inherits_merged_default_interval(self) -> None:
        """Глобально ``default_enabled=False``, ``default_interval_sec=4.5``;
        per-process точечно включает ``metrics.shm`` БЕЗ своего
        ``interval_sec`` → ``shm`` наследует ГЛОБАЛЬНЫЙ ``default_interval_sec``
        (критерий 3b приёмки, но конфиг собран слиянием, а не kwargs)."""
        global_publish = TelemetryPublishConfig(default_enabled=False, default_interval_sec=4.5).to_dict()
        override = {"metrics": {"shm": {"enabled": True}}}

        merged = deep_merge(global_publish, override)
        cfg = TelemetryPublishConfig.from_dict(merged)

        assert cfg.resolve("shm") == (True, 4.5)


class TestNoGateIsNotTheSameAsDefaultEnabledFalse:
    """Вопрос из шага 6 спеки: обратная совместимость ``_build_telemetry_gate``.

    Секции ``telemetry`` нет вовсе → ``_build_telemetry_gate()`` возвращает
    ``None`` («гейта нет», легаси-путь: все метрики публикуются каждый тик).
    Это НЕ то же самое, что ``default_enabled=False`` (гейт ЕСТЬ и активно
    молчит на всё). Разница не косметика: в ``_loop``
    (``process_heartbeat.py:165``) ``allowed_metrics = gate.due_metrics() if
    gate is not None else None``, и у ``build_worker_telemetry._ok()``
    (``heartbeat/telemetry.py``) ``None`` значит «всё разрешено», а пустое
    множество — «ничего не разрешено». Слияние этих двух состояний (например
    рефакторинг вида «``if not allowed_metrics: allowed_metrics = None``» —
    интуитивно смотрящийся безобидно, поскольку и пустой список, и None
    выглядят как falsy) сделало бы ``default_enabled=False`` тихим no-op.
    """

    def test_missing_telemetry_section_gate_is_none(self) -> None:
        hb = ProcessHeartbeat(_Services({}))
        assert hb._build_telemetry_gate() is None

    def test_telemetry_section_without_publish_is_also_no_gate(self) -> None:
        """Второй выход в ``None`` — отдельная ветка, и до этого теста её не было.

        ``_build_telemetry_gate`` отдаёт ``None`` ДВАЖДЫ: когда ключа ``telemetry``
        нет вовсе (сосед выше) и когда секция есть, а под-секции ``publish`` в ней
        нет — например конфиг задаёт только ``throttle``. Ветки разные, и сосед
        вторую не покрывает: он выходит на ПЕРВОМ страже (``telemetry`` не dict) и
        до второго не доходит.

        Измерено инъекцией 2026-08-18 (И5c): подмена ``publish is None`` на
        ``publish = {"default_enabled": False}`` не покрасила НИ ОДНОГО из 15
        тестов — гейт строился там, где по контракту обратной совместимости его
        быть не должно, и никто не возражал. Этот тест обязан покраснеть ровно на
        той подмене.
        """
        hb = ProcessHeartbeat(_Services({"telemetry": {"throttle": {"processes.**.state.fps": 1.0}}}))
        assert hb._build_telemetry_gate() is None

    def test_default_enabled_false_gate_exists_and_is_silent(self) -> None:
        assert gated_metrics(), "каталог метрик пуст — тест не докажет ничего про default_enabled"
        hb = ProcessHeartbeat(_Services({"telemetry": {"publish": {"default_enabled": False}}}))
        gate = hb._build_telemetry_gate()
        assert gate is not None
        assert gate.due_metrics(now=0.0) == set()

    def test_downstream_payload_is_opposite_not_merely_absent(self) -> None:
        """Прямое наблюдение PAYLOAD'а ``build_worker_telemetry`` — другой
        объектив, чем ``due_metrics()`` (который смотрит только на множество
        разрешённых имён, а не на то, что реально уезжает в дерево):
        ``allowed=None`` (гейта нет) публикует hz/latency/агрегат целиком;
        ``allowed=due_metrics()`` гейта с ``default_enabled=False`` публикует
        ТОЛЬКО ``status`` — те же данные, диаметрально разный результат."""
        workers = _one_worker()

        _, no_gate_payload = build_worker_telemetry(workers, "proc", None)
        assert no_gate_payload["workers"]["w0"]["effective_hz"] == 10.0
        assert no_gate_payload["state"] == {"fps": 10.0, "latency_ms": 5.0}

        hb = ProcessHeartbeat(_Services({"telemetry": {"publish": {"default_enabled": False}}}))
        gate = hb._build_telemetry_gate()
        assert gate is not None
        allowed = gate.due_metrics(now=0.0)
        result = build_worker_telemetry(workers, "proc", allowed)

        assert result is not None
        _, silenced_payload = result
        assert silenced_payload["workers"]["w0"] == {"status": "running"}
        assert "state" not in silenced_payload


class TestRoundTripPreservesDefaultEnabledFalse:
    """Вопрос из шага 6 спеки: round-trip ``to_dict``/``from_dict``.

    ``False`` — самый частый тип значения, теряемый в самодельных
    сериализаторах (``if value: …`` вместо ``if value is not None``).
    ``to_dict``/``from_dict`` здесь — тонкие обёртки над
    ``model_dump``/``model_validate``, но тест фиксирует КОНТРАКТ поля:
    следующая правка ``to_dict`` (например ``exclude_defaults=True`` ради
    компактности IPC-сообщения — ``default_enabled=True`` СОВПАДАЕТ со своим
    Pydantic-дефолтом и исчез бы из dict первым) обязана остаться совместимой
    именно с этим полем, а не только с ``default_interval_sec``/``metrics``,
    которые round-trip уже проверяет в ``test_telemetry_publish_config.py``.
    """

    def test_false_survives_to_dict_from_dict(self) -> None:
        original = TelemetryPublishConfig(
            default_enabled=False,
            default_interval_sec=3.0,
            metrics={"fps": MetricRule(enabled=True, interval_sec=0.2)},
        )

        as_dict = original.to_dict()
        assert as_dict["default_enabled"] is False  # ключ реально в dict, не только на объекте

        restored = TelemetryPublishConfig.from_dict(as_dict)
        assert restored.default_enabled is False
        assert restored.resolve("fps") == (True, 0.2)
        assert restored.resolve("shm") == (False, 3.0)  # неперечисленная молчит и после round-trip


class TestReplaceModeDropsDefaultEnabledSilently:
    """Блокер Б1 (ревью 2026-08-18): рантайм-правка в дефолтном режиме ``replace``
    молча СНИМАЕТ флип ``default_enabled=False``.

    Воспроизведено ревьюером на боевых ``ProcessHeartbeat._build_telemetry_gate`` +
    ``apply_telemetry_reconfigure`` (то же, что и у соседних тестов файла — прямые
    вызовы механизма, не дублёр)::

        boot:   telemetry.publish = {default_enabled: false, metrics: {fps: {enabled: true}}}
        затем:  apply_telemetry_reconfigure({"publish": {"metrics": {"fps": {...}}}})
                БЕЗ mode= (дефолт функции — "replace", тот же дефолт, что у команды
                при отсутствующем ``telemetry_mode``, ``builtin_commands.py:2279``)
        выход:  [boot]   default_enabled=False, due_metrics=['fps']            (1 имя)
                [после]  default_enabled=True,  due_metrics=['cycle_duration_ms',
                         'effective_hz', 'fps', 'latency_ms', 'shm']            (5 имён)

    Семантика ``replace`` сама по себе КОРРЕКТНА и документирована (Task 5.10.f —
    ``replace`` заменяет секцию целиком, находка ревью там же) — она не меняется этим
    тестом. Ломается посылка СОСЕДНЕЙ ручки (ADR-PM-039): флип, поставленный на boot
    ``default_enabled=False``, не переживает точечную правку другой метрики в режиме
    по умолчанию, потому что тело правки не обязано (и обычно не будет) повторять
    ``default_enabled`` — отсутствующий в dict ключ берёт схемный дефолт ``True``
    (``TelemetryPublishConfig.from_dict`` → ``model_validate``), а не текущее
    значение гейта. Голоса при этом нет: ``apply_telemetry_reconfigure`` возвращает
    ``{"publish": True}`` — успех без какого-либо намёка на то, что ``default_enabled``
    перевернулся.
    """

    def test_replace_without_default_enabled_key_reverts_the_flip(self) -> None:
        assert gated_metrics(), "каталог метрик пуст — тест не докажет ничего про default_enabled"
        hb = ProcessHeartbeat(
            _Services({"telemetry": {"publish": {"default_enabled": False, "metrics": {"fps": {"enabled": True}}}}})
        )
        # Мимикрируем ProcessHeartbeat.start() (process_heartbeat.py:97) — там гейт
        # собирается и присваивается атрибуту; _build_telemetry_gate() сама по себе
        # чистая фабрика и self._telemetry_gate не трогает.
        hb._telemetry_gate = hb._build_telemetry_gate()
        assert hb._telemetry_gate.due_metrics(now=0.0) == {"fps"}, "boot: только точечный opt-in разрешён"

        applied = apply_telemetry_reconfigure(
            {"publish": {"metrics": {"fps": {"enabled": True, "interval_sec": 0.5}}}},
            heartbeat=hb,
            # mode НЕ передан — воспроизводит отсутствие telemetry_mode в команде.
        )
        assert applied == {"publish": True}, "отказа нет — успех без следа перевёрнутого default_enabled"

        assert hb.current_telemetry_publish()["default_enabled"] is True, (
            "replace без default_enabled в теле вернул поле к схемному дефолту — "
            "флип, поставленный на boot, снят соседней правкой"
        )
        assert hb._telemetry_gate.due_metrics(now=0.0) == {
            "cycle_duration_ms",
            "effective_hz",
            "fps",
            "latency_ms",
            "shm",
        }, "каталог разрешённых расширился со ВСЕХ пяти фреймворковых имён — не только fps"

    def test_merge_mode_preserves_the_flip(self) -> None:
        """Контроль: тот же сценарий с явным ``telemetry_mode: merge`` держит флип.

        Без этого контроля предыдущий тест мог бы с тем же успехом ловить баг в
        ``deep_merge``/``resolve()`` вообще, а не именно в дефолте режима.
        """
        hb = ProcessHeartbeat(
            _Services({"telemetry": {"publish": {"default_enabled": False, "metrics": {"fps": {"enabled": True}}}}})
        )
        hb._telemetry_gate = hb._build_telemetry_gate()

        applied = apply_telemetry_reconfigure(
            {"publish": {"metrics": {"fps": {"enabled": True, "interval_sec": 0.5}}}},
            heartbeat=hb,
            mode="merge",
        )
        assert applied == {"publish": True}
        assert hb.current_telemetry_publish()["default_enabled"] is False, (
            "merge держит флип — регрессия здесь означала бы, что сломаны ОБА режима"
        )
        assert hb._telemetry_gate.due_metrics(now=0.0) == {"fps"}, "каталог разрешённых НЕ расширился"
