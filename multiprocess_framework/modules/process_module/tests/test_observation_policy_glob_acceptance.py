# -*- coding: utf-8 -*-
"""Независимая приёмка Ф4 «политика одним glob» — ДО реализации Task 4.1.

Источник критериев: ``plans/observation-port/plan.md`` — §3 «Правила приёмки для
ВСЕХ фаз» (М1–М5) и раздел «Ф4 — политика одним glob» (Task 4.1 Acceptance
criteria). Тестеру ЗАПРЕЩЕНЫ: дифф Ф4, ``telemetry_publish_config.py`` (новая
редакция), ``observability_reload.py`` (дифф), ``_telemetry_controls.py``
(дифф), авторские тесты Ф4 — этот файл писан ДО того, как что-либо из
перечисленного появилось в дереве (worktree на коммите до реализации).

Сегодняшний механизм (проверено чтением, не заявлено): ``TelemetryGate.due_metrics()``
резолвит ОДНО имя метрики ОДНИМ множеством ``allowed``, разделяемым МЕЖДУ
``build_worker_telemetry`` (фреймворковая плоскость ``processes.<P>.state.<имя>``)
и ``build_plugin_levels`` (плоскость порта ``processes.<P>.state.plugins.<w>.<имя>``)
— см. ``ProcessHeartbeat._loop`` (``heartbeat/process_heartbeat.py:195-213``).
``TelemetryPublishConfig.resolve(metric_name)`` смотрит ключ ``metrics`` ТОЧНЫМ
совпадением по суффиксу (``self.metrics.get(metric_name)``) — пути в нём нет
вовсе (докстринг ``heartbeat/telemetry.py:603-606`` говорит об этом прямо: «Glob
по пути — язык Ф4, здесь его нет»). Отсюда все тесты ниже бьют в ОДНУ и ту же
дыру: сегодня НЕВОЗМОЖНО адресовать правило одной плоскости, не задев другую,
потому что решение принимается по ИМЕНИ, а не по ПУТИ.

Тесты используют РЕАЛЬНЫЕ объекты (``TelemetryPublishConfig``, ``TelemetryGate``,
``build_worker_telemetry``, ``build_plugin_levels``, ``observability_verified``)
и фейковые часы (не ``time.sleep`` — ничего не блокирует, join-дедлайн не нужен).

Два теста (``test_provenance_...``) явно помечены как ГИПОТЕЗА тестера о форме
будущего API — план не называет ни имени функции, ни литералов провенанса
дословно. Расшифровка — в финальном отчёте тестера, раздел «где критерий
оказался неоднозначным».

--------------------------------------------------------------------------
ПРАВКИ ИСПОЛНИТЕЛЯ (задача 4.1). Изменены ТОЛЬКО точки входа — функция,
которую тест зовёт, и адрес ключа конфига. Ни одно заявленное свойство не
ослаблено, ни один литерал ожидания не заменён вычислением из кода. Что
поменялось и почему:

1. **Адрес правил.** Тестер положил glob-ключи внутрь ``telemetry.publish.metrics``
   (его модель будущего API). План связывает исполнителя иначе (Шаг 1: ключи
   порта — в секцию ``observability``, пятая дверь не заводится), поэтому
   правила переехали в ``observability.observation.rules``
   (:class:`ObservationPolicyConfig`), а ``telemetry.publish`` осталась
   ИМЕНОВАННЫМ легаси-источником той же сборки. Литералы правил
   (``processes.*.state.plugins.*.fps``, ``1.0``) — те же.
2. **Два решения вместо одного.** Тестер звал ``gate.due_metrics(...)`` один раз
   и кормил ОДНО множество обоим сборщикам. Ровно эта общность и была дефектом,
   который фаза чинит: решение по имени не может адресовать плоскость. Тесты
   зовут ``due_metrics()`` для фреймворковой плоскости и
   ``due_plugin_metrics({писатель: имена})`` для поддерева порта. Счётчики
   тиков и их ожидаемые значения (5, 2, 3, 1) не тронуты.
3. **Тест №5 заменён.** Тестер сам пометил его черновиком: он сторожил
   ОТСУТСТВИЕ (``observability_provenance`` не принимает ``heartbeat=``), то
   есть свойство, которое исчезает от любой правки сигнатуры и ничего не
   говорит о провенансе. На его месте — настоящая проверка AC3: три РАЗНЫХ
   литерала источника в ОДНОМ тесте.
--------------------------------------------------------------------------
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.configs.observation_policy import (
    SOURCE_RULE,
    SOURCE_SUBTREE_DEFAULT,
    SOURCE_WHITELIST,
    ObservationPolicy,
    ObservationPolicyConfig,
)
from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
    TelemetryPublishConfig,
)
from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    TelemetryGate,
    build_plugin_levels,
    build_worker_telemetry,
)
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    observability_verified,
)

#: Имя процесса — сегмент пути. Литерал теста, а не значение из кода.
PROC = "cam1"


def _gate(clock, publish: dict, observation: dict | None = None) -> TelemetryGate:
    """Гейт из легаси-секции + политики порта — как его собирает боевой heartbeat."""
    legacy = TelemetryPublishConfig.from_dict(publish)
    policy = ObservationPolicy(ObservationPolicyConfig.from_dict(observation), legacy)
    return TelemetryGate(legacy, clock=clock, policy=policy, process=PROC)


class _FakeClock:
    """Часы под управлением теста — зависимость объекта, не глобальный monotonic."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class TestGlobRuleAddressesOnlyItsOwnSubtree:
    """AC Ф4/4.1 #1: ``processes.*.state.plugins.*.fps: 1.0`` душит плагинные fps
    и не трогает фреймворковый ``state.fps`` (литералы обоих счётчиков в тесте).

    Кванторный критерий (§3, правило 4) — окно из 5 тиков (t=0, .25, .5, .75, 1.0),
    не один. Инъекция рода 2 «матчер всегда True» ломает вторую половину assert
    (плагинный fps перестал бы зажиматься — plugin_ticks поехал бы к 5); инъекция
    «матчер всегда False» ломает первую (framework_ticks упал бы к 0/1).
    """

    def test_plugin_fps_is_throttled_framework_fps_is_not(self) -> None:
        clock = _FakeClock(0.0)
        # Дефолтный интервал (не тронут правилом) — 0.25с, отдельное правило
        # плоскости порта — 1.0с. Оба значения точны в двоичной арифметике
        # (0.25 / 1.0), дрейфа округления при накоплении next_due нет.
        gate = _gate(
            clock,
            publish={"default_interval_sec": 0.25},
            observation={"rules": {"processes.*.state.plugins.*.fps": {"interval_sec": 1.0}}},
        )
        workers = {"w1": {"status": "running", "effective_hz": 30.0}}

        framework_ticks = 0
        plugin_ticks = 0
        for i in range(5):  # t = 0, 0.25, 0.5, 0.75, 1.0
            clock.now = i * 0.25
            allowed = gate.due_metrics(now=clock.now)
            allowed_levels = gate.due_plugin_metrics({"capture": ["fps"]}, now=clock.now)

            fw = build_worker_telemetry(workers, PROC, allowed)
            if fw is not None and "fps" in fw[1].get("state", {}):
                framework_ticks += 1

            levels = build_plugin_levels({"capture": {"fps": 42.0}}, allowed_levels)
            if "fps" in levels.get("plugins", {}).get("capture", {}):
                plugin_ticks += 1

        assert framework_ticks == 5, (
            f"фреймворковый state.fps опубликован {framework_ticks} раз из 5 тиков "
            "(дефолтный интервал 0.25с должен пропускать каждый тик)"
        )
        assert plugin_ticks == 2, (
            f"плагинный plugins.capture.fps опубликован {plugin_ticks} раз из 5 тиков — "
            "контракт Ф4 требует 2 (t=0 и t=1.0 при интервале правила 1.0с); сегодня "
            "правило по пути не резолвится вовсе, и оба счётчика идут ВМЕСТЕ "
            "(due_metrics отдаёт одно множество на оба сборщика)"
        )


