"""
Метрики для модуля data_schema.

Предоставляет интерфейс для записи метрик, которые могут быть использованы StatisticsManager.

S-27 (Ф5, Task 5.4, 2026-08-26): сборщик ЗАМОРОЖЕН с ГОЛОСОМ и ПОТОЛКОМ.
Инвентарь Task 5.1 нашёл 14 боевых вызывающих (``model_factory.py`` — 9,
``schema_registry.py`` — 5), но ни одного читателя ``get_metrics()`` и ни
одного ``reset()`` — числа копятся и никуда не уходят. Решение владельца:
не удалять (боевые сайты живы и правило проекта — «FREEZE, не KILL»), но и
не оставлять немым накопителем без потолка. Подробности и обоснование
числа потолка — ``DECISIONS.md`` этого модуля.
"""

from typing import Dict, Any, Optional
from functools import wraps
from threading import RLock
import time

# ЛЕНИВЫЙ импорт get_std_logger (S-27, Task 5.4): этот файл грузится как ЧАСТЬ
# core/__init__.py — то есть на LAYER 0 инициализации data_schema_module, до
# того, как пакет отдаёт SchemaBase наружу. logger_module (через
# configs/logger_manager_config.py → channel_routing_module → data_schema_module)
# на этом же старте тянет `from ...data_schema_module import SchemaBase` —
# импорт get_std_logger на уровне модуля здесь даёт РОВНО тот же цикл
# «partially initialized module», что уже описан в WHITELIST для
# registry/discovery.py и registry/process_registry.py (проверено
# воспроизведением: fresh `import data_schema_module` падает
# ImportError'ом на этой строке, если импорт не отложен). Резолвится
# лениво — при первом фактическом вызове, когда граф модулей уже собран.
_logger = None


def _std_logger():
    """Вернуть (и закэшировать) ``get_std_logger(__name__)`` — импорт ЛЕНИВЫЙ.

    **Ленивость обязательна, а не стилистична: модульный импорт роняет пакет.**
    Воспроизведено 2026-08-26 — строка ``from ...logger_module import
    get_std_logger`` на уровне модуля даёт при ``import
    multiprocess_framework.modules.data_schema_module``::

        File ".../channel_routing_module/core/config.py", line 34, in <module>
            from ...data_schema_module import (
        ImportError: cannot import name 'SchemaBase' from partially initialized
        module 'multiprocess_framework.modules.data_schema_module'
        (most likely due to a circular import)

    Кольцо замыкается НЕ напрямую через ``logger_module``, как можно подумать, а
    третьим модулем: ``core/metrics.py`` грузится как часть ``core/__init__.py``,
    то есть на самом раннем этапе инициализации пакета; ``logger_module`` на
    своём старте тянет ``channel_routing_module``, а тот в ``core/config.py``
    просит у ``data_schema_module`` ``SchemaBase`` — которого в частично
    инициализированном пакете ещё нет. Путь назван поимённо, потому что
    «почистить лишнюю ленивость» — ровно то, что здесь ломается, и по короткому
    «резолвим лениво» этого не восстановить.

    Кэш в модульном ``_logger`` — чтобы горячая дорога не платила за
    ``import``-lookup на каждый вызов; голос всё равно звучит один раз.
    """
    global _logger
    if _logger is None:
        try:
            from ...logger_module import get_std_logger
        except ImportError:
            # Частично инициализированный logger_module — голос ОТКЛАДЫВАЕТСЯ,
            # а не роняет пакет. Воспроизведено 2026-08-26 инъекцией J3: со
            # сломанным флагом «сказать один раз» голос звучит на КАЖДОМ
            # вызове, включая 22 вызова на импорте пакета, и второй из них
            # ловит кольцо — pytest падает на conftest с
            # ``ImportError: cannot import name 'get_std_logger' from
            # partially initialized module``. Сегодня это не срабатывает лишь
            # по счастливому порядку импорта; вернуть ``None`` дешевле, чем
            # зависеть от удачи.
            return None
        _logger = get_std_logger(__name__)
    return _logger


#: Потолок записей ``_timings`` на ОДИН ключ (S-27, К1). Литерал, а не расчёт
#: из кода под тестом — решение владельца Task 5.4 (2026-08-26). Ориентир:
#: ~35 байт/запись (число воспроизведения хозяина) × 1000 ~= 35 КБ на ключ —
#: разумная граница для «не должно расти неограниченно» при ~14 боевых
#: ключей ``data_schema.*``.
TIMINGS_CEILING = 1000


