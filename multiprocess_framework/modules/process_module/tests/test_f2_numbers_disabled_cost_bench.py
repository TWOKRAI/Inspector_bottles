# -*- coding: utf-8 -*-
"""Task 2.10 (M3, В-4) + добор Р-12: бенч «выключенная метрика не дороже гейта» — в дереве.

**Зачем этот файл.** Главный перф-критерий Task 2.1 (шаг 5: «выключенная метрика
≤ 0.5 мкс, цель — цена гейта») до этой задачи жил только в тексте плана
(``phase-2-one-policy.md``) — воспроизвести его одной командой было нечем, и
ревью назвало это находкой М3/В-4. Здесь тот же замер приезжает В ДЕРЕВО, форма
взята дословно у соседа
``process_module/tests/test_plugin_stats_road.py::TestTheCostOfTheHotPath`` —
БОЕВОЙ стенд (настоящие ``StatsManager`` + ``ObservationManager`` + гейт с
политикой), а не дубль, по тому же доводу: фейковый харнесс доказывает харнесс,
а не цену.

**Три числа, один гейтуется.** Шаг 2 задачи:

* (а) ``record_metric`` метрики, запрещённой правилом, через БОЕВОЙ порт;
* (б) голый ``policy.resolve(path)`` на прогретом кэше (задача 2.4) — справочно;
* (в) ``record_metric`` РАЗРЕШЁННОЙ метрики той же дорогой.

Гейтуется ОТНОШЕНИЕ (а)/(в), а не абсолют: разность двух шумных величин на
общей машине шумит сильнее каждой из них по отдельности (тот же довод Н-7,
которым Task 2.1 уже переписала свой гейт с дельты на отношение — см.
``test_plugin_stats_road.py``). (б) репортируется, но не гейтуется — это
диагностика «сколько стоит сам поиск в кэше», а не «во сколько раз дороже».

**Счётный сторож рядом** (Р-12, добор к Task 2.10, шаг 7) — тем же доводом, что
у соседа: тайминг-гейт любой ширины слеп к мелкой регрессии на шумной машине,
число python-вызовов от машины не зависит. Здесь свойство — КАЧЕСТВЕННОЕ
(«меньше», а не заданная кратность): выключенная метрика останавливается на
``gate.allow`` ДО ``_deliver_number``/``_emit_to_taps``, поэтому её дорога
короче структурно, а не только по времени — и это стерегётся литералами ОБОИХ
чисел (не разностью), как того требует добор.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from multiprocess_framework.modules.process_module.configs.observation_policy import (
    ObservationPolicy,
    ObservationPolicyConfig,
)
from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import MetricRule
from multiprocess_framework.modules.statistics_module.core.stats_manager import StatsManager
from multiprocess_framework.modules.statistics_module.observation.observation_manager import ObservationManager
from multiprocess_framework.modules.tests._road_cost import (
    count_calls,
    count_instructions,
    peak_alloc,
    report as _report,
    timed_pair,
)

#: Процесс стенда — сегмент пути правила (Р-2а: ``processes.<p>.stats.<имя>``).
_PROCESS = "task210_cost_probe"
_DISABLED_METRIC = "task210_disabled_metric"
_ENABLED_METRIC = "task210_enabled_metric"

#: Инструкций байткода на дорогах — сняты В ЭТОМ ЖЕ харнессе: число зависит от
#: того, как устроена лямбда (замыкание на одну инструкцию дороже модульной
#: функции — ``PUSH_NULL`` + ``LOAD_DEREF`` вместо ``LOAD_GLOBAL``), поэтому
#: переносить чужой замер нельзя. Инъекция E1 (сборка записи ПЕРЕД гейтом):
#: выключенная 139 → **150**, красный в обоих режимах покрытия.
#:
#: **Литералы привязаны к CPython 3.12.** Смена минорной версии двигает раскладку
#: опкодов и покрасит сторожа без регрессии; проверять в порядке «сначала версия
#: интерпретатора, потом дорога».
DISABLED_INSTRUCTIONS = 139
ENABLED_INSTRUCTIONS = 607


def _wired_stand() -> tuple[StatsManager, ObservationManager, ObservationPolicy]:
    """Настоящие порт + менеджер + политика, связанные как ``ProcessManagers.create_all``.

    Правило запрещает РОВНО ``_DISABLED_METRIC``; ``_ENABLED_METRIC`` в
    ``rules`` не упомянут и падает на дефолт поддерева плоскости чисел
    (:data:`~...configs.observation_policy.STATS_SUBTREE_PATTERN`,
    ``enabled=True, interval_sec=0.0`` — тот же дефолт, каким живёт любая
    метрика плагина без единой правки конфига).
    """
    policy = ObservationPolicy(
        ObservationPolicyConfig(rules={f"processes.{_PROCESS}.stats.{_DISABLED_METRIC}": MetricRule(enabled=False)}),
        legacy=None,
    )
    port = ObservationManager(manager_name=f"port_{_PROCESS}", process=SimpleNamespace(name=_PROCESS))
    assert port.initialize(), "стенд сломан ДО замера: порт не поднялся"
    port.attach_numbers_policy(policy)

    mgr = StatsManager(
        manager_name=f"stats_{_PROCESS}",
        config={
            "enable_logging": False,
            "aggregation_interval": 300.0,
            "flush_interval": 300.0,
            "channels": {"file_stats": {"enabled": False}},
        },
    )
    assert mgr.initialize(), "стенд сломан ДО замера: StatsManager не поднялся"
    assert mgr.attach_observation_port(port) is True, "стенд сломан ДО замера: attach_observation_port вернул False"
    return mgr, port, policy


class TestTheDisabledMetricCostsNoMoreThanTheGate:
    """Task 2.1, шаг 5 — воспроизводимый бенч дерева, а не число из плана."""

    def test_disabled_vs_enabled_ratio_and_call_count(self, capsys: "pytest.CaptureFixture") -> None:
        """(а)/(в) отношением, (б) справочно, плюс счётный сторож «меньше вызовов»."""
        mgr, port, policy = _wired_stand()
        tags = {"probe": "task210"}
        try:
            disabled_call = lambda: mgr.record_metric(_DISABLED_METRIC, 1, tags)  # noqa: E731
            enabled_call = lambda: mgr.record_metric(_ENABLED_METRIC, 1, tags)  # noqa: E731
            disabled_path = f"processes.{_PROCESS}.stats.{_DISABLED_METRIC}"
            resolve_call = lambda: policy.resolve(disabled_path)  # noqa: E731

            # Прогрев ДО замера — задача 2.4 кэширует решение политики НА ПУТЬ,
            # и первый вызов каждой стороны платит нерепрезентативный холодный
            # резолв (плюс, для включённой метрики, разовое создание агрегата в
            # StatsManager). Разница (а) против (в) обязана отражать цену
            # ГЕЙТА на прогретом кэше, а не цену первого касания.
            disabled_call()
            enabled_call()
            resolve_call()

            through_disabled, through_enabled = timed_pair(disabled_call, enabled_call, repeats=20_000)
            ratio = through_disabled / through_enabled

            # (б) — НЕ чередование: обе стороны здесь один и тот же вызов,
            # сравнивать нечего, и работу делает минимум из пяти окон, а не
            # порядок блоков. Прежняя редакция комментария объявляла это
            # «устранением окна загрузки машины» — неверно, и вдвойне: (б)
            # снимается ОТДЕЛЬНЫМ вызовом ``timed_pair``, то есть в другом окне
            # загрузки, чем (а)/(в). С ними (б) сопоставимо только по порядку
            # величины; нужна точная сопоставимость — парить одним вызовом.
            per_call_resolve, _per_call_resolve_again = timed_pair(resolve_call, resolve_call, repeats=20_000)

            _report(capsys, "\nЦена выключенной метрики (Task 2.1, шаг 5 / Task 2.10):")
            _report(capsys, f"  (а) выключенная через боевой порт: {through_disabled * 1e6:.3f} мкс")
            _report(capsys, f"  (в) включённая тем же путём:        {through_enabled * 1e6:.3f} мкс")
            _report(capsys, f"  (б) голый policy.resolve на кэше:   {per_call_resolve * 1e6:.3f} мкс  (справочно)")
            _report(capsys, f"  отношение (а)/(в):                  {ratio:.3f}x  (гейтуется, потолок 0.3)")

            # Потолок 0.3 — рекомендация ревью (добор Р-12, шаг 2), измеренные
            # ~0.15; абсолют (а) и (б) репортируются, не гейтуются — та же
            # причина, что у соседа: абсолют шумной величины на общей машине
            # краснеет без регрессии (Н-7).
            assert ratio < 0.3, (
                f"выключенная метрика подорожала относительно включённой: {ratio:.3f}x "
                f"(выключенная {through_disabled * 1e6:.3f} мкс, включённая {through_enabled * 1e6:.3f} мкс)"
            )

            # Счётный сторож (добор Р-12, шаг 7): выключенная метрика ОБЯЗАНА
            # делать строго меньше python-вызовов, чем включённая, — литералом
            # ОБОИХ чисел, не разностью. Гейт стоит ДО сборки записи
            # (``ObservationPort._route_number``), поэтому выключенная дорога
            # останавливается на ``gate.allow`` и никогда не доходит до
            # ``_deliver_number``/``_emit_to_taps`` — структурно короче, не
            # только по времени.
            #
            # ПАРАМИ (py, C), а не одним py-числом: ``d.copy()`` и ``with lock:``
            # дают py+0 и C+1, то есть только-py сторож слеп ровно к тем
            # регрессиям, ради которых заведён (замер соседа, добор Р-12).
            # C-число здесь устойчиво: на этой дороге нет ни одного ``import``,
            # из-за которого гулял литерал фасада, — сверено в голом процессе,
            # под PySide6 и под coverage.
            disabled = count_calls(disabled_call)
            enabled = count_calls(enabled_call)
            _report(capsys, f"  вызовов py/C (выключенная / включённая): {disabled} / {enabled}")

            assert disabled == (6, 5), (
                f"дорога выключенной метрики завела новую работу: {disabled} вместо (6, 5) (py, C)"
            )
            assert enabled == (28, 30), f"дорога включённой метрики изменилась: {enabled} вместо (28, 30) (py, C)"

            # ТРЕТИЙ объектив — и без него приёмочный критерий этой задачи
            # («инъекция E1: сборка записи ПЕРЕД гейтом → бенч красный») НЕ
            # ВЫПОЛНЯЛСЯ. Найдено ревью, а не автором: заплата E1 проходила
            # мимо ОБЕИХ половин счётной пары (конструктор типа не даёт события
            # ``c_call``: ``dict(d)``, ``{**d}`` и словарный литерал неотличимы
            # от ``lambda: None``) и укладывалась в тайминг-потолок — дельта
            # отношения всего 0.048.
            #
            # Объектив — СЧЁТ ИНСТРУКЦИЙ, литералом обоих чисел, как у пары
            # вызовов. Почему литерал, а не отношение (первая редакция гейтовала
            # отношение пиков ``tracemalloc``, потолок 0.46):
            #
            #   * отношение ПРОБИВАЕМО СО СТОРОНЫ ЗНАМЕНАТЕЛЯ. Замер: E1 плюс
            #     ~600 байт транзиентной работы на ВКЛЮЧЁННОЙ дороге даёт
            #     731/1526 = 0.479 — E1 проходит зелёным, ничего не сломав в
            #     себе. У литерала выключенной дороги знаменателя нет вовсе;
            #   * пик аллокаций зависит от ЯДРА трассировщика, а не только от
            #     версии: на одной дороге CTracer даёт 0.417, ``COVERAGE_CORE=
            #     sysmon`` — 0.367, ``pytrace`` — 0.440. Порог на такой величине
            #     — Н-7 в другом пальто. Счёт инструкций одинаков во всех
            #     четырёх состояниях, включая оба ядра coverage.
            #
            # Довод Н-7 («отношение, а не абсолют») здесь НЕ применяется: он про
            # ШУМНЫЕ величины, а счёт инструкций — событие байткода. Первая
            # редакция перенесла форму по аналогии с соседним гейтом, и это была
            # ошибка того же рода, что три ложных утверждения в старом
            # комментарии соседа.
            disabled_instr = count_instructions(disabled_call)
            enabled_instr = count_instructions(enabled_call)
            _report(capsys, f"  инструкций (выключенная / включённая): {disabled_instr} / {enabled_instr}")

            assert disabled_instr == DISABLED_INSTRUCTIONS, (
                f"дорога выключенной метрики исполняет {disabled_instr} инструкций вместо "
                f"{DISABLED_INSTRUCTIONS}: если число ВЫРОСЛО — на запрещённой дороге появилась "
                "работа, и первый подозреваемый — сборка записи ПЕРЕД гейтом"
            )
            assert enabled_instr == ENABLED_INSTRUCTIONS, (
                f"дорога включённой метрики исполняет {enabled_instr} инструкций вместо {ENABLED_INSTRUCTIONS}"
            )

            # Пик аллокаций — СПРАВОЧНО, без гейта: величина зависит от ядра
            # трассировщика (см. выше), гейтовать её значило бы завести порог,
            # который молча краснеет от смены ``COVERAGE_CORE``.
            disabled_bytes = peak_alloc(disabled_call)
            enabled_bytes = peak_alloc(enabled_call)
            _report(
                capsys,
                f"  пик памяти (выкл/вкл): {disabled_bytes} / {enabled_bytes} байт, "
                f"отношение {disabled_bytes / enabled_bytes:.3f}x  (справочно, НЕ гейтуется)",
            )
        finally:
            mgr.shutdown()
            port.shutdown()
