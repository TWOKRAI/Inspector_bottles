# -*- coding: utf-8 -*-
"""Авторские тесты Task 2.1 — ВНУТРЕННИЕ опасности механизма и паритет конфига.

Независимая приёмка живёт рядом (``test_f2_numbers_policy_acceptance.py``,
9 критериев, написана ДО реализации и без доступа к ней). Эти тесты её НЕ
заменяют и не повторяют: правило проекта разводит три роли по трём классам
дефектов, и здесь закрыт класс автора — гонки, порядок, разъезд двух копий
одного механизма и та половина критерия 7, которую тестер честно назвал
незакрытой (паритет решений на боевом конфиге прототипа; он видел только
громкий голос).

**Почему паритет — главный тест этого файла.** Смена смысла ``stats.enabled``
— единственная смена поведения существующего ключа во всей фазе (план §11 п.1),
и у неё есть НЕОЧЕВИДНЫЙ сосед, найденный при реализации: боевой
``telemetry.publish`` прототипа работает белым списком
(``default_enabled: false``), а его правила суффиксные (``**.<лист>``). Пусти
эту секцию в решение по ЧИСЛАМ — и зонтик ``**`` ответил бы ``enabled=False`` на
каждую метрику каждого процесса: плоскость чисел умерла бы молча в момент
попадания задачи в main, при девяти зелёных приёмочных тестах (они строят
политику с ``legacy=None``). Тест ниже берёт НАСТОЯЩИЙ файл конфига, а не его
пересказ, и держит контроль, доказывающий, что он не зелен вхолостую.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import pytest
import yaml

from ...process_module.configs.observability_config import expand_observability
from ...process_module.configs.observation_policy import (
    SOURCE_SUBTREE_DEFAULT,
    STATS_SUBTREE_PATTERN,
    ObservationPolicy,
    ObservationPolicyConfig,
)
from ...process_module.configs.telemetry_publish_config import MetricRule, TelemetryPublishConfig
from ...process_module.heartbeat.telemetry import TelemetryGate
from .. import StatsManager
from ..observation.numbers_gate import NumbersGate, PathSchedule, stats_metric_path
from ..observation.observation_manager import ObservationManager

#: Боевой конфиг прототипа — ЧИТАЕТСЯ, а не пересказывается. Пересказ согласился
#: бы сам с собой: правку `default_enabled` в файле такой тест не заметил бы.
PROTOTYPE_CONFIG = Path(__file__).resolve().parents[4] / "multiprocess_prototype" / "backend" / "config" / "system.yaml"

#: Реальные имена метрик, встречающиеся в вызовах ``record_metric``/``increment``
#: фреймворка и прототипа (грепом по дереву, тесты исключены). Литералы, а не
#: выражение от кода: перечень, вычисленный тем же обходом, что и предмет,
#: согласился бы с любым ответом, включая пустой.
REAL_METRIC_NAMES: Tuple[str, ...] = (
    "capture.frames",
    "capture.drops",
    "plugin.frames",
    "plugin.frames_total",
    "defects_total",
    "topology.apply",
    "dispatcher.dispatch.errors",
    "command_manager.command.execution.success",
)


def _prototype_sections() -> Tuple[Any, Any]:
    """``(секция observability, секция telemetry.publish)`` боевого конфига."""
    if not PROTOTYPE_CONFIG.is_file():
        pytest.skip(f"конфиг прототипа не найден: {PROTOTYPE_CONFIG}")
    data = yaml.safe_load(PROTOTYPE_CONFIG.read_text(encoding="utf-8")) or {}
    return data.get("observability") or {}, ((data.get("telemetry") or {}).get("publish"))


def _prototype_policy() -> ObservationPolicy:
    """Политика, собранная ДОСЛОВНО так, как её собирает ``ProcessHeartbeat``.

    ``observation`` в конфиге прототипа сегодня нет вовсе → дефолты L0; легаси —
    настоящая секция ``telemetry.publish``. Отклонись сборка от боевой хоть в
    одном аргументе — тест доказывал бы харнесс, а не систему.
    """
    observability, publish = _prototype_sections()
    legacy = TelemetryPublishConfig.from_dict(publish) if publish is not None else None
    config = ObservationPolicyConfig.from_dict(observability.get("observation"))
    return ObservationPolicy(config, legacy)


# ====================================================================== #
#  Паритет на БОЕВОМ конфиге — вторая половина критерия 7.               #
# ====================================================================== #


class TestParityOnTheProductionConfig:
    """Числа боевого процесса едут ПОСЛЕ правки ровно так же, как до неё."""

    def test_the_control_is_alive_legacy_still_denies_an_unknown_leaf(self) -> None:
        """КОНТРОЛЬ, без которого весь класс зелен вхолостую.

        Подтверждающий ноль засчитывается только в паре с контролем, дающим
        ненулевое: если бы легаси-секция прототипа не была deny-by-default, тесты
        ниже проходили бы и с ПОЛНОСТЬЮ сломанным разведением плоскостей. Здесь
        доказано, что на УРОВНЯХ она реально запрещает незнакомый лист, — то
        есть опасность, от которой защищается следующий тест, существует.
        """
        _, publish = _prototype_sections()
        assert publish is not None, "боевой конфиг перестал нести telemetry.publish — посылка теста устарела"
        assert publish.get("default_enabled") is False, (
            "посылка теста: белый список прототипа. Если ключ сменился, "
            f"переписать нужно ТЕСТ, а не молчать: {publish!r}"
        )
        policy = _prototype_policy()
        decision = policy.resolve("processes.camera_0.state.no_such_leaf", count=False)
        assert decision.enabled is False, (
            "контроль мёртв: легаси-секция обязана запрещать незнакомый лист на плоскости "
            f"УРОВНЕЙ, иначе паритетный тест ниже ничего не доказывает — получено {decision!r}"
        )

    @pytest.mark.parametrize("metric", REAL_METRIC_NAMES)
    def test_every_real_metric_name_survives_the_legacy_deny_by_default(self, metric: str) -> None:
        """Восемь боевых имён на боевом конфиге — ВСЕ едут, все без троттла.

        Это и есть паритет: до Ф2 числа гейта не знали вовсе (``record_metric``
        шёл прямо в окно), и после Ф2 обязаны ехать так же. Красным тест
        становится ровно тогда, когда легаси-зонтик или дефолт поддерева
        начинают отвечать за плоскость чисел.
        """
        decision = _prototype_policy().resolve(stats_metric_path("camera_0", metric), count=False)
        assert decision.enabled is True, f"{metric}: число перестало собираться на боевом конфиге — {decision!r}"
        assert decision.interval_sec == 0.0, f"{metric}: у чисел появился троттл, которого до Ф2 не было — {decision!r}"
        assert decision.source == SOURCE_SUBTREE_DEFAULT and decision.pattern == STATS_SUBTREE_PATTERN, (
            f"{metric}: решение принял НЕ дефолт поддерева чисел — {decision!r}"
        )

    def test_a_number_named_fps_does_not_inherit_the_levels_throttle(self) -> None:
        """Точный локализатор коллизии имён между плоскостями.

        ``fps`` стоит в белом списке ``telemetry.publish`` прототипа с
        ``interval_sec: 1.0`` — это правило про УРОВЕНЬ. Суффиксная форма
        ``**.fps`` совпадает и с путём ЧИСЛА, поэтому без разведения плоскостей
        метрика ``fps``, записанная как число, молча получила бы предохранитель
        частоты чужой плоскости: суммы за секунду складывались бы из одного
        слагаемого. Пара: уровень при этом обязан троттл сохранить.
        """
        policy = _prototype_policy()
        as_number = policy.resolve(stats_metric_path("camera_0", "fps"), count=False)
        as_level = policy.resolve("processes.camera_0.state.fps", count=False)
        assert as_number.enabled is True and as_number.interval_sec == 0.0, (
            f"число fps унаследовало правило плоскости уровней: {as_number!r}"
        )
        assert as_level.enabled is True and as_level.interval_sec == 1.0, (
            f"пара: у УРОВНЯ fps правило прототипа обязано остаться в силе — {as_level!r}"
        )

    def test_todays_config_keeps_the_plane_and_the_log_channel(self) -> None:
        """``stats.enabled: true`` (строка 149 боевого файла) → всё как было.

        Тестер прямо назвал, что на ЭТОМ файле смена смысла тривиально незаметна
        (true→true), — поэтому здесь она и не проверяется: проверяется, что
        сегодняшний файл после правки даёт прежние два «да».
        """
        observability, _ = _prototype_sections()
        assert (observability.get("stats") or {}).get("enabled") is True, (
            "посылка теста устарела: боевой конфиг больше не несёт stats.enabled: true"
        )
        expanded = expand_observability(observability)["stats"]
        assert expanded["enabled"] is True, "плоскость чисел выключилась на конфиге, который её не выключал"
        assert expanded["enable_logging"] is True, (
            "лог-канал снапшотов погас на конфиге, который его не гасил — "
            "log_snapshots обязан подставить прежний дефолт True"
        )

    def test_the_old_false_variant_moves_only_the_plane_not_the_log_channel(self) -> None:
        """Вариант со СТАРЫМ ``false`` — тот, которого в файле нет и ради которого тест.

        Смысл ключа сменился, и здесь это зафиксировано числом, а не намерением:
        старый конфиг просил «не логировать снапшоты», а получает «не собирать
        числа». Лог-канал при этом остаётся ВКЛЮЧЁННЫМ — то есть старый конфиг
        меняет поведение в ОБЕ стороны, и обе названы. Голос об этом сторожит
        приёмочный ``test_c7``.
        """
        observability, _ = _prototype_sections()
        old_style = {**observability, "stats": {**(observability.get("stats") or {}), "enabled": False}}
        expanded = expand_observability(old_style)["stats"]
        assert expanded["enabled"] is False, "плоскость обязана выключиться — это и есть новый смысл ключа"
        assert expanded["enable_logging"] is True, (
            "лог-канал больше НЕ управляется ключом enabled: он остаётся включённым, "
            "пока не сказано log_snapshots: false. Красный здесь означает, что смена "
            f"смысла сделана наполовину — {expanded!r}"
        )


# ====================================================================== #
#  Расписание — ОДИН класс на две плоскости, а не копия.                 #
# ====================================================================== #


class TestTheScheduleIsOneClassNotACopy:
    """План требует у чисел ТОТ ЖЕ класс расписания, что у уровней."""

    def test_both_planes_hold_the_same_schedule_type(self) -> None:
        """Структурный сторож: вторая машина расписания рядом с первой — красный.

        Проверяется тип ОБОИХ держателей, а не наличие метода: копия с тем же
        интерфейсом прошла бы duck-typed проверку и разъехалась бы с оригиналом
        на первой же правке — ровно тот дефект, который фаза разбирает.
        """
        levels_gate = TelemetryGate(TelemetryPublishConfig(), process="cam1")
        numbers_gate = NumbersGate(None, "cam1")
        assert type(levels_gate._schedule) is PathSchedule, "у уровней своё расписание, не общий класс"
        assert type(numbers_gate._schedule) is PathSchedule, "у чисел своё расписание, не общий класс"

    def test_the_next_due_back_compat_view_is_live_not_a_snapshot(self) -> None:
        """``TelemetryGate._next_due`` пережил вынос состояния и остался ЖИВЫМ.

        Три существующих набора тестов читают этот адрес и сравнивают снимки
        до/после. Отдай он пустую копию — они остались бы зелёными на пустом
        словаре, то есть сторож изоляции расписания перестал бы сторожить,
        не покраснев ни разу.
        """
        gate = TelemetryGate(TelemetryPublishConfig(default_enabled=True, default_interval_sec=5.0), process="cam1")
        assert gate._next_due == {}
        gate.due_metrics(now=100.0, extra=["probe_leaf"])
        assert gate._next_due, "таблица сроков не наполнилась — вид отвязался от живого расписания"
        assert gate._next_due is gate._schedule.table, "вид отдаёт КОПИЮ: сравнение снимков перестанет что-либо ловить"


# ====================================================================== #
#  Состояние гейта при смене политики.                                   #
# ====================================================================== #


class TestGateStateAcrossPolicySwap:
    def test_counters_survive_the_swap_and_the_schedule_does_not(self) -> None:
        """Счётчики переживают пересборку, расписание — нет. Обе половины разом.

        Первая: ``config.reload`` соседней ручки пересобирает политику, и
        обнуляйся счёт вместе с ней — «сколько срезано правилом» отвечало бы
        «ноль» после каждой чужой правки, то есть единственное число про работу
        правила было бы вечно свежим нулём.

        Вторая: сроки посчитаны по СТАРЫМ интервалам и после смены правил
        означают уже не то — расписание чистится, дословно как у уровней
        (у нового ``TelemetryGate`` ``_next_due`` пустой).
        """
        deny = ObservationPolicy(ObservationPolicyConfig(rules={"processes.cam1.stats.x": MetricRule(enabled=False)}))
        throttle = ObservationPolicy(
            ObservationPolicyConfig(rules={"processes.cam1.stats.y": MetricRule(interval_sec=1000.0)})
        )
        gate = NumbersGate(deny, "cam1")
        assert gate.allow("x") is False
        assert gate.allow("y") is True  # правила про y ещё нет — дефолт поддерева
        assert gate.dropped_by_metric() == {"x": 1}

        gate.set_policy(throttle)
        assert gate.allow("y") is True, "после смены политики срок y обязан начаться заново"
        assert gate.allow("y") is False, "второй вызов внутри интервала 1000 с обязан быть придержан"
        assert gate.dropped_by_metric() == {"x": 1}, (
            f"счёт срезанных правилом обнулился чужой пересборкой: {gate.dropped_by_metric()!r}"
        )
        assert gate.throttled_by_metric() == {"y": 1}, (
            f"придержанное считается отдельно: {gate.throttled_by_metric()!r}"
        )

    def test_setting_the_same_policy_object_does_not_wipe_the_schedule(self) -> None:
        """Повторная доставка ТОЙ ЖЕ политики — не пересборка.

        ``apply_observation_policy`` зовётся на КАЖДЫЙ ``config.reload``, в том
        числе тот, что менял ``log_level`` и про порт не сказал ни слова. Не
        различай гейт «та же ссылка», и соседняя правка молча снимала бы
        частотный предохранитель чисел — ровно тот дефект, который у уровней уже
        закрыт сверкой содержимого политики.
        """
        policy = ObservationPolicy(
            ObservationPolicyConfig(rules={"processes.cam1.stats.z": MetricRule(interval_sec=1000.0)})
        )
        gate = NumbersGate(policy, "cam1")
        assert gate.allow("z") is True
        gate.set_policy(policy)
        assert gate.allow("z") is False, "повторная доставка той же политики сбросила расписание"


# ====================================================================== #
#  Гонка: политика пересобирается, пока другой поток пишет числа.        #
# ====================================================================== #


class TestPolicyRebuildUnderConcurrentWriters:
    """Опасность №3 задания: ``config.reload`` во время записи чисел."""

    def test_every_call_has_exactly_one_outcome_while_the_policy_is_swapped(self) -> None:
        """Закон сохранения: собрано + срезано == позвано. Ни потерь, ни двойного счёта.

        Пишет ОДИН поток, политику подменяет главный. Второй пишущий поток здесь
        сделал бы тест флейким по собственному признанию механизма: счётчики
        гейта инкрементятся без лока (названный потолок в ``NumbersGate``), и под
        конкуренцией теряют единицы. Проверять законом сохранения то, что само
        объявлено неточным, значило бы завести тест, который краснеет от
        расписания планировщика, а не от дефекта.

        Что тест ловит на самом деле: подмена ссылки на политику ПОСРЕДИ записи
        не имеет права ни уронить пишущего, ни оставить число «нигде» — а именно
        так выглядел бы разрыв, собери гейт своё решение из двух чтений
        ``self._policy`` (одно для ``enabled``, другое для интервала).

        Поток — daemon с дедлайном на ``join``: тест, который ВИСНЕТ вместо
        падения, хуже отсутствующего — он прячет регресс за таймаутом.
        """
        stop = threading.Event()
        done = threading.Event()
        errors: List[BaseException] = []
        # Потолок итераций — предохранитель от бесконечного цикла, если событие
        # остановки почему-то не доедет. Не ожидание и не ориентир: реальное
        # число вызовов считает сам пишущий, и закон сохранения проверяется
        # против НЕГО, а не против литерала.
        cap = 200_000

        gate = NumbersGate(
            ObservationPolicy(ObservationPolicyConfig(rules={"processes.cam1.stats.a": MetricRule(enabled=False)})),
            "cam1",
        )
        called: Dict[str, int] = {"a": 0, "b": 0}
        allowed: Dict[str, int] = {"a": 0, "b": 0}

        def _writer() -> None:
            try:
                for _ in range(cap):
                    if stop.is_set():
                        return
                    for name in ("a", "b"):
                        called[name] += 1
                        if gate.allow(name):
                            allowed[name] += 1
            except BaseException as exc:  # noqa: BLE001 — падение пишущего и есть предмет теста
                errors.append(exc)
            finally:
                done.set()

        thread = threading.Thread(target=_writer, daemon=True, name="numbers-writer")
        thread.start()
        # Пауза между подменами — НЕ ожидание результата, а гарантия
        # ПЕРЕПЛЕТЕНИЯ: без неё главный поток успевал прокрутить все подмены
        # раньше, чем пишущий делал первый вызов, и тест зеленел вхолостую
        # (собственный сторож ниже это и поймал: 0 разрешённых 'a' из 400).
        for index in range(40):
            blocked = "a" if index % 2 else "b"
            gate.set_policy(
                ObservationPolicy(
                    ObservationPolicyConfig(rules={f"processes.cam1.stats.{blocked}": MetricRule(enabled=False)})
                )
            )
            time.sleep(0.002)
        stop.set()
        assert done.wait(timeout=30.0), "пишущий поток не завершился за 30 с — механизм заблокировал запись чисел"
        thread.join(timeout=5.0)
        assert not errors, f"подмена политики уронила пишущий поток: {errors!r}"

        dropped = gate.dropped_by_metric()
        assert gate.throttled_by_metric() == {}, "интервалов в этом тесте нет — придержанных быть не может"
        for name in ("a", "b"):
            assert allowed[name] + dropped.get(name, 0) == called[name], (
                f"{name}: собрано {allowed[name]} + срезано {dropped.get(name, 0)} != позвано {called[name]} — "
                "число исчезло между чтением политики и решением"
            )
            assert allowed[name] > 0 and dropped.get(name, 0) > 0, (
                f"тест вхолостую: подмена ни разу не переключила решение по {name!r} "
                f"(собрано {allowed[name]}, срезано {dropped.get(name, 0)} из {called[name]})"
            )


# ====================================================================== #
#  Шов гейта: обе дороги и обе плоскости решений.                        #
# ====================================================================== #


def _pair(process: str, policy: Any, plane_enabled: bool = True):
    """Реальные порт и менеджер, связанные как в ``ProcessManagers.create_all``."""
    port = ObservationManager(manager_name=f"port_{process}", process=SimpleNamespace(name=process))
    assert port.initialize()
    if policy is not None:
        port.attach_numbers_policy(policy)
    mgr = StatsManager(
        manager_name=f"stats_{process}",
        config={
            "enabled": plane_enabled,
            "enable_logging": False,
            "aggregation_interval": 300.0,
            "flush_interval": 300.0,
            "channels": {"file_stats": {"enabled": False}},
        },
    )
    assert mgr.initialize()
    assert mgr.attach_observation_port(port) is True
    return mgr, port


class TestTheGateSitsInTheSeam:
    def test_a_denied_number_never_reaches_delivery(self) -> None:
        """Необходимое условие «решение ДО сборки записи»: доставки не было вовсе.

        Достаточное (цена вызова) меряет бенч шага 5 — тест на время в наборе был
        бы флейким по построению. Здесь проверяется то, что тестом проверяемо:
        запрещённое число не доходит до ``_deliver_number``, то есть словарь
        записи не собирается и раздача tap'ам не начинается.
        """
        policy = ObservationPolicy(
            ObservationPolicyConfig(rules={"processes.cam1.stats.denied": MetricRule(enabled=False)})
        )
        mgr, port = _pair("cam1", policy)
        delivered: List[Dict[str, Any]] = []
        original = port._deliver_number
        port._deliver_number = lambda record: (delivered.append(record), original(record))[1]  # type: ignore[method-assign]
        try:
            for _ in range(4):
                mgr.record_metric("denied", 1)
            mgr.record_metric("open", 1)
            assert [rec["name"] for rec in delivered] == ["open"], f"запрещённое число дошло до доставки: {delivered!r}"
        finally:
            port._deliver_number = original  # type: ignore[method-assign]
            mgr.shutdown()
            port.shutdown()

    def test_the_disabled_plane_also_covers_the_plugin_road_into_the_port(self) -> None:
        """Плоскость выключена — число, написанное ПРЯМО В ПОРТ, тоже не собирается.

        Дорога плагина (``PluginContext._stats_call`` → ``port.record_metric``)
        идёт мимо фасада ``StatsManager``, и гейт плоскости, поставленный в
        фасад, эту дорогу не накрыл бы: числа плагинов продолжали бы копиться в
        окне при выключенной плоскости. Утверждение из докстринга
        ``_apply_metric`` («шов накрывает обе дороги») здесь проверяется
        исполнением, а не читается на слово.
        """
        mgr, port = _pair("cam1", None, plane_enabled=False)
        try:
            for _ in range(3):
                port.record_metric("plugin.frames", 1)  # дорога плагина, мимо менеджера
            mgr.record_metric("facade.metric", 1)  # дорога фасада
            mgr.flush()
            assert mgr.get_all_metrics() == {}, f"выключенная плоскость собрала числа: {mgr.get_all_metrics()!r}"
            dropped = mgr.get_stats()["numbers_policy_dropped"]
            assert dropped == {"plugin.frames": 3, "facade.metric": 1}, (
                f"обе дороги обязаны быть посчитаны выключенной плоскостью: {dropped!r}"
            )
        finally:
            mgr.shutdown()
            port.shutdown()

    def test_the_plane_and_the_rule_share_one_read_address(self) -> None:
        """Один адрес на два владельца решения — сумма читается в одном месте.

        Плоскость судит в ``StatsManager``, правило — в гейте порта. Читатель
        обязан спрашивать ОДИН раз: два счётчика с одним именем в двух объектах
        он складывал бы вручную и ошибался бы молча.
        """
        policy = ObservationPolicy(
            ObservationPolicyConfig(rules={"processes.cam1.stats.ruled": MetricRule(enabled=False)})
        )
        mgr, port = _pair("cam1", policy)
        try:
            mgr.record_metric("ruled", 1)
            mgr.record_metric("ruled", 1)
            assert mgr.get_stats()["numbers_policy_dropped"] == {"ruled": 2}
            assert "numbers_policy_dropped" not in port.get_stats(), (
                "порт не должен нести ключ с тем же именем — адрес обязан быть один"
            )
        finally:
            mgr.shutdown()
            port.shutdown()
