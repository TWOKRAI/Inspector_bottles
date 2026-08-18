# -*- coding: utf-8 -*-
"""Независимая приёмка: адресация секции ``telemetry.publish`` (RT-2, telemetry-stage6).

Написан НЕЗАВИСИМО от диффа/плана исправления — по критериям B1..B5, переданным
тестировщику текстом. Реализации фикса адресации на момент написания нет: часть
тестов ОБЯЗАНА быть красной (это и есть ожидаемый результат независимой приёмки).

Архитектурный факт (не баг), сообщённый в задании: конфиг доезжает до процесса
ДВУМЯ формами —
  - оркестратор получает свой конфиг ПЛОСКИМ: секция лежит в корне (``telemetry``);
  - дочерний процесс получает ВЕСЬ ``proc_dict``, поэтому его секции лежат под
    префиксом ``config.`` (то есть ``config.telemetry``).

``ProcessHeartbeat._build_telemetry_gate()`` изначально делал РОВНО один вызов —
``self._services.get_config("telemetry", None)`` — без попытки вложенного адреса;
``telemetry_targets(svc)`` (L0 для возврата рантайм-правок по сроку) делал ТОТ ЖЕ
плоский вызов тем же ключом.

Два способа проверки в этом файле:
  - фейк ``_AddressingServices`` (техника из памяти тестера,
    ``test-live-telemetry-gate-without-full-boot``) — быстрый, без полного боевого
    стенда, но ``get_config`` в нём ОБЯЗАН уметь точечную нотацию (dot-notation)
    ровно как настоящий читатель (``Config._traverse``) — плоский
    ``dict.get(key, default)`` без разбора точек НЕ отличил бы верную починку
    адресации от неверной (обнаружено ревью координатора 2026-08-18: первая
    редакция была плоской, и B1/B4 оставались красными даже после верного фикса
    исходников — тест охранял форму дублёра, а не свойство читателя);
  - настоящий ``ProcessConfigHandler`` (классы ``*OnRealHandler`` ниже) — не
    дублёр вовсе, конструируется поверх словаря формы боевого ``proc_dict``.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.process_module.configs.process_config_handler import (
    ProcessConfigHandler,
)
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    telemetry_targets,
)

# Секция publish, литералом (не выводится из проверяемого кода): default_enabled=false
# переворачивает белый список — метрика без явного правила в metrics выключена.
PUBLISH_SECTION: dict = {"default_enabled": False, "default_interval_sec": 1.0, "metrics": {}}


class _AddressingServices:
    """Минимальный дублёр ``IProcessServices`` для гейта телеметрии.

    ``get_config`` — ОБЩИЙ обход по точкам (dot-notation), СПИСАННЫЙ с контракта
    настоящего читателя (``Config._traverse``,
    ``multiprocess_framework/modules/config_module/core/config.py:191-199``):
    ключ режется по ``"."``, каждый сегмент — шаг вглубь вложенных dict, любой
    непройденный уровень → ``default``. **Важно: НЕ спец-случай под
    ``"config.telemetry"``** — обходится ЛЮБОЙ путь, иначе следующий ключ
    споткнётся о ту же дыру дублёра.

    Обнаружено ревью координатора (2026-08-18): прежняя версия была ПЛОСКИМ
    ``dict.get(key, default)`` без точечной нотации — из-за этого B1/B4
    оставались красными даже ПОСЛЕ верного исправления исходников (тест
    охранял форму дублёра, а не свойство читателя; «фейк доказывает сам
    себя» — не отличил бы верный фикс от неверного). Правильность самой
    точечной семантики проверена и на настоящем ``ProcessConfigHandler``
    (см. классы ``*OnRealHandler`` ниже) — дублёр здесь только экономит вызовы
    там, где реальный объект не нужен по существу проверяемого свойства.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        # (уровень, сообщение) — для B5: слышны ли оба исхода сборки гейта.
        self.logs: list[tuple[str, str]] = []

    def get_config(self, key: str, default: Any = None) -> Any:
        node: Any = self._config
        for part in key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def log_info(self, msg: object, *a: object, **k: object) -> None:
        self.logs.append(("info", str(msg)))

    def log_debug(self, msg: object, *a: object, **k: object) -> None:
        self.logs.append(("debug", str(msg)))

    def log_warning(self, msg: object, *a: object, **k: object) -> None:
        self.logs.append(("warning", str(msg)))


