# -*- coding: utf-8 -*-
"""Приёмочные тесты Task 2.5 плана ``observability-closure`` (m11) — легаси
``telemetry.publish`` как ОДИН адаптер в единой политике, а не вторая дверь.

НЕЗАВИСИМЫЙ тестер, стадия 1: написано ДО реализации, по критериям приёмки из
``plans/observability-closure/phase-2-one-policy.md`` (Task 2.5) и по заданию
оркестратора (4 критерия). Диффа и кода реализации не существует — рабочее
дерево стоит на коммите ДО правки (``eb233480``). ``interface.py`` у модуля
нет; контракт читается из самого ``observation_policy.py`` (докстринг класса
+ докстринг ``resolve``/``_decide`` + существующие тесты
``test_observation_policy_review_f4.py`` как живой прецедент формы ответа).

Четыре критерия — четыре класса теста ниже:

  1. ``TestLegacyParityAcrossEightMetrics`` — паритетный тест: боевой конфиг
     прототипа даёт ТЕ ЖЕ решения (enabled, interval_sec) по 8 именам метрик,
     что и до правки. **Законно ЗЕЛЁН сегодня** — паритет «до=после» на
     неизменённом дереве сравнивает движок сам с собой. Ценность не в
     сегодняшнем результате, а в том, что литералы получены РУЧНЫМ разбором
     алгоритма ``_decide()``, а не подсмотрены у объекта под тестом, и обязаны
     остаться ТЕМИ ЖЕ после переезда легаси в ``observation.rules``.
  2. ``TestReadbackShowsLegacyProvenance`` — readback правила легаси-
     происхождения называет ``source`` дословно ``legacy:telemetry.publish``
     (не ``whitelist`` — сегодняшний ``SOURCE_WHITELIST``). КРАСНЫЙ сегодня.
  3. ``TestReconfigureRoutesThroughTheSameTranslator`` — ``telemetry.reconfigure``
     даёт ТОТ ЖЕ ``source`` и переводит легаси в ``observation.rules`` (растёт
     ``.config.rules``), а не держит его вторым, отдельным параметром
     ``legacy=``. КРАСНЫЙ сегодня.
  4. ``TestUmbrellaDefaultNoLongerASeparateWhitelistTier`` — зонтичный
     ``default_enabled`` (случай, где легаси отвечает НЕ явной записью
     ``metrics.<имя>``, а умолчанием) тоже переходит на ``source``
     ``legacy:telemetry.publish`` — не остаётся отдельной веткой
     ``TIER_UMBRELLA``/``SOURCE_WHITELIST`` рядом с ``subtree_enabled``.
     КРАСНЫЙ сегодня. **Огорка о неоднозначности критерия — см. докстринг
     класса и отчёт тестера.**

Восемь имён метрик паритетного теста (см. класс 1) — из каталога
``declare_metric`` фреймворка (``heartbeat/telemetry.py:59-62``,
``heartbeat/process_heartbeat.py:21``: ``fps``, ``latency_ms``,
``effective_hz``, ``cycle_duration_ms``, ``shm``) и из комментария боевого
``system.yaml:180-181`` про плагинные метрики поддерева писателя
(``capture_fps``, ``frame_count``, ``drops``).

Пути построены ТЕМИ ЖЕ шаблонами, что использует боевой код (не придуманы):
``STATE_PATH_TEMPLATE = "processes.{process}.state.{leaf}"`` и
``PLUGIN_PATH_TEMPLATE = "processes.{process}.state.plugins.{writer}.{leaf}"``
(обе — ``heartbeat/telemetry.py:37-38``). Framework-метрики (первые пять)
резолвятся ОДНИМ вызовом ``due_metrics()`` на ВЕСЬ процесс — per-worker
``effective_hz``/``cycle_duration_ms`` гейтуются не по путям воркеров, а по
имени листа на уровне процесса (``telemetry.py:132-133``,
``process_heartbeat.py:1267``), поэтому путь для них — тот же
``processes.<p>.state.<имя>``, что и у ``fps``/``latency_ms``/``shm``.

Ни один тест не трогает ``_impl``/реализацию — только читает
``ObservationPolicy`` и командные хендлеры, которые уже существуют в этом
коммите.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from multiprocess_framework.modules.process_module.configs.observation_policy import (
    ObservationPolicy,
    ObservationPolicyConfig,
)

from .test_observation_policy_review_f4 import PROC, _policy
from .test_telemetry_commands import _make

# Литерал из ТЕКСТА критерия приёмки Task 2.5 (АК2), взят дословно из задания
# тестеру ("Readback показывает правило с `source: legacy:telemetry.publish`"),
# а НЕ выражением от кода под тестом (не ``f"legacy:{LEGACY_SOURCE_NAME}"`` —
# ``LEGACY_SOURCE_NAME`` живёт в модуле под тестом, и такое выражение доказывало
# бы согласие с самим собой).
LEGACY_PROVENANCE = "legacy:telemetry.publish"

# Боевой конфиг прототипа — источник паритетного теста (критерий АК1).
SYSTEM_YAML = Path(__file__).resolve().parents[4] / "multiprocess_prototype" / "backend" / "config" / "system.yaml"


def _load_real_legacy_publish() -> dict:
    """Секция ``telemetry.publish`` из БОЕВОГО ``system.yaml`` — не копия руками.

    Читаем файл, а не переносим значения в константу теста: копия руками не
    заметила бы дрейф боевого конфига, а паритетный тест обязан ловить именно
    его — по условию задачи. Два ``assert`` ниже — НЕ проверка политики (её
    нулевой смысл до правки), а страховка от дрейфа: если боевой конфиг сменит
    форму, тест обязан сказать «конфиг изменился», а не «политика сломалась».
    """
    raw = yaml.safe_load(SYSTEM_YAML.read_text(encoding="utf-8"))
    publish = raw["telemetry"]["publish"]
    assert publish.get("default_enabled") is False, (
        f"боевой system.yaml сменил default_enabled — паритетный тест ловит ДРЕЙФ "
        f"КОНФИГА, не движок политики: {publish!r}"
    )
    assert set(publish.get("metrics", {})) == {"fps", "latency_ms"}, (
        f"боевой system.yaml сменил состав metrics — паритетный тест ловит ДРЕЙФ КОНФИГА: {publish!r}"
    )
    return publish


#: Читается один раз на сборку модуля (collection time) — восемь тестов ниже
#: не должны платить восемь раз за чтение и разбор одного и того же файла, а
#: расхождение конфига обязано упасть ОДИН раз, громко, при сборке.
REAL_LEGACY_PUBLISH = _load_real_legacy_publish()

WRITER = "capture"

#: {имя метрики: (путь, ожидаемый enabled, ожидаемый interval_sec)} — ЛИТЕРАЛЫ,
#: полученные РУЧНЫМ разбором ``ObservationPolicy._decide()`` (см. докстринг
#: файла) на ``REAL_LEGACY_PUBLISH`` и дефолтной ``ObservationPolicyConfig()``
#: (в боевом ``system.yaml`` секции ``observability.observation`` нет —
#: действуют дефолты L0: ``subtree_enabled=True``, ``subtree_interval_sec=0.0``
#: (Р-11, Ф2 задача 2.11, 2026-09-03 — было ``1.0`` до этого решения),
#: ``rules={}``). Независимо подтверждено вторым источником: тот же боевой
#: конфиг ЦЕЛИКОМ (под именем ``PROD``) уже живёт в
#: ``test_observation_policy_review_f4.py::TestAWhitelistEntryOutranksTheSubtreeFrequencyToo``
#: (её ``test_the_subtree_frequency_does_not_reach_a_whitelisted_name`` задаёт
#: ``subtree_interval_sec`` ЯВНО, не дефолтом, — 0.2 — но подтверждает тот же
#: МЕХАНИЗМ: ``fps`` остаётся легаси-белым-списком (``1.0``, не трогается
#: значением поддерева) вне зависимости от него, а ``drops`` всегда следует за
#: ``subtree_default`` — при дефолте L0 это ``0.0``, что и стоит в таблице
#: ниже).
PATHS_AND_EXPECTED: dict[str, tuple[str, bool, float]] = {
    # Плоскость фреймворка (``processes.<p>.state.<имя>``) — решает ИМЕННО
    # легаси-секция: путь не попадает под ``PORT_SUBTREE_PATTERN``
    # (``processes.*.state.plugins.**``), поддерево порта тут не кандидат.
    "fps": (f"processes.{PROC}.state.fps", True, 1.0),  # явная запись metrics.fps
    "latency_ms": (f"processes.{PROC}.state.latency_ms", True, 1.0),  # явная запись metrics.latency_ms
    "effective_hz": (f"processes.{PROC}.state.effective_hz", False, 1.0),  # зонтик default_enabled=False
    "cycle_duration_ms": (f"processes.{PROC}.state.cycle_duration_ms", False, 1.0),  # зонтик
    "shm": (f"processes.{PROC}.state.shm", False, 1.0),  # зонтик
    # Плоскость плагинных писателей (``processes.<p>.state.plugins.<w>.<имя>``)
    # — решает ДЕФОЛТ ПОДДЕРЕВА ПОРТА (subtree_default), НЕ зонтик легаси:
    # ни одно из трёх имён не перечислено в metrics явно, а
    # PORT_SUBTREE_PATTERN совпадает раньше, чем алгоритм доходит до умолчания
    # default_enabled. Это ровно та ловушка, которую задание тестеру называет
    # "КРИТИЧНО" — здесь она для плоскости УРОВНЕЙ (не чисел): наивная
    # трансляция, которая подняла бы зонтик default_enabled на ступень не
    # ниже TIER_SUBTREE_DEFAULT, погасила бы эти три пути молча.
    # Р-11 (Ф2, задача 2.11, 2026-09-03): дефолт поддерева сменился с 1.0 на
    # 0.0 — «не чаще такта, без дополнительного троттла». Три пути ниже
    # решаются ИМЕННО этим дефолтом (subtree_default), не легаси-зонтиком.
    "capture_fps": (f"processes.{PROC}.state.plugins.{WRITER}.capture_fps", True, 0.0),
    "frame_count": (f"processes.{PROC}.state.plugins.{WRITER}.frame_count", True, 0.0),
    "drops": (f"processes.{PROC}.state.plugins.{WRITER}.drops", True, 0.0),
}


# =============================================================================
# АК1 — паритетный тест: 8 имён метрик, литералы "до" == "после"
# =============================================================================
class TestLegacyParityAcrossEightMetrics:
    """Паритет «до/после» на боевом конфиге прототипа, литералы по 8 именам.

    **Законно ЗЕЛЁН на этом коммите** — движок политики по обе стороны
    сравнения один и тот же код, паритет «X == X» тривиален. Осмысленным тест
    становится ПОСЛЕ Task 2.5: он обязан остаться зелёным С ТЕМИ ЖЕ ЧИСЛАМИ,
    когда легаси-чтение переедет в ``observation.rules``.

    Конкретная опасность, которую тест ловит (а не просто «что-то могло
    сломаться»): если трансляция ``default_enabled`` подключится к резолву на
    ступени не ниже ``TIER_SUBTREE_DEFAULT``, дефолт поддерева перестанет
    побеждать над легаси-зонтиком для ПЛАГИННЫХ путей — ``capture_fps`` /
    ``frame_count`` / ``drops`` молча переключатся на ``enabled=False``. Три
    из восьми строк таблицы существуют именно ради этого случая.
    """

    @pytest.mark.parametrize("metric_name", sorted(PATHS_AND_EXPECTED))
    def test_decision_matches_pre_change_literal(self, metric_name: str) -> None:
        path, expected_enabled, expected_interval = PATHS_AND_EXPECTED[metric_name]
        policy = _policy({}, publish=REAL_LEGACY_PUBLISH)
        decision = policy.resolve(path)

        assert decision.enabled is expected_enabled, (
            f"{metric_name} ({path}): enabled={decision.enabled}, ожидался {expected_enabled} "
            f"(паритет с состоянием ДО Task 2.5 нарушен; source={decision.source!r})"
        )
        assert decision.interval_sec == pytest.approx(expected_interval), (
            f"{metric_name} ({path}): interval_sec={decision.interval_sec}, ожидался {expected_interval} "
            f"(паритет с состоянием ДО Task 2.5 нарушен; source={decision.source!r})"
        )


# =============================================================================
# АК2 — readback называет легаси-происхождение дословно
# =============================================================================
class TestReadbackShowsLegacyProvenance:
    """Правило легаси-происхождения показывает ``source: legacy:telemetry.publish``.

    Сегодня — ``SOURCE_WHITELIST`` (буквально строка ``"whitelist"``) что для
    именованной записи (``metrics.fps``, ступень ``TIER_LEGACY_ENTRY``), что
    для БЕЗЫМЯННОГО зонтика (``default_enabled``, ступень ``TIER_UMBRELLA``) —
    см. ``test_observation_policy_review_f4.py::TestExplicitOperatorEntryBeatsADefault``
    (``decision.source == SOURCE_WHITELIST``, дословно). КРАСНЫЙ сегодня.
    """

    LEGACY = {"default_enabled": False, "metrics": {"fps": {"enabled": True, "interval_sec": 1.0}}}

    def test_named_legacy_entry_shows_legacy_provenance(self) -> None:
        """Именованная запись ``metrics.fps`` на плоскости фреймворка."""
        policy = _policy({}, publish=self.LEGACY)
        decision = policy.resolve(f"processes.{PROC}.state.fps")
        assert decision.source == LEGACY_PROVENANCE, (
            f"readback не называет легаси-источник дословно: source={decision.source!r}, "
            f"ожидание критерия приёмки — {LEGACY_PROVENANCE!r}"
        )

    def test_provenance_for_readback_surface_agrees(self) -> None:
        """Тот же факт через ``provenance_for`` — метод, которым реально кормится
        readback ``introspect.observability.observation.sources``
        (``managers/observability_wiring.py:451``, ``_observation_policy_report``,
        зовёт ИМЕННО ``provenance_for`` по путям, реально публикуемым портом).
        Путь — плагинный: та секция readback'а строит провенанс только по
        ``plugin_metric_path``, framework-плоскость (голый ``processes.<p>.state.fps``)
        в неё не попадает вовсе.
        """
        policy = _policy({}, publish=self.LEGACY)
        path = f"processes.{PROC}.state.plugins.{WRITER}.fps"
        prov = policy.provenance_for([path])
        assert prov[path]["source"] == LEGACY_PROVENANCE, prov


# =============================================================================
# АК3 — telemetry.reconfigure пишет правила ТЕМ ЖЕ путём, что и конфиг
# =============================================================================
class TestReconfigureRoutesThroughTheSameTranslator:
    """``telemetry.reconfigure`` не второй, отдельный механизм.

    Сегодня ``ProcessHeartbeat._make_gate`` держит легаси ОТДЕЛЬНЫМ параметром
    ``legacy=`` у ``ObservationPolicy`` — что на загрузке, что на
    ``telemetry.reconfigure`` (``process_heartbeat.py:604-629`` на этом
    коммите, метод один — ``_make_gate`` — но легаси в ``.config.rules`` не
    попадает НИКОГДА, он живёт отдельно). Доказательство в две половины:

      (а) поведенческая — рантайм-команда даёт ТОТ ЖЕ ``source``, что и
          загрузочная конструкция (см. класс АК2 выше);
      (б) структурная — ``.config.rules`` (то, что реально сериализуется как
          ``observation.rules``) РАСТЁТ от ``telemetry.reconfigure``. Точный
          текст ключа-паттерна трансляции НЕ угадывается (см. отчёт
          тестера) — тест смотрит только на факт роста, не на конкретный
          паттерн.

    Обе КРАСНЫЕ сегодня.
    """

    LEGACY_PUBLISH = {"default_enabled": False, "metrics": {"fps": {"enabled": True, "interval_sec": 1.0}}}

    def test_reconfigure_gives_the_same_provenance_as_load(self) -> None:
        svc, cm = _make()
        res = cm.dispatch("telemetry.reconfigure", {"publish": self.LEGACY_PUBLISH})
        assert res["success"] is True and res["applied"] == {"publish": True}, res

        process = str(getattr(svc._heartbeat._services, "name", ""))
        decision = svc._heartbeat._observation_policy.resolve(f"processes.{process}.state.fps")
        assert decision.source == LEGACY_PROVENANCE, (
            f"telemetry.reconfigure даёт другой source ({decision.source!r}), чем загрузочная "
            f"дорога ({LEGACY_PROVENANCE!r} по АК2) — вторая дорога жива"
        )

    def test_reconfigure_grows_observation_rules_not_a_side_channel(self) -> None:
        svc, cm = _make()
        hb = svc._heartbeat
        before = len(hb._observation_policy.config.rules) if hb._observation_policy is not None else 0

        res = cm.dispatch("telemetry.reconfigure", {"publish": self.LEGACY_PUBLISH})
        assert res["success"] is True, res

        after = len(hb._observation_policy.config.rules)
        assert after > before, (
            f"telemetry.reconfigure не перевёл легаси-секцию в observation.rules "
            f"(было {before} правил, стало {after}) — легаси по-прежнему едет отдельным "
            "параметром `legacy=`, а не как правила"
        )


# =============================================================================
# АК4 — один дефолт: default_enabled больше не второй зонтик рядом с
# subtree_enabled
# =============================================================================
class TestUmbrellaDefaultNoLongerASeparateWhitelistTier:
    """Зонтичный ``default_enabled`` перестаёт быть ОТДЕЛЬНОЙ, самостоятельно
    резолвящейся веткой (``TIER_UMBRELLA``/``SOURCE_WHITELIST``) рядом со
    ступенью дефолта поддерева порта (``TIER_SUBTREE_DEFAULT``/``subtree_enabled``).

    **Оговорка о неоднозначности (см. отчёт тестера).** Формулировка критерия
    ("`default_enabled` → `subtree_enabled`, один дефолт") допускает как
    минимум два прочтения:
      (i) легаси-умолчание перестаёт быть ЖИВОЙ, отдельно резолвящейся веткой
          кода и говорит ТЕМ ЖЕ голосом (``source``), что и именованная запись
          легаси, — не меняя при этом СВОЙ адресный охват (эффект на
          ``effective_hz`` остаётся ``enabled=False``, как и раньше, — см. АК1);
      (ii) ``subtree_enabled`` расширяет СВОЙ охват на весь ``**`` и
          буквально ЗАМЕНЯЕТ легаси-зонтик как единственный программный дефолт.

    Тест ниже проверяет (i) — узкое, наблюдаемое через уже существующий API
    прочтение, — и НЕ проверяет (ii): решать между ними — не дело тестера,
    формулировка задачи не называет, какой ``ObservationPolicyConfig``-флаг
    станет владельцем эффекта. Если реализация выберет (ii), этот тест может
    потребовать пересмотра — см. отчёт.
    """

    LEGACY = {"default_enabled": False, "metrics": {"fps": {"enabled": True, "interval_sec": 1.0}}}

    def test_umbrella_case_shows_the_same_legacy_provenance_as_the_named_entry(self) -> None:
        policy = _policy({}, publish=self.LEGACY)
        # effective_hz: не в metrics, не под processes.*.state.plugins.** —
        # сегодня закрывается ИСКЛЮЧИТЕЛЬНО зонтиком default_enabled
        # (TIER_UMBRELLA, source='whitelist', pattern='**').
        decision = policy.resolve(f"processes.{PROC}.state.effective_hz")
        assert decision.source == LEGACY_PROVENANCE, (
            f"зонтичный default_enabled всё ещё отвечает отдельным source ({decision.source!r}), "
            f"а не {LEGACY_PROVENANCE!r} — второй зонтик рядом с subtree_enabled жив"
        )
        # Поведение (АК1) обязано пережить смену провенанса дословно.
        assert decision.enabled is False, (
            f"зонтик сменил ПОВЕДЕНИЕ (enabled={decision.enabled}), а не только провенанс — "
            "это уже не задача 2.5, а разрыв паритета АК1"
        )


# =============================================================================
# Явный симметричный контроль: без легаси-секции вовсе поведение НЕ трогается
# (SOURCE_UNGATED — третье состояние, вне охвата Task 2.5) — страховка, что
# тесты выше не начнут молча ловить исчезновение самого легаси-механизма.
# =============================================================================
def test_control_no_legacy_section_is_out_of_scope_and_stays_ungated() -> None:
    """Якорь-контроль: гейта без легаси нет вовсе (``SOURCE_UNGATED``, паритет
    с ``ProcessHeartbeat._build_telemetry_gate() -> None``, докстринг класса
    ``ObservationPolicy``). Task 2.5 эту ветку не трогает — заявлено только
    про перевод ``telemetry.publish`` как ВХОДА; тест здесь фиксирует, что
    отсутствие секции по-прежнему означает «гейта нет», а не «зонтик закрыт».
    """
    policy = ObservationPolicy(ObservationPolicyConfig(), None)
    decision = policy.resolve(f"processes.{PROC}.state.effective_hz")
    assert decision.enabled is True, decision
    assert decision.source == "ungated", decision
