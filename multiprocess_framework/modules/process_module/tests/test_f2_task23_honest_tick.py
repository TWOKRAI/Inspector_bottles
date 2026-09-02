# -*- coding: utf-8 -*-
"""RED-тесты Task 2.3 плана ``observability-closure`` (M9, «Честный такт»).

Ф2, [`phase-2-one-policy.md`](../../../../../plans/observability-closure/phase-2-one-policy.md),
раздел «Task 2.3 — Честный такт: эффективная каденция в readback и голосом».

**Статус на момент написания: коммит ДО реализации** (worktree на ``eb233480``).
Все пять свойств ниже сегодня либо падают ``AssertionError``/``AttributeError``
(ключа/атрибута нет), либо (Test 4-контроль) намеренно зелены уже сейчас —
отмечено явно в докстринге теста.

Грепом подтверждено (весь ``multiprocess_framework/modules/process_module``):
``heartbeat_interval_sec`` / ``effective_interval_sec`` / ``tick_effective_sec`` —
НОЛЬ вхождений где бы то ни было, включая тесты. Механизм целиком новый.

**Символы, которые ниже ПРЕДПОЛАГАЮТСЯ (спецификация имён для реализатора)** —
без interface.py источник истины только текст плана + структура соседних,
уже существующих плоскостей (``events``/``flight``/``voices``/``observation``
в ``observability_effective`` и ``_rebuild_and_apply``, см.
``managers/observability_reload.py``):

1. ``ObservabilityConfig.heartbeat_interval_sec: float = 5.0`` — новое поле
   схемы. Имя дано ДОСЛОВНО текстом шага 1 плана («ключ слоёв
   ``observability.heartbeat_interval_sec``»), риск минимален.
2. ``ProcessHeartbeat.current_resolved_metrics()`` — каждая запись словаря
   получает НОВЫЙ ключ ``"effective_interval_sec"`` (float). Имя дано
   ДОСЛОВНО критерием приёмки.
3. Ответ команды ``introspect.telemetry`` (``_cmd_introspect_telemetry``)
   получает НОВЫЙ ключ ВЕРХНЕГО уровня ``"tick_effective_sec"`` (float).
   Имя дано ДОСЛОВНО критерием приёмки; значение — уже существующий
   ``ProcessHeartbeat._telemetry_tick()``, просто не выставленный наружу.
4. ``ObservationPolicy.effective_view()`` (через
   ``ProcessHeartbeat.current_observation_policy()`` →
   ``introspect.observability`` → ``effective.observation``) получает НОВЫЙ
   ключ ``"effective"``. Имя ключа дано ДОСЛОВНО («observation.effective»).
   **ВНУТРЕННЯЯ форма — МОЙ ГАДАННЫЙ довесок**, по аналогии с уже существующим
   ``cap_candidates()``/``capped_metrics()`` (``configs/observation_policy.py``,
   ``heartbeat/telemetry.py``): ``{паттерн: {"interval_sec": ..., "effective_interval_sec": ...}}``.
   Помечено отдельным тестом и явной оговоркой в его докстринге — если форма
   окажется другой, это ТЗ для реализатора, а не диагноз чужого бага.
5. Донесение ``heartbeat_interval_sec`` до ЖИВОГО ``ProcessHeartbeat._interval``
   через ``config.reload`` (аналог существующих ``apply_observation_policy``/
   ``apply_voices_policy`` в ``_rebuild_and_apply``, ``managers/observability_reload.py``)
   — имени НЕ угадываю вовсе: тест 3с проверяет только НАБЛЮДАЕМЫЙ эффект
   (``svc._heartbeat._interval`` — уже существующий атрибут) через уже
   существующую команду ``config.reload``, не называя новую функцию.
6. Правка поведения ``_warn_capped_metrics`` при ``tick_sec=None`` — НЕ новый
   символ, метод уже существует; меняется его текущий early-return (см.
   докстринг метода: «No-op, если tick_sec не задан»).

**Харнесс.** ``_wired`` (импортирован из ``test_observation_policy_review_f4``)
регистрирует ТОЛЬКО ``_register_observability_commands()`` — ``config.reload``,
``telemetry.reconfigure``. Command'ы ``introspect.telemetry``/
``introspect.observability`` живут в ОТДЕЛЬНОМ ``_register_introspect_commands()``
(проверено чтением: ``test_introspect_telemetry.py::_make`` зовёт ОБА метода —
``_wired`` этого не делает). Поэтому ниже — свой ``_wired_with_introspect``,
дословная копия тела ``_wired`` с добавленным вызовом; ``_wired`` наружу
объект ``bc`` не отдаёт, пристроить вызов к готовому результату нечем.

**Инъекция (критерий 5 плана): «убрать max() → тест красный».** Отдельного
теста-инъекции здесь нет и не нужно — это СВОЙСТВО тестов 1a/1b (см. их
докстринги): значения подобраны так, что убрать ``max()`` (заменить на
``min()``, на голый ``interval_sec`` или на голый ``tick``) ломает хотя бы
один из двух случаев арифметически. Живую инъекцию (реальный break-injection
на собранном коде) эта стадия не проводит — реализации ещё нет; это задача
стадии 3 (see ``docs/claude/memory`` / CLAUDE.md «Task launch convention»).
"""

