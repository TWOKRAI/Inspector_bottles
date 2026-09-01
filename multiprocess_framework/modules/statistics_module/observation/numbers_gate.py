# -*- coding: utf-8 -*-
"""Гейт плоскости ЧИСЕЛ: то же glob-правило, что у уровней, но до сборки записи (Ф2, 2.1).

Уровни (``processes.<P>.state.plugins.<писатель>.<лист>``) уже решаются политикой
:class:`~...process_module.configs.observation_policy.ObservationPolicy` — по
ПУТИ, одним glob-множеством. Числа (``StatsManager.record_metric`` и три его
брата) до этой задачи не решались вообще ничем: единственной ручкой был
бинарный ``stats.enabled``, и «зажать одну шумную метрику одного процесса» было
невыразимо. Здесь тот же язык приходит на вторую плоскость — **та же политика,
тот же объект**, только другой корень пути: ``processes.<P>.stats.<имя>``
(развилка Р-2, вариант «а», решение владельца).

**Теги в путь НЕ входят и правилом не адресуются.** Серия метрики — это «имя ×
теги», а правило говорит про ИМЯ: ``processes.cam1.stats.capture.frames``
режет метрику целиком, со всеми её тегами. Адресация по тегам (Р-2б) сознательно
оставлена за границей задачи, и это сказано вслух здесь, в ``CONTROL_PANEL.md`` и
в докстринге :meth:`NumbersGate.allow` — молчаливое «теги просто не работают»
было бы ровно тем классом тихого no-op, который фаза разбирает.

**Почему легаси-секция ``telemetry.publish`` СЮДА не пускается** —
воспроизведение, а не соображение. Она deny-by-default в боевом конфиге
прототипа (``multiprocess_prototype/backend/config/system.yaml:277`` —
``default_enabled: false`` с белым списком из двух имён), а её правила
суффиксные (``**.<лист>``, то есть «любой путь, кончающийся этим именем»).
Пусти её в решение по числам — и зонтик ``**`` ответил бы ``enabled=False`` на
КАЖДУЮ метрику каждого процесса: вся плоскость чисел умерла бы молча в тот же
момент, когда эта задача попадёт в main. Поэтому у чисел свой дефолт поддерева
(:data:`~...process_module.configs.observation_policy.STATS_SUBTREE_PATTERN`),
и он живёт в самой политике, а не здесь: решение о пути принимает политика, гейт
только спрашивает. Паритет сторожится тестом на боевом конфиге прототипа
(``test_f2_numbers_policy_hazards.py``).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

__all__ = ["NumbersGate", "PathSchedule", "stats_metric_path"]

#: Корень путей плоскости чисел (Р-2а). Литерал живёт ЗДЕСЬ и больше нигде:
#: его читают гейт (строит путь) и политика (дефолт поддерева
#: ``processes.*.stats.**``), и разъехавшись, они дали бы «правило написано,
#: попаданий ноль» без единого голоса.
STATS_PATH_SEGMENT = "stats"


def stats_metric_path(process: str, metric: str) -> str:
    """Путь метрики плоскости чисел: ``processes.<процесс>.stats.<имя>``.

    Форма дословно повторяет соседей плоскости уровней
    (``telemetry.state_metric_path`` / ``plugin_metric_path``) — у оператора
    один язык адресов на все плоскости, а не три похожих.
    """
    return f"processes.{process}.{STATS_PATH_SEGMENT}.{metric}"


class PathSchedule:
    """Расписание «созрел ли путь» — ОДИН класс на обе плоскости.

    Тело — те же три строки, что жили внутри ``TelemetryGate._grant``
    (``process_module/heartbeat/telemetry.py``): сравнить с сроком, выдать,
    сдвинуть срок. Вынесено не ради красоты: план Ф2 требует, чтобы
    ``interval_sec`` у ЧИСЕЛ считался ТЕМ ЖЕ расписанием, что у уровней, а не
    его копией. Вторая машина расписания рядом с первой — ровно тот дефект,
    который эта фаза разбирает: два похожих механизма расходятся тем тише, чем
    реже на них смотрят, а расхождение выглядит как «частота почему-то другая».

    Ключ — ПОЛНЫЙ ПУТЬ, а не имя листа. Так уровни ведут расписание с Ф4 (до неё
    ключевались именем, и агрегат фреймворка делил запись с листом плагина), и
    числа наследуют то же свойство даром: одноимённая метрика двух процессов
    зреет независимо.

    Потокобезопасность: словарь без лока. Под GIL вставка и чтение не рвутся, но
    два потока, спросившие ОДИН путь одновременно, могут оба получить разрешение
    — то есть предохранитель частоты изредка пропускает лишнюю запись, а не
    придерживает нужную. Лок на горячем пути записи чисел стоил бы дороже, чем
    эта неточность (тот же довод, по которому без лока живёт
    ``ObservationManager._numbers_delivered_count``); заявляется как «не чаще
    интервала ПЛЮС гонка», а не как точная периодичность.
    """

    __slots__ = ("_clock", "_due")

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        """
        Args:
            clock: источник монотонного времени (инъекция часов в тестах).
        """
        self._clock = clock
        self._due: Dict[str, float] = {}

    @property
    def table(self) -> Dict[str, float]:
        """Живая таблица ``{путь: срок}`` — для диагностики и back-compat-чтения."""
        return self._due

    def due(self, path: str, interval: float, now: Optional[float] = None) -> bool:
        """Созрел ли ``path``; при выдаче разрешения сдвигает его срок.

        Продвижение происходит в момент ВЫДАЧИ, а не факта наличия данных — тот
        же контракт, что был у ``TelemetryGate._grant`` до выноса.

        Args:
            path: полный путь листа.
            interval: минимальный интервал, сек.
            now: момент решения; ``None`` → ``clock()``.
        """
        if now is None:
            now = self._clock()
        if now < self._due.get(path, 0.0):
            return False
        self._due[path] = now + interval
        return True

    def clear(self) -> None:
        """Забыть все сроки — новая политика начинает расписание с чистого листа."""
        self._due.clear()


class NumbersGate:
    """Решение «собирать ли ЭТО число» — один вопрос политике до сборки записи.

    Живёт на :class:`~.observation_manager.ObservationManager` (порт), потому
    что порт — единственный писатель плоскости чисел (М5 плана «порт
    наблюдений»): и прямая дорога ``StatsManager.record_metric``, и слот-дорога
    ``ObservableMixin._record_metric``, и дорога плагина
    (``PluginContext._stats_call``) сходятся в ``ObservationPort._route_number``.
    Гейт здесь — ФИЛЬТР ВНУТРИ единственного пути, а не второй путь рядом с ним;
    поставь его в фасад ``StatsManager``, и числа плагинов, идущие в порт мимо
    менеджера, обошли бы политику молча.

    Счётчики переживают смену политики намеренно: ``config.reload`` соседней
    ручки пересобирает политику, и обнуляйся счёт вместе с ней — «сколько
    метрик срезано правилом» отвечало бы «ноль» ровно после каждой чужой правки.
    Расписание, наоборот, ЧИСТИТСЯ (:meth:`set_policy`) — дословно как у уровней
    (``ProcessHeartbeat.apply_observation_policy``: у нового гейта ``_next_due``
    пустой), потому что сроки посчитаны по СТАРЫМ интервалам и после смены
    правил означают уже не то.

    Потокобезопасность: политика подменяется присваиванием ссылки (атомарно под
    GIL), поэтому пишущий поток работает либо со старой политикой целиком, либо
    с новой. Счётчики — обычные ``dict`` с ``+= 1`` без лока: под конкуренцией
    МОГУТ недосчитать единицы (тот же названный потолок, что у
    ``numbers_delivered``), годятся как счётный факт, не как точный аудит.
    """

    __slots__ = ("_dropped", "_dropped_by_rule", "_policy", "_prefix", "_schedule", "_throttled")

    def __init__(self, policy: Any, process: str, clock: Callable[[], float] = time.monotonic) -> None:
        """
        Args:
            policy: объект с ``resolve(path, count=True) -> PolicyDecision``
                (:class:`~...process_module.configs.observation_policy.ObservationPolicy`).
                Duck-typing, а не импорт: политика живёт в ``process_module``, а
                этот файл — в ``statistics_module``, и импорт замкнул бы кольцо
                пакетов (см. докстринг ``observation/__init__.py``).
            process: имя процесса — второй сегмент пути.
            clock: источник монотонного времени.
        """
        self._policy = policy
        self._prefix = f"processes.{process}.{STATS_PATH_SEGMENT}."
        self._schedule = PathSchedule(clock)
        self._dropped: Dict[str, int] = {}
        self._throttled: Dict[str, int] = {}
        self._dropped_by_rule: Dict[str, int] = {}

    @property
    def policy(self) -> Any:
        """Действующая политика (``None`` — правил нет, гейт пропускает всё)."""
        return self._policy

    def set_policy(self, policy: Any) -> None:
        """Подменить политику. Счётчики переживают, расписание — нет (см. докстринг класса)."""
        if policy is self._policy:
            return
        self._policy = policy
        self._schedule.clear()

    def allow(self, name: str) -> bool:
        """Пускать ли метрику ``name`` — решение ДО сборки числовой записи.

        Три исхода, и все три считаемы:

        * правило запретило (``enabled=False``) → ``numbers_policy_dropped[имя]``
          и ``dropped_by_rule[паттерн]``;
        * правило разрешило, но путь ещё не созрел (``interval_sec``) →
          ``numbers_policy_throttled[имя]``. Отдельным счётчиком, а не общим с
          запретом: «запрещено навсегда» и «придержано до срока» — разные факты,
          и слитые в одно число они не дают оператору различить их;
        * разрешено → ``True``.

        **Теги в решении не участвуют** (Р-2а): путь несёт только имя метрики,
        поэтому правило режет ВСЕ серии этого имени сразу.

        ``interval_sec == 0`` минует расписание вовсе — не только ради цены, но
        и ради памяти: иначе таблица сроков наполнялась бы записью на каждое имя
        метрики процесса, а нулевой интервал всё равно означает «созрел всегда».
        """
        policy = self._policy
        if policy is None:
            return True
        path = self._prefix + name
        decision = policy.resolve(path)
        if not decision.enabled:
            self._dropped[name] = self._dropped.get(name, 0) + 1
            pattern = decision.pattern
            self._dropped_by_rule[pattern] = self._dropped_by_rule.get(pattern, 0) + 1
            return False
        interval = decision.interval_sec
        if interval > 0.0 and not self._schedule.due(path, interval):
            self._throttled[name] = self._throttled.get(name, 0) + 1
            return False
        return True

    # ------------------------------------------------------------- диагностика

    def dropped_by_metric(self) -> Dict[str, int]:
        """``{имя метрики: сколько раз запрещено правилом}`` — копия снимка."""
        return dict(self._dropped)

    def throttled_by_metric(self) -> Dict[str, int]:
        """``{имя метрики: сколько раз придержано интервалом}`` — копия снимка."""
        return dict(self._throttled)

    def dropped_by_rule(self) -> Dict[str, int]:
        """``{паттерн правила: сколько чисел им срезано}`` — копия снимка.

        Ключ — паттерн ПОБЕДИВШЕГО правила, а не имя метрики: оператор,
        выключивший поддерево одним правилом, спрашивает «сколько срезало ЭТО
        правило», и разложение по именам на этот вопрос не отвечает.
        """
        return dict(self._dropped_by_rule)

    def view(self) -> Dict[str, Any]:
        """Секция ``policy`` ответа ``introspect.observability.stats``.

        Три поля названы планом (шаг 4 Task 2.1): правила, попадания,
        ``dropped_by_rule``. Попадания читаются У ПОЛИТИКИ
        (``rule_hits``) — это ТОТ ЖЕ счёт, которым живёт плоскость уровней, и
        второй счётчик рядом означал бы два ответа на «сработало ли правило».
        """
        policy = self._policy
        rules = getattr(policy, "rules_view", None)
        hits = getattr(policy, "rule_hits", None)
        return {
            "rules": rules() if callable(rules) else {},
            "hits": hits() if callable(hits) else {},
            "dropped_by_rule": self.dropped_by_rule(),
            "dropped_by_metric": self.dropped_by_metric(),
            "throttled_by_metric": self.throttled_by_metric(),
        }
