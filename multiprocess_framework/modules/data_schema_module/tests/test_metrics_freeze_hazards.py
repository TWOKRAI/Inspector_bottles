# -*- coding: utf-8 -*-
"""
Авторские тесты на опасности заморозки MetricsCollector (S-27, Task 5.4).

Приёмочный набор (``test_metrics_ceiling_acceptance.py``) написан независимым
тестером от постановки — он доказывает, что контракт К1-К5 выполнен на
последовательных вызовах. Здесь — то, что видно только автору реализации:
опасности МЕХАНИЗМА, а не формы контракта.

    Х1 — глобальный ``_metrics_collector`` один на процесс и уже наполнен на
         импорте: тест без изоляции измерил бы ЧУЖИЕ числа (та самая ловушка,
         которую acceptance-файл обходит через свежий ``MetricsCollector()``).
    Х2 — потолок ``_timings`` и счётчик отброшенного — это read-modify-write
         над общим состоянием; без ``RLock`` конкурентная запись может дать
         bucket длиннее потолка ИЛИ потерять часть дропов.
    Х3 — голос «никто не читает» — read-then-write флага; без блокировки два
         потока, оба заставшие ``_voice_sounded is False`` одновременно на
         первом вызове, оба бы залогировали голос (дубль).
    Х4 — ``record_metric`` (К4: counter-семантика) — тоже read-modify-write;
         без блокировки конкурентные прибавления теряют часть слагаемых.

Правила автора (см. режим dev в .claude/modes): литерал в ожидании, а не
диапазон; наблюдаемый эффект публичного API вместо имени приватного
атрибута; квантор — минимум на двух вызовах/потоках; у отрицательного
критерия — якорь существования в том же тесте.
"""

from __future__ import annotations

import logging
import re
import threading

from ..core.metrics import MetricsCollector, TIMINGS_CEILING, get_metrics_collector


# ============================================================================
# Х1 — глобальный singleton общий на процесс и наполнен уже на импорте
# ============================================================================


def test_global_singleton_is_shared_and_prepopulated_at_import():
    """Х1: get_metrics_collector() — ОДИН и тот же объект, уже непустой.

    Квантор: вызываем get_metrics_collector() дважды и требуем идентичность
    (``is``) — не "похожие данные", а буквально один объект. Якорь
    существования: свежий ``MetricsCollector()`` пуст — это доказывает, что
    непустота глобального ниже не подделка сломанного счётчика (который был
    бы одинаково "непуст" и для чужого, и для своего экземпляра).
    """
    first = get_metrics_collector()
    second = get_metrics_collector()
    assert first is second, (
        "get_metrics_collector() обязан возвращать ОДИН объект на процесс — "
        "иначе тест, ожидающий изоляции через него, тихо смотрит на чужой инстанс"
    )

    # Якорь существования: свежий экземпляр демонстрирует, что "пусто" — это
    # ДОСТИЖИМОЕ состояние счётчика, а не то, чего сборщик в принципе не умеет.
    fresh = MetricsCollector()
    assert fresh.get_metrics()["counters"] == {}, (
        "свежий MetricsCollector() обязан быть пуст — иначе непустота "
        "глобального ниже ничего не доказывает про изоляцию"
    )

    assert len(first.get_metrics()["counters"]) >= 1, (
        "process-wide singleton обязан быть уже наполнен на момент импорта "
        "модуля (регистрация схем через registry/factory на старте) — тест "
        "без изоляции (через свежий MetricsCollector()) считал бы эти чужие "
        "числа своими"
    )


# ============================================================================
# Х2 — потолок _timings и счётчик потерь под конкурентной записью
# ============================================================================