from __future__ import annotations

from typing import Any

import yaml

from multiprocess_framework.modules.process_module.commands.builtin_commands import (
    BuiltinCommands,
)
from multiprocess_framework.modules.process_module.configs.observability_config import (
    ObservabilityConfig,
)
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    process_observability_layers,
)
from multiprocess_framework.modules.process_module.configs.observation_policy import (
    DEFAULT_SUBTREE_INTERVAL_SEC,
    PORT_SUBTREE_PATTERN,
)
from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
    TelemetryPublishConfig,
)
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)

from .test_observation_policy_review_f4 import _wired
from .test_telemetry_commands import _FakeLogger, _FakeServices
from .test_telemetry_layers import BOOT_PUBLISH

#: Дефолт heartbeat в ``ProcessHeartbeat.__init__`` ДО ``start()`` — тот же
#: литерал, что план называет L0-дефолтом новой ``heartbeat_interval_sec``.
#: ``_wired``/``_wired_with_introspect`` НИКОГДА не зовут ``.start()`` (см. их
#: докстринги) — то есть в этих тестах такт всегда идёт от него, если явно не
#: перезаведён через ``reconfigure_telemetry``/``config.reload``.
BOOT_HEARTBEAT_INTERVAL = 5.0


def _wired_with_introspect(tmp_path):
    """``_wired`` + регистрация ``introspect.telemetry``/``introspect.observability``.

    Дословная копия тела ``_wired`` (``test_observation_policy_review_f4.py:64``)
    с добавленным ``bc._register_introspect_commands()`` — см. докстринг модуля,
    почему голого ``_wired`` для этих команд не хватает.
    """
    svc = _FakeServices(logger=_FakeLogger())
    svc._config["telemetry"] = {"publish": BOOT_PUBLISH}
    svc._heartbeat._services._config["telemetry"] = {"publish": BOOT_PUBLISH}
    svc._heartbeat._telemetry_gate = svc._heartbeat._build_telemetry_gate()

    cfg_path = tmp_path / "system.yaml"
    cfg_path.write_text(yaml.safe_dump({"observability": {"log_level": "INFO"}}), encoding="utf-8")
    svc._config["observability_config_path"] = str(cfg_path)

    bc = BuiltinCommands(svc)
    bc._register_introspect_commands()
    bc._register_observability_commands()
    process_observability_layers(svc)
    return svc, svc.command_manager.handlers


class _RecordingServices:
    """Минимальный контекст ``ProcessHeartbeat`` для ``_warn_capped_metrics``, который
    ПОМНИТ голос — в отличие от ``_HeartbeatServices`` (``test_telemetry_commands.py``),
    у которой ``log_info``/``log_debug`` — молчаливые заглушки, а ``log_warning`` нет
    вовсе (метод при её использовании падает в no-op ``log_info`` и ничего не хранит).
    Своя мини-заглушка, а не правка чужой: та используется по имени в других файлах.
    """

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def log_warning(self, message: str, *a: Any, **k: Any) -> None:
        self.warnings.append(message)

    def log_info(self, *a: Any, **k: Any) -> None: ...

    def log_debug(self, *a: Any, **k: Any) -> None: ...