def _real_proc_dict(telemetry_section: dict) -> dict:
    """Словарь формы боевого ``proc_dict`` дочернего процесса — секция под ``config.``.

    Верхнеуровневые ключи и их набор — НЕ выдумка: список
    ``['class', 'config', 'managers', 'memory', 'priority', 'protected', 'queues',
    'restart_policy', 'workers']`` измерен координатором на настоящем
    ``proc_dicts["camera_0"]`` собранного рецепта ``webcam_sketch`` (см. сообщение
    ревью, 2026-08-18). Импорт прототипа из фреймворкового теста запрещён границей
    слоёв (``.sentrux/rules.toml``: ``multiprocess_framework/* -> multiprocess_prototype/*``
    заблокирован; тот же вывод — память тестера
    ``feedback_framework_tests_cannot_import_prototype``), поэтому форма
    воспроизведена руками, а не импортом ``multiprocess_prototype.backend.tests.
    test_build_characterization``.
    """
    return {
        "class": "multiprocess_prototype.backend.example.Module",
        "config": {"telemetry": telemetry_section},
        "managers": {},
        "memory": {},
        "priority": "normal",
        "protected": False,
        "queues": {},
        "restart_policy": {},
        "workers": {},
    }


class TestNestedChildAddressGate:
    """B1 — секция по вложенному адресу (форма дочернего процесса)."""

    def test_nested_config_telemetry_address_builds_gate_and_default_enabled_false_wins(self) -> None:
        """Секция лежит под ``{"config": {"telemetry": {"publish": ...}}}``.

        Ожидание B1: гейт СОБИРАЕТСЯ и действует — ``default_enabled: false``
        выключает метрику, для которой в ``metrics`` нет явного правила
        (``latency_ms`` здесь не перечислена вовсе).

        Как падает, если свойство отсутствует: ``_build_telemetry_gate()`` делает
        один плоский вызов ``get_config("telemetry", None)`` — по этому ключу в
        переданном словаре лежит только ``"config"``, "telemetry" на верхнем
        уровне нет → метод вернёт ``None`` → первый же ``assert gate is not None``
        упадёт ``AssertionError``.
        """
        cfg = {"config": {"telemetry": {"publish": dict(PUBLISH_SECTION)}}}
        services = _AddressingServices(cfg)
        hb = ProcessHeartbeat(services)

        gate = hb._build_telemetry_gate()

        assert gate is not None, "гейт не собрался по вложенному адресу config.telemetry"
        assert "latency_ms" not in gate.due_metrics(now=0.0)
        assert gate.due_metrics(now=0.0) == set()