class TestNewPluginMetricNeedsZeroConfigEdits:
    """M1 дословно (§3): новая метрика плагина едет в дерево при НУЛЕВЫХ правках
    конфига — якорь «до»/«после» в одном тесте; вторая половина пары (М1,
    обязательна) — та же метрика во фреймворковой плоскости не публикуется.

    Без deny-by-default вне поддерева порта («вариант «в», решение владельца
    2026-08-25) эта пара была бы зелена и при полном развороте дерева — секция
    §3, пункт 3, требует ЯКОРЬ СУЩЕСТВОВАНИЯ, поэтому ``default_enabled=False``
    здесь не украшение, а условие небанальности проверки.
    """

    def test_new_metric_appears_under_port_default_rule_framework_plane_silent(self) -> None:
        clock = _FakeClock(0.0)
        # Белый список — ничего явного про "capture_fps" не написано. Единственная
        # причина, по которой метрика вообще может проехать, — дефолтное правило
        # поддерева порта (Ф4, вариант «в»). Ноль правок конфига под НОВОЕ имя.
        gate = _gate(clock, publish={"default_enabled": False, "default_interval_sec": 1.0})
        # Фреймворковой плоскости имя предъявлено ЯВНО (`extra`) — и всё равно
        # обязано быть отсеяно белым списком: переворот на неё не распространяется.
        allowed = gate.due_metrics(now=0.0, extra=["capture_fps"])

        # Якорь "до": лист не объявлен писателем — его нет.
        before = build_plugin_levels({}, gate.due_plugin_metrics({}, now=0.0))
        assert before == {}, before

        # Якорь "после": писатель объявил лист — по контракту М1 он ОБЯЗАН
        # появиться, литералом 42.0, без единой правки конфига/фреймворка.
        allowed_levels = gate.due_plugin_metrics({"capture": ["capture_fps"]}, now=0.0)
        after = build_plugin_levels({"capture": {"capture_fps": 42.0}}, allowed_levels)
        assert after == {"plugins": {"capture": {"capture_fps": 42.0}}}, (
            f"новая метрика плагина не доехала до дерева: {after!r} — сегодня "
            "плоскости deny-by-default вне поддерева порта не существует, "
            "'capture_fps' резолвится глобальным default_enabled=False"
        )

        # Вторая половина пары: то же имя во фреймворковой плоскости не публикуется
        # ни одним сборщиком фреймворка (build_worker_telemetry знает только
        # фиксированную четвёрку имён — эта проверка гарантирует, что она и
        # впредь не станет каналом утечки прикладных имён в state.<имя>).
        fw = build_worker_telemetry({"w1": {"status": "running", "effective_hz": 10.0}}, PROC, allowed)
        assert fw is None or "capture_fps" not in fw[1].get("state", {}), fw
        assert "capture_fps" not in allowed, (
            f"имя плагина прошло гейт ФРЕЙМВОРКОВОЙ плоскости при default_enabled=false: {sorted(allowed)} "
            "— переворот варианта «в» обязан жить только в поддереве порта"
        )