def test_ceiling_and_drop_counter_survive_concurrent_writes():
    """Х2: потолок и dropped — ЛИТЕРАЛЫ даже под гонкой 8 потоков.

    check-then-append (``len(bucket) >= TIMINGS_CEILING``) без блокировки —
    классический TOCTOU: несколько потоков проходят проверку одновременно и
    аппендят сверх потолка. Ожидание — не "count <= TIMINGS_CEILING" (это
    было бы верно и для сломанной защиты, зафиксировавшей меньшее число), а
    РОВНО TIMINGS_CEILING и РОВНО (всего_вызовов - TIMINGS_CEILING) потерь.
    """
    collector = MetricsCollector()
    name = "hazard.concurrent.timing"
    threads_n = 8
    calls_per_thread = 400  # 3200 суммарно, заведомо больше потолка 1000
    total_calls = threads_n * calls_per_thread

    def worker() -> None:
        for _ in range(calls_per_thread):
            collector.record_timing(name, 0.001)

    threads = [threading.Thread(target=worker) for _ in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    agg = collector.get_metrics()["timings"][name]
    assert agg["count"] == TIMINGS_CEILING, (
        f"после {total_calls} конкурентных вызовов ({threads_n} потоков) count "
        f"обязан застыть РОВНО на {TIMINGS_CEILING}, получено {agg['count']!r} — "
        f"гонка check-then-append переполнила потолок"
    )
    assert agg["dropped"] == total_calls - TIMINGS_CEILING, (
        f"dropped обязан быть ЛИТЕРАЛОМ {total_calls - TIMINGS_CEILING} "
        f"(сам счётчик потерь тоже под гонкой — его инкремент обязан быть "
        f"атомарным), получено {agg['dropped']!r}"
    )


# ============================================================================
# Х3 — голос «никто не читает» звучит ровно один раз даже под гонкой
# ============================================================================

_VOICE_RE = re.compile(r"никто.*чита", re.IGNORECASE)


def test_voice_sounds_exactly_once_under_concurrent_first_calls(caplog):
    """Х3: 8 потоков одновременно бьют по первому вызову — голос всё равно один.

    Без блокировки вокруг read-then-write флага несколько потоков могли бы
    все застать ``_voice_sounded is False`` до того, как первый выставит
    True, и все бы залогировали. ``threading.Barrier`` синхронизирует старт,
    чтобы гонка была реальной, а не последовательной по факту планировщика.

    ЧЕСТНАЯ ОГОВОРКА (проверено инъекцией 2026-08-26, не вывод из головы):
    окно гонки здесь — два соседних байткода (``LOAD_ATTR``/``STORE_ATTR``),
    и на этой машине голый ``NoOpLock`` без искусственной задержки НЕ дал
    красного даже при заниженном ``sys.setswitchinterval`` и 16 потоках —
    CPython слишком редко переключает поток между такими соседними
    инструкциями. Красный воспроизведён ТОЛЬКО когда в критическую секцию
    была добавлена ``time.sleep()`` между чтением и записью флага (искажение
    самого кода, не тестового окружения) — тогда 8/8 потоков дали дубль.
    Это означает: тест доказывает поведение при НОРМАЛЬНОЙ конкурентности
    (не падает, не дублирует в типичном случае), но НЕ является надёжным
    стражем против будущего снятия ``self._lock`` конкретно здесь — снятие
    лока без соседней задержки может остаться незамеченным этим тестом.
    Корректность в этой точке опирается на code review (лок физически
    покрывает check-then-set), а не только на этот прогон.
    """
    caplog.set_level(logging.WARNING)
    collector = MetricsCollector()
    threads_n = 8
    barrier = threading.Barrier(threads_n)

    def worker(i: int) -> None:
        barrier.wait()
        collector.record_metric(f"hazard.voice.metric.{i}", 1)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    hits = [r for r in caplog.records if _VOICE_RE.search(r.getMessage())]
    assert len(hits) == 1, (
        f"голос «никто не читает» обязан прозвучать РОВНО один раз под гонкой "
        f"{threads_n} потоков на первом вызове, найдено {len(hits)}: "
        f"{[r.getMessage() for r in hits]!r}"
    )


# ============================================================================
# Х4 — record_metric (К4, counter-семантика) под конкурентной записью
# ============================================================================


def test_record_metric_additive_sum_survives_concurrent_writers():
    """Х4: сумма record_metric(name, 1) под гонкой — ЛИТЕРАЛ, не "меньше или равно".

    read-modify-write (``prev_value + value``) без блокировки теряет часть
    слагаемых при гонке двух потоков на одном ключе — итог был бы МЕНЬШЕ
    ожидаемой суммы, и без литерального ожидания потерю никто бы не заметил.
    """
    collector = MetricsCollector()
    name = "hazard.additive.metric"
    threads_n = 10
    calls_per_thread = 50
    total = threads_n * calls_per_thread

    def worker() -> None:
        for _ in range(calls_per_thread):
            collector.record_metric(name, 1)

    threads = [threading.Thread(target=worker) for _ in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stored = collector.get_metric(name)
    assert stored is not None
    assert stored["value"] == total, (
        f"сумма {threads_n} потоков × {calls_per_thread} record_metric(name, 1) "
        f"обязана быть ЛИТЕРАЛОМ {total}, получено {stored['value']!r} — "
        f"read-modify-write без блокировки потерял часть прибавлений"
    )


# --------------------------------------------------------------------------- #
# Находка инъекции J3 (владелец, 2026-08-26): голос ходит в logger_module
# ЛЕНИВО и вызывается уже на импорте пакета — кольцо импорта роняло всё.
# --------------------------------------------------------------------------- #


def test_the_voice_never_kills_the_package_when_the_logger_is_unreachable():
    """Недоступный логгер откладывает голос, а не роняет пакет и не глотает его.

    **Почему этот тест существует.** Голос звучит уже НА ИМПОРТЕ пакета:
    ``schema_registry``/``model_factory`` зовут ``increment_metric`` на своём
    старте, и к концу ``import data_schema_module`` в сборщике 22 счётчика,
    ``_voice_sounded is True``, ленивый логгер резолвнут. То есть ленивый
    ``from ...logger_module import get_std_logger`` выполняется ВНУТРИ импорта
    пакета и сегодня проходит только по счастливому порядку.

    Инъекция J3 (2026-08-26) показала порядок, в котором не проходит: со
    сломанным флагом «сказать один раз» голос зовётся на каждом вызове, и
    второй ловит кольцо — прогон падает целиком на conftest с
    ``ImportError: cannot import name 'get_std_logger' from partially
    initialized module``. Это был не «ноль красных», а сломанный сбор: 0
    собранных тестов вместо 563.

    Пара, как требует правило отрицательных критериев:

    * **отрицание** — логгер недоступен: вызов не бросает, флаг НЕ выставлен
      (иначе единственный голос был бы проглочен молча и не прозвучал бы уже
      никогда);
    * **якорь существования** — логгер вернулся: тот же сборщик говорит, и
      РОВНО один раз на двух вызовах (кванторная часть — на двух, не на одном).
    """
    from ..core import metrics as metrics_mod

    collector = metrics_mod.MetricsCollector()
    original = metrics_mod._std_logger
    said = []

    try:
        # --- отрицание: логгер недоступен ---
        metrics_mod._std_logger = lambda: None
        try:
            collector.record_metric("j3.probe", 1)
            collector.record_metric("j3.probe", 1)
        except Exception as exc:  # pragma: no cover — падение здесь и есть дефект
            raise AssertionError(f"недоступный логгер уронил запись метрики: {exc!r}") from exc

        assert collector._voice_sounded is False, (
            "флаг голоса выставлен при недоступном логгере — голос проглочен молча и не прозвучит уже никогда"
        )
        landed = collector.get_metric("j3.probe")
        assert landed["value"] == 2, f"запись метрики пострадала от недоступного логгера: {landed!r}"

        # --- якорь существования: логгер вернулся, голос звучит ровно один раз ---
        metrics_mod._std_logger = lambda: type("L", (), {"warning": lambda _s, *a, **k: said.append(a)})()
        collector.record_metric("j3.probe", 1)
        collector.record_metric("j3.probe", 1)
    finally:
        # Восстановление ОБЯЗАНО быть в finally, а не только в except: тест,
        # упавший на ассерте после подмены, оставил бы глобальную функцию
        # подменённой и отравил соседей. Поймано на себе же 2026-08-26 —
        # сосед ниже получал None вместо логгера и краснел по чужой причине.
        metrics_mod._std_logger = original

    assert len(said) == 1, f"голос прозвучал {len(said)} раз на двух вызовах, ожидался ровно 1"
    assert collector._voice_sounded is True, "после успешного голоса флаг обязан быть выставлен"


def test_std_logger_returns_none_instead_of_raising_on_a_circular_import():
    """``_std_logger`` обязан вернуть ``None``, а не пробросить ImportError.

    Прямой сторож на ветку ``except ImportError``: без неё кольцо импорта
    (воспроизведено J3) роняет весь пакет, а не одну строчку лога.

    Якорь существования — во второй половине: при исправном импорте та же
    функция отдаёт настоящий логгер с методом ``warning``.
    """
    import builtins

    from ..core import metrics as metrics_mod

    metrics_mod._logger = None
    real_import = builtins.__import__

    def _boom(name, *args, **kwargs):
        if "logger_module" in name:
            raise ImportError("partially initialized module (имитация кольца J3)")
        return real_import(name, *args, **kwargs)

    builtins.__import__ = _boom
    try:
        assert metrics_mod._std_logger() is None, "при кольце импорта ожидался None, а не логгер"
    finally:
        builtins.__import__ = real_import
        metrics_mod._logger = None

    # Якорь существования: импорт исправен → настоящий логгер.
    got = metrics_mod._std_logger()
    assert got is not None and callable(getattr(got, "warning", None)), (
        f"при исправном импорте ожидался логгер с warning(), получено {got!r}"
    )