class TestNestedChildAddressGateOnRealHandler:
    """B1 на НАСТОЯЩИХ объектах — не дублёре: ``ProcessConfigHandler`` поверх
    словаря формы боевого ``proc_dict`` (см. ``_real_proc_dict``).

    Обязательное требование проекта к фейк-гарнитуре: свойство, доказанное
    только дублёром, доказано наполовину. Этот тест — тот самый «ОДИН тест на
    настоящих объектах», которого не хватало (ревью координатора, 2026-08-18).
    """

    def test_real_process_config_handler_resolves_nested_address(self) -> None:
        """``ProcessConfigHandler.get_config("telemetry", None)`` (плоский, без
        точки) обязан вернуть ``None`` — сверено отдельно, чтобы не спутать
        «нашли по вложенному пути» с «нашли случайно по плоскому».

        Как падает, если свойство отсутствует: если адресация не почин(ен)а,
        ``hb._build_telemetry_gate()`` вернёт ``None`` на настоящем обработчике
        точно так же, как и на дублёре (B1) — ``assert gate is not None`` упадёт
        ``AssertionError``, и на этот раз — по вине исходников, не дублёра.
        """
        proc_dict = _real_proc_dict({"publish": dict(PUBLISH_SECTION)})
        handler = ProcessConfigHandler("camera_0", config=proc_dict)

        assert handler.get_config("telemetry", None) is None, (
            "плоский ключ 'telemetry' не обязан находить секцию, лежащую под config."
        )

        hb = ProcessHeartbeat(handler)
        gate = hb._build_telemetry_gate()

        assert gate is not None, "настоящий ProcessConfigHandler: гейт не собрался по вложенному адресу"
        assert gate.due_metrics(now=0.0) == set()


class TestFlatOrchestratorAddressGate:
    """B2 — та же секция плоско (форма оркестратора); починка B1 не смеет её сломать."""

    def test_flat_telemetry_address_builds_gate_and_default_enabled_false_wins(self) -> None:
        """Секция лежит под ``{"telemetry": {"publish": ...}}`` — плоско, в корне.

        Ожидание B2: гейт собирается ровно так же, как и по вложенному адресу
        (B1) — обе формы обязаны работать одновременно.

        Как падает, если свойство отсутствует: сегодня это УЖЕ работает (плоский
        адрес совпадает с единственным вызовом ``get_config("telemetry", None)``),
        поэтому тест зелёный характеризацией. Он ловит РЕГРЕСС: если починка
        вложенного адреса (B1) заменит логику так, что плоский путь перестанет
        резолвиться, здесь появится ``AssertionError`` на ``gate is not None``.
        """
        cfg = {"telemetry": {"publish": dict(PUBLISH_SECTION)}}
        services = _AddressingServices(cfg)
        hb = ProcessHeartbeat(services)

        gate = hb._build_telemetry_gate()

        assert gate is not None, "гейт не собрался по плоскому адресу telemetry (регресс формы оркестратора)"
        assert "latency_ms" not in gate.due_metrics(now=0.0)
        assert gate.due_metrics(now=0.0) == set()


class TestNoSectionAtEitherAddressIsAThirdState:
    """B3 — секции нет ни по одному адресу: третье состояние, не «всё выключено»."""

    def test_gate_is_none_not_empty_set_when_section_absent_at_both_addresses(self) -> None:
        """Пустой конфиг: ни ``telemetry`` в корне, ни ``config.telemetry``.

        Ожидание B3: гейт — ``None``. Это ОТЛИЧНО от «явно выключено»
        (``default_enabled=False`` → ``due_metrics() == set()``, см. B1/B2) —
        продакшн-код различает их буквально (``process_heartbeat.py``, тело
        ``_loop``): ``allowed_metrics = gate.due_metrics() if gate is not None
        else None``. ``None`` внизу означает «всё разрешено» (backward compat),
        а не «ничего не разрешено».

        Как падает, если свойство отсутствует: слияние ``None`` с «выключено»
        сделало бы ``allowed_metrics`` пустым множеством вместо ``None`` —
        второй ``assert`` (``allowed_metrics is None``) упал бы ``AssertionError``,
        и «нет конфига» стало бы неотличимо от «всё выключено» для потребителя.
        """
        services = _AddressingServices({})
        hb = ProcessHeartbeat(services)

        gate = hb._build_telemetry_gate()

        assert gate is None
        allowed_metrics = gate.due_metrics() if gate is not None else None
        assert allowed_metrics is None
        assert allowed_metrics != set()