# =========================================================================== #
# 1. introspect.telemetry.resolved[*].effective_interval_sec + tick_effective_sec
# =========================================================================== #
class TestResolvedMetricsShowTheEffectiveInterval:
    """M9, шаг 3: readback обязан показывать ДОСТИЖИМЫЙ интервал публикации,
    а не только заявленный ``interval_sec`` — расхождение «сконфигурировано 1с,
    действует 5с» обязано быть слышно оператору из ``introspect.telemetry``,
    не только из строки лога.

    Оба теста вместе пинуют ФОРМУЛУ ``effective_interval_sec = max(interval_sec,
    tick)`` (а не только факт наличия поля) — см. их докстринги: они специально
    подобраны так, что в одном случае побеждает такт, а в другом — заявленный
    интервал. Порознь каждый пропустил бы половину вырожденных инъекций
    (голый ``interval_sec`` без ``max()``, голый ``tick`` без ``max()``,
    ``min()`` вместо ``max()``) — см. докстринг модуля, критерий 5 плана.
    """

    def test_the_tick_wins_when_the_configured_interval_is_tighter(self, tmp_path) -> None:
        """Буквальный сценарий приёмки: ``interval_sec: 1.0`` при такте 5.0 → 5.0.

        Такт = ``heartbeat_interval`` (5.0, дефолт — ``.start()`` не звался):
        ``tick_sec`` НЕ задан → ``_telemetry_tick()`` возвращает
        ``self._interval`` (уже существующий метод, см. его докстринг).
        Метрика просит 1.0с — быстрее такта, поэтому ДОСТИЖИМОЕ — 5.0, не 1.0.
        """
        svc, handlers = _wired_with_introspect(tmp_path)
        svc._heartbeat.reconfigure_telemetry({"metrics": {"fps": {"enabled": True, "interval_sec": 1.0}}})

        resp = handlers["introspect.telemetry"]({})

        assert resp["success"] is True, resp
        assert "tick_effective_sec" in resp, sorted(resp)  # поля нет сегодня
        assert resp["tick_effective_sec"] == BOOT_HEARTBEAT_INTERVAL, resp["tick_effective_sec"]

        fps = resp["resolved"]["fps"]
        assert fps["interval_sec"] == 1.0, fps  # заявленное — уже работает сегодня, не трогаем
        assert "effective_interval_sec" in fps, sorted(fps)  # поля нет сегодня
        assert fps["effective_interval_sec"] == BOOT_HEARTBEAT_INTERVAL, fps  # max(1.0, 5.0) = 5.0

    def test_the_configured_interval_wins_when_it_is_looser_than_the_tick(self, tmp_path) -> None:
        """Зеркальный случай: такт БЫСТРЕЕ заявленного интервала → достижимое = заявленное.

        ``BOOT_PUBLISH`` (harness-дефолт, ``tick_sec=1.0``): такт =
        ``min(5.0, 1.0) = 1.0``; ``fps.interval_sec=5.0`` — МЕДЛЕННЕЕ такта,
        поэтому такт метрику не «зажимает», и достижимое равно заявленному.

        Без этого случая мутация «``effective_interval_sec`` = голый ``tick``
        всегда» (без ``max()``) прошла бы предыдущий тест НЕ иначе — она бы
        его тоже сломала (0.083... нет, тут тик=5.0=ожиданию совпадает — см.
        докстринг класса) вообще-то ловится ИМЕННО здесь: голый tick дал бы
        1.0 вместо правильных 5.0.
        """
        svc, handlers = _wired_with_introspect(tmp_path)
        # Гейт уже собран `_wired_with_introspect` из BOOT_PUBLISH — доп. reconfigure не нужен.

        resp = handlers["introspect.telemetry"]({})

        assert resp["success"] is True, resp
        assert "tick_effective_sec" in resp, sorted(resp)
        assert resp["tick_effective_sec"] == 1.0, resp["tick_effective_sec"]  # min(5.0, 1.0)

        fps = resp["resolved"]["fps"]
        assert fps["interval_sec"] == 5.0, fps
        assert "effective_interval_sec" in fps, sorted(fps)
        assert fps["effective_interval_sec"] == 5.0, fps  # max(5.0, 1.0) = 5.0 = заявленное