class TestDefaultSubtreeFrequencyIsObservable:
    """AC Ф4/4.1 #4: дефолтная частота дефолтного правила наблюдаема ЗНАЧЕНИЕМ —
    правка этого значения меняет наблюдаемый темп публикации (кванторный, ≥2
    тика). Инъекция «частота дефолтного правила игнорируется» обязана краснеть.
    """

    @staticmethod
    def _plugin_ticks(default_subtree_interval: float) -> int:
        clock = _FakeClock(0.0)
        gate = _gate(
            clock,
            publish={"default_enabled": False, "default_interval_sec": 1.0},
            # Дефолтное правило поддерева порта: частота — ЯВНОЕ значение, не
            # подразумеваемая (§3, требование владельца).
            observation={"subtree_enabled": True, "subtree_interval_sec": default_subtree_interval},
        )
        count = 0
        for t in (0.0, 1.0, 2.0):
            clock.now = t
            allowed_levels = gate.due_plugin_metrics({"capture": ["capture_fps"]}, now=t)
            levels = build_plugin_levels({"capture": {"capture_fps": 1.0}}, allowed_levels)
            if "capture_fps" in levels.get("plugins", {}).get("capture", {}):
                count += 1
        return count

    def test_changing_default_rule_frequency_changes_observed_rate(self) -> None:
        fast = self._plugin_ticks(default_subtree_interval=0.5)  # чаще шага тиков (1.0с) → на каждом
        slow = self._plugin_ticks(default_subtree_interval=5.0)  # реже окна (3с) → один раз

        assert fast == 3, f"частая частота (0.5с): {fast} публикаций из 3 тиков, ожидалось 3"
        assert slow == 1, f"редкая частота (5.0с): {slow} публикаций из 3 тиков, ожидалось 1"
        assert fast != slow, (
            "правка значения дефолтной частоты поддерева НЕ меняет наблюдаемый темп "
            "публикации — предохранитель, который нельзя измерить, предохранителем не является"
        )