class MetricsCollector:
    """
    Сборщик метрик для data_schema.

    Используется для записи метрик операций, которые могут быть прочитаны StatisticsManager.

    S-27 (Task 5.4): ``_timings`` растёт до :data:`TIMINGS_CEILING` записей на
    ключ, дальше новые записи ОТБРАСЫВАЮТСЯ (не старые — см. ``record_timing``),
    а потеря считается явно и видна в ``get_metrics()["timings"][key]["dropped"]``.
    Сверх того — сборщик ОДИН РАЗ за жизнь экземпляра говорит через
    ``get_std_logger``, что накопленное никто не читает (боевых читателей
    ``get_metrics()``/``reset()`` — ноль, см. докстринг модуля).

    **Уровень голоса — DEBUG, а не WARNING (правка по ревью Ф5, S7).** Первая
    редакция писала WARNING, и ревью показало цену: голос звучит на импорте
    пакета, то есть по одной строке на КАЖДЫЙ процесс сборки — восемь WARNING
    на каждый подъём системы, бессрочно, плюс в stdout любого CLI, который
    импортирует ``data_schema_module``. При этом сообщение описывает
    СТАТИЧЕСКИЙ факт кода («читателей нет»), а не рантайм-происшествие: оно
    истинно всегда, пока читателя не добавят. WARNING, который всегда истинен,
    учит не читать WARNING'и — а плоскость логов этого проекта уже платила за
    шум (инцидент 645 МБ, 23% невидимых ошибок).

    Действенный рантайм-факт здесь другой — «потолок сработал, записи
    отброшены», — и он наблюдаем числом в
    ``get_metrics()["timings"][key]["dropped"]``. Заводить под него второй
    голос авансом не стали: по правилу проекта фича идёт после доказательства,
    что она нужна.

    Экземпляр потокобезопасен (``RLock`` на всё мутируемое состояние + флаг
    голоса) — глобальный ``_metrics_collector`` общий на процесс, и запись в
    него может идти из нескольких потоков одновременно.
    """

    def __init__(self):
        """Инициализация сборщика метрик."""
        self._metrics: Dict[str, Any] = {}
        self._counters: Dict[str, int] = {}
        self._timings: Dict[str, list] = {}
        self._timings_dropped: Dict[str, int] = {}
        self._voice_sounded = False
        self._lock = RLock()

    def _announce_no_reader_once(self) -> None:
        """Голос «меня никто не читает» — РОВНО один раз за жизнь экземпляра (К3).

        Флаг читается/пишется под тем же ``RLock``, что и остальное состояние:
        без этого два потока, оба заставшие ``_voice_sounded is False``, оба
        залогировали бы голос — то есть ровно тот дефект, который К3 и ловит,
        только гонкой, а не последовательными вызовами.
        """
        with self._lock:
            if self._voice_sounded:
                return
            log = _std_logger()
            if log is None:
                # Логгер ещё недоступен — флаг НЕ ставим, скажем на следующем
                # вызове. Иначе единственный голос был бы проглочен молча.
                return
            self._voice_sounded = True
        log.debug(
            "MetricsCollector (data_schema_module): собранные метрики никто не "
            "читает — get_metrics() ни разу не вызывается в боевом коде (S-27, "
            "инвентарь Task 5.1: 14 вызывающих record_timing/increment_metric, "
            "0 читателей). _timings заморожен потолком %s записей на ключ; "
            "новые записи сверх потолка отбрасываются и считаются явно.",
            TIMINGS_CEILING,
        )

    def record_metric(self, metric_name: str, value: Any = 1, tags: Optional[Dict[str, str]] = None):
        """
        Прибавить метрику (S-27, К4: counter-семантика, не перезапись).

        В этом проекте имя ``record_metric`` означает «прибавить», как и
        ``increment`` — три вызова ``record_metric(name, 1)`` дают
        ``value == 3``, а не ``1`` (было «последний вызов побеждает» до
        Task 5.4). Проверено перед правкой: в репозитории ни один боевой
        сайт и ни один существующий тест не зовёт эту функцию/метод напрямую —
        все 14 боевых вызывающих идут через ``record_timing``/``increment_metric``
        (см. отчёт по задаче), так что смена семантики никого не задевает.

        Args:
            metric_name: Имя метрики
            value: Прибавляемое значение
            tags: Теги метрики
        """
        self._announce_no_reader_once()
        key = self._make_key(metric_name, tags)
        with self._lock:
            previous = self._metrics.get(key)
            prev_value = previous["value"] if previous is not None else 0
            self._metrics[key] = {
                "name": metric_name,
                "value": prev_value + value,
                "tags": tags or {},
                "timestamp": time.time(),
            }

    def increment(self, metric_name: str, tags: Optional[Dict[str, str]] = None):
        """
        Увеличить счетчик метрики.

        Args:
            metric_name: Имя метрики
            tags: Теги метрики
        """
        self._announce_no_reader_once()
        key = self._make_key(metric_name, tags)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + 1

    def record_timing(self, metric_name: str, duration: float, tags: Optional[Dict[str, str]] = None):
        """
        Записать время выполнения операции.

        S-27 (К1, К2): хранилище на ключ ограничено :data:`TIMINGS_CEILING`
        записями. При упоре в потолок отбрасывается НОВАЯ запись (старые
        остаются) — у тайминга нет «последнее важнее», а усечение хвоста
        (не головы) даёт стабильную по времени выборку начала вместо
        дрейфующего скользящего окна; отбросить старые пришлось бы ценой
        сдвига всего списка на каждой записи (O(n) вместо O(1)), а с
        боевыми ключами это горячий путь. Потеря считается явно в
        ``self._timings_dropped`` и видна через
        ``get_metrics()["timings"][key]["dropped"]`` — не молчит.

        Args:
            metric_name: Имя метрики
            duration: Время выполнения в секундах
            tags: Теги метрики
        """
        self._announce_no_reader_once()
        key = self._make_key(metric_name, tags)
        with self._lock:
            bucket = self._timings.setdefault(key, [])
            if len(bucket) >= TIMINGS_CEILING:
                self._timings_dropped[key] = self._timings_dropped.get(key, 0) + 1
                return
            bucket.append({"duration": duration, "timestamp": time.time(), "tags": tags or {}})

    def get_metrics(self) -> Dict[str, Any]:
        """
        Получить все метрики.

        Returns:
            Словарь с метриками. Каждая агрегация в ``timings`` несёт поле
            ``dropped`` (S-27, К2) — число записей, отброшенных потолком
            :data:`TIMINGS_CEILING` для этого ключа; 0, если потолок ещё не
            достигнут.
        """
        with self._lock:
            return {
                "metrics": self._metrics.copy(),
                "counters": self._counters.copy(),
                "timings": {
                    key: {
                        "count": len(timings),
                        "total": sum(t["duration"] for t in timings),
                        "avg": sum(t["duration"] for t in timings) / len(timings) if timings else 0,
                        "min": min(t["duration"] for t in timings) if timings else 0,
                        "max": max(t["duration"] for t in timings) if timings else 0,
                        "dropped": self._timings_dropped.get(key, 0),
                    }
                    for key, timings in self._timings.items()
                },
            }

    def get_metric(self, metric_name: str, tags: Optional[Dict[str, str]] = None) -> Optional[Any]:
        """
        Получить конкретную метрику.

        Args:
            metric_name: Имя метрики
            tags: Теги метрики

        Returns:
            Значение метрики или None
        """
        with self._lock:
            return self._metrics.get(self._make_key(metric_name, tags))

    def reset(self):
        """Сбросить все метрики.

        ``_voice_sounded`` НЕ сбрасывается — голос про жизнь экземпляра
        (К3: «ровно один раз»), а не про накопленные в нём данные.
        """
        with self._lock:
            self._metrics.clear()
            self._counters.clear()
            self._timings.clear()
            self._timings_dropped.clear()

    def _make_key(self, metric_name: str, tags: Optional[Dict[str, str]]) -> str:
        """Создать ключ для метрики."""
        if tags:
            tag_str = "_".join(f"{k}={v}" for k, v in sorted(tags.items()))
            return f"{metric_name}_{tag_str}"
        return metric_name