# =========================================================================== #
# 2. introspect.observability → effective.observation.effective (порт)
# =========================================================================== #
class TestObservationEffectiveShowsThePortsAchievableCadence:
    """M9, шаг 3, вторая половина: то же самое, но для правил ПОРТА
    (``observability.observation``, ``processes.*.state.plugins.**``) — тем же
    тактом, что и у framework-плоскости выше (один механизм, одна цифра).
    """

    def test_the_effective_key_exists_in_the_ports_readback(self, tmp_path) -> None:
        """Первичное, низкорисковое утверждение: сам КЛЮЧ ``effective`` появился.

        Имя ключа дано ДОСЛОВНО критерием приёмки («observation.effective») —
        в отличие от следующего теста, здесь не гадается внутренняя форма.
        """
        svc, handlers = _wired_with_introspect(tmp_path)
        svc._heartbeat.reconfigure_telemetry({"metrics": {"fps": {"enabled": True, "interval_sec": 1.0}}})

        resp = handlers["introspect.observability"]({})

        assert resp["success"] is True, resp
        observation = resp["effective"]["observation"]
        assert "effective" in observation, sorted(observation)

    def test_the_subtree_defaults_effective_interval_matches_the_tick(self, tmp_path) -> None:
        """Форма ``effective`` — МОЙ ДОГАД по аналогии с уже существующим
        ``cap_candidates()``/``capped_metrics()`` (``configs/observation_policy.py``,
        ``heartbeat/telemetry.py``): ``{паттерн: {"interval_sec", "effective_interval_sec"}}``.
        Если реализатор выберет другую форму — это НЕ баг, это несовпадение
        с моим предположением, и тест правится, а не диагностирует regressию.

        Сценарий: такт = 5.0 (heartbeat_interval, ``tick_sec`` снят), правил
        оператора НЕТ ни одного → решает дефолт поддерева
        (``DEFAULT_SUBTREE_INTERVAL_SEC`` = 1.0, ``PORT_SUBTREE_PATTERN``) —
        быстрее такта, поэтому достижимое 5.0, не 1.0. Прямая параллель со
        сценарием ``test_the_tick_wins_when_the_configured_interval_is_tighter``
        выше, тем же гейтом (``cap_candidates`` уже считает этот случай
        «зажатым» для ЦЕЛЕЙ ГОЛОСА — см. ``capped_metrics``; этот тест
        проверяет то же самое число, но в READBACK, а не в логе).
        """
        svc, handlers = _wired_with_introspect(tmp_path)
        svc._heartbeat.reconfigure_telemetry({"metrics": {"fps": {"enabled": True, "interval_sec": 1.0}}})

        resp = handlers["introspect.observability"]({})
        observation = resp["effective"]["observation"]

        assert "effective" in observation, sorted(observation)
        effective = observation["effective"]
        assert PORT_SUBTREE_PATTERN in effective, sorted(effective) if isinstance(effective, dict) else effective
        subtree = effective[PORT_SUBTREE_PATTERN]
        assert subtree["interval_sec"] == DEFAULT_SUBTREE_INTERVAL_SEC, subtree  # заявленное (дефолт), 1.0
        assert subtree["effective_interval_sec"] == BOOT_HEARTBEAT_INTERVAL, subtree  # max(1.0, 5.0) = 5.0


# =========================================================================== #
# 3. heartbeat_interval → ключ слоёв observability.heartbeat_interval_sec
# =========================================================================== #
class TestHeartbeatIntervalIsALayeredKeyWithProvenance:
    """M9, шаг 1, половина «схема + провенанс»: ``heartbeat_interval`` перестаёт
    быть голым ``get_config("heartbeat_interval", 5.0)`` и становится полем
    ``ObservabilityConfig`` — L0 = 5.0, с провенансом наравне с соседями
    (``session_ttl_sec`` и т.п.).
    """

    def test_the_schema_default_is_5_seconds(self) -> None:
        """Прямой доступ к атрибуту — НЕ через resolve()/поведение (см. правило
        проекта про ``extra=ignore``: ``SchemaBase`` молча роняет непоказанный
        kwarg, и поведенческая проверка через него осталась бы зелёной и без
        поля). Сегодня падает ``AttributeError`` — поля нет вовсе.
        """
        cfg = ObservabilityConfig()
        assert cfg.heartbeat_interval_sec == BOOT_HEARTBEAT_INTERVAL, cfg.heartbeat_interval_sec

    def test_provenance_names_the_key_at_l0_by_default(self, tmp_path) -> None:
        """Без единой правки любого слоя ключ ОБЯЗАН появиться в ``provenance``
        (генерик по ``_schema_keys()`` — ``ObservabilityLayers.provenance``,
        ``configs/observability_layers.py:891-923`` — заводить отдельную
        проводку для КАЖДОГО скалярного поля не нужно, но само поле в схеме
        обязано быть, иначе ``_schema_keys()`` о нём не знает).
        """
        svc, handlers = _wired_with_introspect(tmp_path)

        resp = handlers["introspect.observability"]({})

        assert "heartbeat_interval_sec" in resp["provenance"], sorted(resp["provenance"])
        assert resp["provenance"]["heartbeat_interval_sec"] == {"layer": "framework", "source": "framework"}, resp[
            "provenance"
        ]["heartbeat_interval_sec"]