class TestPortKnobRegistersWithConfigReloadVerified:
    """AC Ф4/4.1 #6: правка ручки порта через ``config_reload_verified`` даёт
    ``confirmed`` при ``checked > 0``. Инъекция «readback порта не
    зарегистрирован» даёт ``unverifiable`` при ``checked=0`` — тест ОБЯЗАН
    трактовать это как красное, а не как норму (буквальное указание AC).

    Прецедент в этом же файле — секции ``events``/``flight`` (Ф4/4.1, Ф5/5.1
    по докстрингу ``observability_verified``) уже зарегистрированы явно строчками
    ``for section_key in (EVENTS_SECTION_KEY, FLIGHT_SECTION_KEY): ...``;
    ``TELEMETRY_KEY`` в этом списке НЕТ — секция ``telemetry`` только СНИМАЕТСЯ
    ``unknown_section_keys`` (чтобы не быть ложной опечаткой), но никогда не
    добавляется обратно в ``expected``, поэтому любой telemetry-путь до Ф4 был
    ``unverifiable`` при ``checked=0``. Задача 4.1 добавляет туда третьей
    секцию ``observation``.
    """

    def test_port_knob_is_confirmed_with_checked_above_zero(self) -> None:
        requested = {"observation": {"rules": {"processes.*.state.plugins.*.fps": {"interval_sec": 1.0}}}}
        # "Действующее" — readback ЖИВОЙ политики, а не рукописное эхо запроса.
        # Собирать эхо руками значило бы сверять две копии одной модели: тест
        # прошёл бы и при политике, которая правку не приняла.
        policy = ObservationPolicy(
            ObservationPolicyConfig.from_dict(requested["observation"]),
            TelemetryPublishConfig.from_dict({}),
        )
        effective = {"observation": policy.effective_view()}

        result = observability_verified(requested, effective)

        assert result["checked"] > 0, (
            f"checked={result['checked']!r}, verdict={result['verdict']!r} — readback порта "
            "не зарегистрирован в config_reload_verified (TELEMETRY_KEY не заведён в "
            "expected рядом с events/flight), unverifiable читается КАК НОРМА вместо красного"
        )
        assert result["verdict"] == "confirmed", result


class TestProvenanceNamesThreeSources:
    """AC Ф4/4.1 #3: провенанс различает ТРИ источника решения — дефолт поддерева
    порта / белый список легаси-секции / явное правило оператора — тремя разными
    литералами в ОДНОМ тесте.

    Черновик тестера на этом месте сторожил ОТСУТСТВИЕ (``observability_provenance``
    не принимает ``heartbeat=``) и был помечен им же как гипотеза; он покраснел бы
    от любой правки сигнатуры и ничего не сказал бы о провенансе. Заменён на
    проверку самого критерия — по решению исполнителя, с точкой входа
    ``ObservationPolicy.resolve`` (провенанс считается ТЕМ ЖЕ резолвом, которым
    принимается решение, — свой пересчёт показывал бы согласие всегда).

    Один тест, а не три: критерий про РАЗЛИЧЕНИЕ, и различить можно только рядом.
    Литералы источников — из контракта модуля, но сравниваются с тремя РАЗНЫМИ
    значениями, поэтому подмена любого из них на общий литерал красит тест.
    """

    def test_three_distinct_source_literals_in_one_resolve_set(self) -> None:
        policy = ObservationPolicy(
            ObservationPolicyConfig.from_dict(
                {"rules": {"processes.*.state.plugins.capture.drops": {"interval_sec": 0.5}}}
            ),
            TelemetryPublishConfig.from_dict(
                {"default_enabled": False, "default_interval_sec": 2.0, "metrics": {"fps": {"interval_sec": 3.0}}}
            ),
        )

        by_rule = policy.resolve(f"processes.{PROC}.state.plugins.capture.drops")
        by_subtree = policy.resolve(f"processes.{PROC}.state.plugins.capture.anything_new")
        by_whitelist = policy.resolve(f"processes.{PROC}.state.fps")

        assert by_rule.source == SOURCE_RULE, by_rule
        assert by_rule.interval_sec == 0.5, by_rule
        assert by_subtree.source == SOURCE_SUBTREE_DEFAULT, by_subtree
        assert by_subtree.interval_sec == 1.0, by_subtree
        assert by_whitelist.source == SOURCE_WHITELIST, by_whitelist
        assert by_whitelist.interval_sec == 3.0, by_whitelist

        sources = {by_rule.source, by_subtree.source, by_whitelist.source}
        assert len(sources) == 3, (
            f"три решения назвали {len(sources)} источник(а) вместо трёх: {sorted(sources)} — "
            "оператор не отличит «разрешено дефолтом» от «разрешено руками»"
        )

        # Якорь существования у отрицательного соседа: имя ВНЕ белого списка и вне
        # поддерева порта молчит — переворот варианта «в» не течёт на плоскость
        # фреймворка. Без этой половины тест был бы зелен при развороте дерева.
        outside = policy.resolve(f"processes.{PROC}.state.effective_hz")
        assert outside.source == SOURCE_WHITELIST, outside
        assert outside.enabled is False, outside