class TestTelemetryTargetsReadsL0SameWayAsBoot:
    """B4 — ``telemetry_targets(svc)["telemetry_boot"]`` обязан читаться так же, как бут."""

    def test_telemetry_boot_is_not_none_and_matches_gate_source_at_nested_address(self) -> None:
        """При вложенном адресе (форма дочернего процесса) L0 не смеет быть ``None``
        и обязан содержать ТУ ЖЕ секцию, из которой собирается гейт.

        Докстринг ``telemetry_targets`` обещает: "``telemetry_boot`` читается ТЕМ
        ЖЕ способом, что и на старте" — иначе возврат правки по сроку (Task 5.10.f)
        применился бы не туда, куда применилась сама правка.

        Как падает, если свойство отсутствует (СЕГОДНЯ): ``telemetry_targets``
        делает тот же единственный плоский вызов ``get_config("telemetry", None)``,
        что и ``_build_telemetry_gate`` (см. B1) — по вложенному адресу это вернёт
        ``None``, и ``dict(raw) if isinstance(raw, dict) else None`` даст ``None``.
        ``assert targets["telemetry_boot"] is not None`` упадёт ``AssertionError``.
        """
        section = {"publish": dict(PUBLISH_SECTION)}
        cfg = {"config": {"telemetry": section}}
        services = _AddressingServices(cfg)

        targets = telemetry_targets(services)

        assert targets["telemetry_boot"] is not None, "L0 (telemetry_boot) не найден по вложенному адресу"
        assert targets["telemetry_boot"] == section


class TestTelemetryTargetsOnRealHandler:
    """B4 на НАСТОЯЩИХ объектах — тот же способ починки дублёра, что и у B1."""

    def test_real_process_config_handler_telemetry_boot_matches_gate_source(self) -> None:
        """``telemetry_targets(handler)["telemetry_boot"]`` на настоящем
        ``ProcessConfigHandler`` обязан быть той же секцией, из которой
        собирается гейт на ТОМ ЖЕ объекте — не на дублёре.

        Как падает, если свойство отсутствует: ``telemetry_targets`` делает
        плоский вызов ``get_config("telemetry", None)`` — на настоящем
        обработчике (см. предыдущий класс) это тоже ``None`` для секции,
        лежащей под ``config.`` → ``assert targets["telemetry_boot"] is not
        None`` упадёт ``AssertionError``.
        """
        section = {"publish": dict(PUBLISH_SECTION)}
        proc_dict = _real_proc_dict(section)
        handler = ProcessConfigHandler("camera_0", config=proc_dict)

        targets = telemetry_targets(handler)

        assert targets["telemetry_boot"] is not None, (
            "настоящий ProcessConfigHandler: L0 не найден по вложенному адресу"
        )
        assert targets["telemetry_boot"] == section