class TestHeartbeatIntervalAppliesLiveWithoutRestart:
    """M9, шаг 1, половина «применяется reload'ом БЕЗ рестарта» — буквальный
    сценарий приёмки: ``config_reload(heartbeat_interval_sec=1.0)`` меняет
    действующий такт немедленно, без пересоздания процесса/heartbeat'а.

    **Значение НЕ совпадает со схемным дефолтом (5.0)** — намеренно, по
    правилу проекта из брифа: «не бери в качестве ожидаемого значения схемный
    дефолт», иначе реализация, тихо игнорирующая ключ и продолжающая жить на
    дефолте 5.0, прошла бы тест НЕЗАМЕТНО. 1.0 отличимо от дефолта числом.
    """

    def test_config_reload_mutates_the_live_interval_without_calling_start(self, tmp_path) -> None:
        svc, handlers = _wired(tmp_path)
        # Явный якорь «без рестарта»: .start() в этом харнессе не звался НИ РАЗУ
        # (ни разу за весь сетап `_wired`) — если бы прикладной код теста случайно
        # его вызвал, эта проверка поймала бы подмену сценария.
        assert svc._heartbeat.is_running() is False, "start() не должен был вызываться в этом сценарии"
        assert svc._heartbeat._interval == BOOT_HEARTBEAT_INTERVAL, svc._heartbeat._interval

        res = handlers["config.reload"]({"observability": {"heartbeat_interval_sec": 1.0}})

        # Сегодня здесь success=False: `heartbeat_interval_sec` — неизвестный ключ
        # секции сессии, и `validate_layer_section` (`observability_layers.py:1251-1335`)
        # отказывает ДО записи в слой (см. её докстринг, «пятое место — задача 5.4»).
        # Это ЧЕСТНЫЙ, читаемый RED: `res["reason"]` прямо называет неизвестное имя.
        assert res["success"] is True, res
        assert svc._heartbeat._interval == 1.0, svc._heartbeat._interval
        assert svc._heartbeat.is_running() is False, "проверка бьёт мимо цели, если применение вызвало рестарт"