# Глобальный экземпляр сборщика метрик
_metrics_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """Получить глобальный экземпляр сборщика метрик."""
    return _metrics_collector


def record_metric(metric_name: str, value: Any = 1, tags: Optional[Dict[str, str]] = None):
    """Записать метрику (удобная функция)."""
    _metrics_collector.record_metric(metric_name, value, tags)


def increment_metric(metric_name: str, tags: Optional[Dict[str, str]] = None):
    """Увеличить счетчик метрики (удобная функция)."""
    _metrics_collector.increment(metric_name, tags)


def record_timing(metric_name: str, duration: float, tags: Optional[Dict[str, str]] = None):
    """Записать время выполнения (удобная функция)."""
    _metrics_collector.record_timing(metric_name, duration, tags)


def timed(metric_name: Optional[str] = None, tags: Optional[Dict[str, str]] = None):
    """
    Декоратор для автоматического измерения времени выполнения.

    Args:
        metric_name: Имя метрики (по умолчанию используется имя функции)
        tags: Теги метрики
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            name = metric_name or f"{func.__module__}.{func.__qualname__}"
            # 2.2 (Р2.2-10): часы длительности — perf_counter. Замеряемый интервал
            # короче шага time.time()/monotonic на Windows (~15.6 мс), и такие
            # разности ложатся на сетку часов: по бакетам они разложились бы
            # двумя столбиками (0.0 и 0.0156) вместо распределения. Значение
            # используется только как разность — эпоха perf_counter не важна.
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration = time.perf_counter() - start_time
                record_timing(f"{name}.duration", duration, tags)
                increment_metric(f"{name}.success", tags)
                return result
            except Exception:
                duration = time.perf_counter() - start_time
                record_timing(f"{name}.error_duration", duration, tags)
                increment_metric(f"{name}.errors", tags)
                raise

        return wrapper

    return decorator
