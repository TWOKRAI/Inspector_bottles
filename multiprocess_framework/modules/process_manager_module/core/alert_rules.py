"""alert_rules — декларативные правила алертинга поверх supervisor-событий (NEW-7).

Purpose:
    Супервизор уже публикует поток событий (``crashed``/``unresponsive``/
    ``restarting``/``recovered``/``gave_up``) и счётчики (drop'ы очередей). Правила
    здесь превращают их в АЛЕРТ — громкую нотификацию с severity и антидребезгом,
    чтобы терминальные состояния («сдался», «дропы растут») не терялись в потоке
    обычных логов.

    Модуль ЧИСТЫЙ: без I/O, без StateStore, без времени «изнутри» — всё приходит
    аргументами. Это делает правила юнит-тестируемыми и позволяет монитору
    оставаться единственным местом с побочными эффектами.

Public API:
    - AlertRule — декларация одного правила (событийного или счётчикового)
    - DEFAULT_RULES — набор по умолчанию
    - rules_for_event / counter_rules — выборка правил
    - should_fire — антидребезг (cooldown) по времени последнего срабатывания
    - counter_growth — прирост счётчика относительно базы

Stability: lite
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Optional, Tuple

__all__ = [
    "AlertRule",
    "DEFAULT_RULES",
    "rules_for_event",
    "counter_rules",
    "should_fire",
    "counter_growth",
]

Severity = Literal["critical", "warning", "info"]


@dataclass(frozen=True)
class AlertRule:
    """Декларация правила алертинга.

    Два вида (взаимоисключающие):
      - **событийное** — ``events`` непусто: срабатывает на supervisor-событии;
      - **счётчиковое** — ``counter_path`` непусто: срабатывает на приросте счётчика
        в StateStore (шаблон с ``{process}``), напр. ``drops_count``.

    Attributes:
        name: уникальное имя правила (ключ в дереве алертов и в антидребезге)
        severity: ``critical`` | ``warning`` | ``info`` — влияет на уровень лога
        events: supervisor-события, на которые правило реагирует
        counter_path: шаблон пути счётчика с ``{process}``; пусто → не счётчиковое
        min_growth: минимальный прирост счётчика для срабатывания (≥1)
        cooldown_sec: антидребезг — не повторять тот же алерт чаще, чем раз в N сек
    """

    name: str
    severity: Severity = "warning"
    events: Tuple[str, ...] = ()
    counter_paths: Tuple[str, ...] = ()
    min_growth: int = 1
    cooldown_sec: float = 60.0

    def paths_for(self, process: str) -> list[str]:
        """Пути-кандидаты счётчика для процесса (пусто — правило не счётчиковое).

        Кандидатов несколько, потому что имя поля счётчика — конвенция публикующей
        стороны, а не проверяемый инвариант: capture-плагин публикует ``drops``,
        другие источники могут писать ``drops_count``. Монитор берёт ПЕРВЫЙ путь,
        который реально резолвится, — правило не умирает молча от переименования.
        """
        return [p.format(process=process) for p in self.counter_paths]


#: Набор по умолчанию. Терминальный ``gave_up`` — critical с длинным cooldown
#: (одно громкое событие вместо потока); ``unresponsive`` — предупреждение;
#: рост дропов — предупреждение (данные теряются молча, это должно быть видно).
DEFAULT_RULES: Tuple[AlertRule, ...] = (
    AlertRule(
        "supervisor_gave_up",
        severity="critical",
        events=("gave_up",),
        cooldown_sec=300.0,
    ),
    AlertRule(
        "process_unresponsive",
        severity="warning",
        events=("unresponsive",),
        cooldown_sec=60.0,
    ),
    AlertRule(
        "drops_growing",
        severity="warning",
        # ВАЖНО: путь обязан совпадать с тем, что РЕАЛЬНО публикуют источники.
        # Живой публикатор — capture-плагин (`Plugins/sources/capture/plugin.py`):
        # `processes.<name>.state` ⊃ поле `drops`. Вариант `drops_count` оставлен
        # вторым кандидатом (так поле зовётся в camera-адаптере прототипа под
        # другим корнем и в RingBuffer). Первый резолвящийся путь выигрывает —
        # иначе правило молча мертво (находка ревью NEW-7: дефолт указывал на
        # `drops_count` под `processes.*`, который не публикует НИКТО).
        counter_paths=(
            "processes.{process}.state.drops",
            "processes.{process}.state.drops_count",
        ),
        min_growth=1,
        cooldown_sec=60.0,
    ),
)


def rules_for_event(rules: Iterable[AlertRule], event: str) -> list[AlertRule]:
    """Событийные правила, реагирующие на ``event``.

    Post: каждое возвращённое правило имеет ``event in rule.events``.
    """
    return [r for r in rules if event in r.events]


def counter_rules(rules: Iterable[AlertRule]) -> list[AlertRule]:
    """Счётчиковые правила (непустой ``counter_paths``)."""
    return [r for r in rules if r.counter_paths]


def should_fire(last_fired_at: Optional[float], now: float, cooldown_sec: float) -> bool:
    """Прошёл ли антидребезг: можно ли поднимать алерт снова.

    Pre: ``now`` — монотонное время в секундах.
    Post: ``True``, если алерт ещё не поднимался (``last_fired_at is None``) либо с
    прошлого раза прошло ≥ ``cooldown_sec``. ``cooldown_sec <= 0`` → всегда ``True``.
    """
    if last_fired_at is None or cooldown_sec <= 0:
        return True
    return (now - last_fired_at) >= cooldown_sec


def counter_growth(baseline: Optional[int], current: Optional[int]) -> int:
    """Прирост счётчика относительно базы.

    Нечисловые/отсутствующие значения → ``0`` (нет сигнала). Сброс счётчика
    (``current < baseline`` — например, процесс перезапущен) тоже даёт ``0``:
    рестарт не должен выглядеть как всплеск потерь.
    """
    # bool — подкласс int: True стал бы «счётчиком 1». Контракт модуля: не-int
    # (в том числе bool) сигнала не даёт — симметрично фильтру _read_state_int.
    if isinstance(current, bool) or isinstance(baseline, bool):
        return 0
    if not isinstance(current, int) or not isinstance(baseline, int):
        return 0
    delta = current - baseline
    return delta if delta > 0 else 0