# =========================================================================== #
# 4. _warn_capped_metrics работает и при tick_sec=None (такт = heartbeat)
# =========================================================================== #
class TestWarnCappedMetricsWorksWithoutAnExplicitTickSec:
    """M9, шаг 2: голос о недостижимой частоте обязан звучать и когда оператор
    НЕ трогал ``tick_sec`` вовсе — такт в этом случае всё равно есть
    (``= heartbeat_interval``), и метрика может упираться в НЕГО ровно так же,
    как в явный ``tick_sec``. Сегодня ``_warn_capped_metrics`` при
    ``tick_sec=None`` возвращается РАНЬШЕ вычисления такта (см. её текущий
    докстринг: «No-op, если tick_sec не задан») — то есть эта ветка голоса
    тихая ВСЕГДА, независимо от того, зажата ли метрика фактическим тактом.
    """

    def test_a_metric_capped_by_heartbeat_interval_alone_still_warns(self) -> None:
        """Метрика просит 1.0с при отсутствующем ``tick_sec`` и дефолтном
        ``heartbeat_interval=5.0`` — достижимо не чаще 5.0с, и это обязано
        прозвучать ОДНИМ WARNING с адресом ключа (``fps``), а не молчанием.
        """
        services = _RecordingServices()
        hb = ProcessHeartbeat(services)
        config = TelemetryPublishConfig.from_dict({"metrics": {"fps": {"enabled": True, "interval_sec": 1.0}}})
        assert config.tick_sec is None, config  # предпосылка сценария подтверждена

        hb._warn_capped_metrics(config)

        assert services.warnings, "нет ни одного WARNING — fps просит 1.0с при heartbeat_interval=5.0с"
        assert len(services.warnings) == 1, services.warnings  # один голос на пересборку, не по счётчику метрик
        assert "fps" in services.warnings[0], services.warnings[0]  # адрес ключа назван, а не общая жалоба

    def test_an_uncapped_metric_still_stays_silent_with_no_tick_sec(self) -> None:
        """КОНТРОЛЬ (вторая половина пары «ложноположительный/ложноотрицательный»,
            см. правило проекта §1 из брифа) — этот тест УЖЕ ЗЕЛЁН сегодня, и это
            честно ожидаемо, а не находка: при ``interval_sec=10.0 > heartbeat_interval
            (5.0)`` метрика не зажата НИ ДО, НИ ПОСЛЕ фикса — сегодня отсутствие
            голоса объясняется багом (ранний возврат), после фикса — тем, что
            зажимать нечего. Оставлен, чтобы починка шага 2 не превратила «работает
            и при tick_sec=None» в «шумит по любому правилу вообще».

            **Подпорка снята оркестратором (стадия 3), с воспроизведением.** Исполнитель
        добавлял сюда ``default_interval_sec`` и сам пометил правку возможно
        избыточной после того, как сузил охват ``capped_metrics()``. Проверено
        прямым прогоном: без неё набор 9/9 зелёный — подпорка действительно
        стала лишней и убрана, чтобы сцена теста читалась однозначно.
        Историческая причина, по которой она появлялась: Исходный конфиг
            (без ``default_interval_sec``) действительно был зелёным ДО фикса, но
            НЕ остаётся зелёным ПОСЛЕ него — не из-за ``fps``, а из-за СОСЕДНЕЙ,
            не связанной с шагом 2 механики: ``capped_metrics()`` (``heartbeat/
            telemetry.py``) обходит ВЕСЬ каталог :func:`gated_metrics` (``fps``,
            ``latency_ms``, ``effective_hz``, ``cycle_duration_ms``, ``shm``), а не
            только явно перечисленные в ``metrics``. Четыре метрики без правила
            резолвятся в ``(default_enabled, default_interval_sec)`` —
            ``default_interval_sec`` схемы по умолчанию ``1.0`` — то есть **тоже**
            меньше такта 5.0с и тоже считаются зажатыми, независимо от того, что
            оператор написал про ``fps``. Воспроизведено ДО этой правки прогоном
            класса в изоляции: тест падал на непустом списке из четырёх ЧУЖИХ имён
            (``cycle_duration_ms``/``effective_hz``/``latency_ms``/``shm``), ``fps``
            среди них не было — то есть само свойство шага 2 (не путать явно
            зажатую метрику с незажатой) было цело, а падал контроль по НЕВЕРНОЙ
            причине. То же самое воспроизводится СЕГОДНЯ и на уже задействованном
            пути ``tick_sec``, заданном явно (``{"tick_sec": 5.0, ...}``) — то есть
            это не находка шага 2, а существовавшее и до задачи 2.3 свойство
            ``capped_metrics()``: каталог обходится целиком, а не по явным записям
            ``metrics``. Правка ниже — ОДИН добавленный ключ ``default_interval_sec``
            (= такту), убирающий эту помеху, а не ослабление проверяемого свойства:
            assertion остаётся тем же самым «полное молчание», просто конфиг больше
            не подставляет параллельно СВОЙ собственный (не ``fps``-овый) повод для
            голоса.
        """
        services = _RecordingServices()
        hb = ProcessHeartbeat(services)
        config = TelemetryPublishConfig.from_dict(
            {
                # Такту (5.0) РАВНО, не МЕНЬШЕ — capped_metrics() режет строго по
                # `<`, поэтому дефолт остальных четырёх метрик каталога перестаёт
                # быть их СОБСТВЕННЫМ поводом для голоса, и тест снова проверяет
                # только заявленное свойство: `fps` с interval_sec=10.0 не зажат.
                "metrics": {"fps": {"enabled": True, "interval_sec": 10.0}},
            }
        )
        assert config.tick_sec is None, config

        hb._warn_capped_metrics(config)

        assert services.warnings == [], services.warnings