class TestBothGateOutcomesAreLogged:
    """B5 — оба исхода сборки гейта (включён/выключен) слышны в логе процесса."""

    def test_gate_built_outcome_leaves_a_log_entry(self) -> None:
        """Успешная сборка БЕЗ предупреждений (нет капа по тику, нет опечаток в
        именах метрик) сегодня не вызывает логгер вовсе — ``_warn_capped_metrics``
        и ``_warn_unknown_metrics`` оба no-op при пустой секции ``metrics`` и не
        заданном ``tick_sec``, а в самом теле ``_build_telemetry_gate`` после
        удачного ``TelemetryPublishConfig.from_dict`` записи в лог нет.

        Как падает, если свойство отсутствует: ``services.logs`` останется пустым
        после успешной сборки → ``assert services.logs`` упадёт ``AssertionError``
        — «включён» неотличимо от «метод вообще не вызывали».
        """
        cfg = {"telemetry": {"publish": {}}}
        services = _AddressingServices(cfg)
        hb = ProcessHeartbeat(services)

        gate = hb._build_telemetry_gate()

        assert gate is not None
        assert services.logs, "успешная сборка гейта не оставила ни одной записи в логе"

    def test_gate_disabled_outcome_leaves_a_log_entry_when_section_is_truly_absent(self) -> None:
        """Секции нет НИ по одному адресу → гейт ``None``. Сегодня обе ранние ветки
        возврата (``not isinstance(telemetry, dict)`` и ``publish is None``) не
        зовут логгер вовсе.

        Как падает, если свойство отсутствует: ``services.logs`` пуст после
        отказа от сборки → ``assert services.logs`` упадёт ``AssertionError`` —
        «выключен» неотличимо от «метод не звали».
        """
        services = _AddressingServices({})
        hb = ProcessHeartbeat(services)

        gate = hb._build_telemetry_gate()

        assert gate is None
        assert services.logs, "отказ от сборки гейта (секции нет вовсе) не оставил ни одной записи в логе"

    def test_disabled_log_is_present_and_names_both_addresses_when_section_exists_at_a_third_one(
        self,
    ) -> None:
        """Секция ЕСТЬ в конфиге, но НЕ по одному из двух адресов, которые умеет
        читатель (``read_process_config`` пробует ровно ``"telemetry"`` и
        ``"config.telemetry"``, см. ``observability_layers.py:971-996``) — здесь
        она лежит на ТРЕТЬЕМ, никем не проверяемом уровне
        (``config.nested.telemetry``, опечатка/лишняя вложенность). Это
        единственный конфиг, где ветка отказа ДЕЙСТВИТЕЛЬНО достижима после
        починки B1: конфиги на ``"telemetry"`` и на ``"config.telemetry"`` теперь
        оба уходят на успешную ветку (см. B1/B2), и прежний сценарий этого теста
        (секция под ``config.telemetry``) после исправления адресации СТАЛ
        успешным сценарием, а не отказным — инъекция координатора (2026-08-18)
        поймала это ровно так: снятие голоса на УСПЕХЕ, а не на отказе, роняло
        этот тест, хотя по названию он был про отказ.

        Двойная проверка одного диагностического свойства:
          1. отказ от сборки обязан оставить запись в логе (симметрично голосу
             на успехе — см. предыдущий тест);
          2. эта запись обязана НАЗВАТЬ ОБА адреса, которые проверил читатель
             (``"telemetry"`` и ``"config.telemetry"``), а не просто избегать
             одной плохой фразы — проверка «нет плохой фразы» одна осталась бы
             зелёной и на пустом/невнятном сообщении. Ложный вывод вместо факта
             («секции нет», хотя секция была, просто по другому адресу) уже
             уводил диагностику по ложному следу в этом проекте (см. память
             тестера, config.reload/ttl-адресация) — здесь тот же класс дефекта
             на другой двери, и сообщение обязано перечислять ФАКТ (где смотрели),
             а не строить вывод.

        Как падает, если свойство отсутствует: если голос на отказе снова
        замолчит — первый ``assert services.logs`` упадёт ``AssertionError``
        (как и раньше). Если голос звучит, но не называет оба адреса (например
        куце говорит «секция не найдена» без перечисления) — упадёт вторая
        пара ``assert`` на отсутствии ``"config.telemetry"`` либо отдельно
        стоящего ``"telemetry"``.
        """
        section = {"publish": dict(PUBLISH_SECTION)}
        cfg = {"config": {"nested": {"telemetry": section}}}
        services = _AddressingServices(cfg)
        hb = ProcessHeartbeat(services)

        gate = hb._build_telemetry_gate()

        assert gate is None, "секция на третьем, непроверяемом адресе не должна собрать гейт"
        assert services.logs, "отказ от сборки (секция на непроверяемом адресе) не оставил ни одной записи в логе"
        joined = " ".join(msg.lower() for _lvl, msg in services.logs)
        assert "config.telemetry" in joined, (
            f"лог не называет вложенный адрес config.telemetry, который проверил читатель: {services.logs}"
        )
        assert "telemetry" in joined.replace("config.telemetry", ""), (
            f"лог не называет плоский адрес telemetry ОТДЕЛЬНО от вложенного config.telemetry: {services.logs}"
        )
