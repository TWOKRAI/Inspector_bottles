"""throttle.py — Middleware для ограничения частоты обновлений по паттернам путей.

Позволяет задать минимальный интервал между записями для группы путей.
Полезно для высокочастотных метрик (fps, seq), которые не нужно писать в
StateStore на каждый кадр.

Порядок правил: первое матчащее правило применяется.

Два входа троттла (симметричная семантика):

- ``before_set`` — троттлит по одному конкретному пути (``path`` = лист).
- ``before_merge`` — troттлит **поддерево** (``path`` = корень, ``value`` = вложенный
  dict). Merge разворачивается в листовые ПОЛНЫЕ пути (``path`` + относительный путь
  листа), и к каждому листу применяется та же логика правил, что и в ``before_set``.
  Троттлящиеся листья вырезаются из поддерева; остальные проходят. См. подробный
  разбор семантики в docstring :meth:`before_merge` (PC 0.1).

Рантайм-мутабельность правил (PC 0.1): :meth:`set_rules` / :meth:`update_rule` /
:meth:`remove_rule` меняют набор правил живьём (потокобезопасно, copy-on-write) —
нужно для рантайм-команд (config hot-reload / backend_ctl, Фаза 3).

Гигиена таймингов мёртвых путей (находка G, Task 3.4): без чистки ``_last_pass``/
``_pending`` растут бессрочно при hot-swap процессов с новыми именами/instance-id
(старые пути никогда не удаляются). Два независимых механизма:

- :meth:`prune` — точечная чистка по префиксу пути, звать при удалении поддерева
  из StateStore (``state.delete`` на корне ``processes.<name>``,
  см. ``StateStoreManager.handle_state_delete``).
- lazy-prune по размеру (:meth:`_maybe_lazy_prune`) — подстраховка НА СЛУЧАЙ, если
  путь исчез без явного ``state.delete`` (например, тайминг остался от снятого
  правила без снятия поддерева): срабатывает только когда ``_last_pass`` вырос за
  ``_LAZY_PRUNE_SIZE_THRESHOLD``, выбрасывает записи старше
  ``_STALE_AGE_MULTIPLIER × базовый_интервал``.

:meth:`flush` отбрасывает (не возвращает) pending-значения старше того же порога —
см. docstring метода.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Iterator

from ..core import match_pattern, split_pattern
from .base import StateMiddleware

# ---------------------------------------------------------------------------
# Константы гигиены таймингов (находка G, Task 3.4)
# ---------------------------------------------------------------------------

# N — порог размера _last_pass, после которого запускается lazy-prune (см.
# _maybe_lazy_prune). Прод-нагрузка телеметрии (десятки-сотни путей) никогда
# не задевает этот порог — lazy-prune для неё чистый no-op (одна проверка len()).
_LAZY_PRUNE_SIZE_THRESHOLD = 1000

# K — множитель "запись мертва, если её возраст > K × базовый_интервал". Путь,
# не обновлявшийся дольше нескольких СВОИХ интервалов, почти наверняка исчез
# (hot-swap/остановленный процесс), а не просто временно не шлёт кадры.
_STALE_AGE_MULTIPLIER = 10

# Базовый интервал, когда среди правил нет ни одного ПОЛОЖИТЕЛЬНОГО (только
# interval=0 полные блокировки, либо правил нет вовсе) — без этого fallback'а
# порог вырождался бы в 0 и любая запись считалась бы мёртвой мгновенно.
_DEFAULT_RULE_INTERVAL_SEC = 5.0


class ThrottleMiddleware(StateMiddleware):
    """Ограничение частоты обновлений по паттернам путей.

    Пример::

        ThrottleMiddleware({
            "**.state.actual_fps": 1.0,    # max 1 раз/сек
            "**.state.drops_count": 2.0,   # max 1 раз/2 сек
            "**.state.last_frame_seq": 0,  # полная блокировка
        })

    Правила:
    - ``0``  — полная блокировка: путь никогда не попадёт в StateStore.
    - ``>0`` — минимальный интервал в секундах между двумя пропущенными записями.
    - Путь не покрыт ни одним правилом — пропускать всегда (без ограничений).
    - Последнее заблокированное значение накапливается в ``_pending`` и может
      быть сброшено вручную через :meth:`flush` (например, при shutdown).

    Троттл применяется и к ``set`` (лист), и к ``merge`` (поддерево — per-leaf,
    см. :meth:`before_merge`).

    Потокобезопасность (PC 0.1):
        Middleware читается из потока стора (``before_set`` / ``before_merge`` /
        ``flush``), а правила могут меняться из ДРУГОГО потока (рантайм-команды —
        Фаза 3). Набор правил ``_rules`` защищён по схеме **copy-on-write**:
        мутаторы под ``_lock`` строят НОВЫЙ dict и атомарно пере-присваивают
        ``self._rules`` (мутаторы никогда не правят живой dict «на месте»). Путь
        чтения (``_find_rule``) берёт локальную ссылку на ``self._rules`` и
        итерирует её без блокировки — это безопасно, т.к. пере-присваивание ссылки
        атомарно под GIL, а живой dict неизменен. ``_lock`` сериализует только
        мутатор-vs-мутатор (без него два одновременных ``update_rule`` могли бы
        потерять правку). Тайминги (``_last_pass`` / ``_pending`` / ``_pending_since``)
        трогаются только из потока стора — их синхронизировать не нужно. Это же
        относится и к :meth:`prune` (Task 3.4): звать его разрешено ТОЛЬКО из
        потока стора (того же, что обрабатывает ``state.set``/``state.merge``/
        ``state.delete`` — все IPC-команды ``StateStoreManager`` диспетчерятся
        серийно одним воркер-тредом ``message_processor``, см.
        ``StateStoreManager.handle_state_delete``); вызов из другого потока не
        потокобезопасен (гонка с ``before_set``/``before_merge`` того же процесса).
    """

    @property
    def name(self) -> str:
        return "throttle"

    def __init__(self, rules: dict[str, float]) -> None:
        # Словарь правил: паттерн → интервал (0 = полная блокировка).
        # Мутируется только пере-присваиванием (copy-on-write), см. docstring.
        self._rules: dict[str, float] = dict(rules)

        # Сериализация мутаторов правил (мутатор-vs-мутатор). Путь чтения — без лока.
        self._lock = threading.Lock()

        # Последний момент пропуска для каждого конкретного пути
        self._last_pass: dict[str, float] = {}

        # Последнее заблокированное значение: path → (value, source)
        self._pending: dict[str, tuple[Any, str]] = {}

        # Момент последней записи в _pending для того же пути (не путать со
        # значением из _last_pass — это момент постановки в очередь, а не
        # момент пропуска). Отдельный dict, а не третий элемент кортежа в
        # _pending, — чтобы не менять внешнюю форму _pending (используется в
        # тестах и в flush()). Нужен для age-проверок в prune/flush (Task 3.4).
        self._pending_since: dict[str, float] = {}

    # ------------------------------------------------------------------
    # before_set — троттл одного пути (лист)
    # ------------------------------------------------------------------

    def before_set(
        self,
        path: str,
        value: Any,
        source: str,
        context: dict,
    ) -> tuple[bool, Any]:
        """Проверить, нужно ли пропустить обновление по пути ``path``.

        Алгоритм:
        1. Найти первое матчащее правило для ``path``.
        2. Нет правила → пропустить (True, value).
        3. ``interval == 0`` → заблокировать навсегда (False, value).
        4. Прошло меньше ``interval`` с последнего пропуска → сохранить
           в ``_pending``, вернуть (False, value).
        5. Иначе → пропустить, обновить ``_last_pass``, очистить ``_pending``.

        Перед основной логикой опционально запускает lazy-prune (Task 3.4,
        см. :meth:`_maybe_lazy_prune`) — недорогая проверка размера на
        каждый вызов, полное сканирование — только при превышении порога.
        """
        now = time.monotonic()
        self._maybe_lazy_prune(now)

        interval = self._find_rule(path)

        # Путь не покрыт правилами — пропускаем без ограничений
        if interval is None:
            return True, value

        # Полная блокировка
        if interval == 0:
            self._pending[path] = (value, source)
            self._pending_since[path] = now
            context["rejection_reason"] = "throttled"
            return False, value

        last = self._last_pass.get(path)

        if last is not None and (now - last) < interval:
            # Слишком рано — накапливаем последнее значение
            self._pending[path] = (value, source)
            self._pending_since[path] = now
            context["rejection_reason"] = "throttled"
            return False, value

        # Пропускаем: обновляем время и убираем pending для этого пути
        self._last_pass[path] = now
        self._pending.pop(path, None)
        self._pending_since.pop(path, None)
        return True, value

    # ------------------------------------------------------------------
    # before_merge — троттл поддерева (per-leaf)
    # ------------------------------------------------------------------

    def before_merge(
        self,
        path: str,
        data: dict,
        source: str,
        context: dict,
    ) -> tuple[bool, dict]:
        """Троттлить merge-поддерево по правилам per-leaf (PC 0.1).

        **Зачем per-leaf.** Merge несёт ПОДДЕРЕВО: ``path`` — корень (напр.
        ``processes.cam``), ``data`` — вложенный dict листьев. Правила же
        авторятся как листовые глобы (``processes.**.state.fps``), ровно как для
        ``before_set``. Сопоставлять эти правила с КОРНЕМ merge (``processes.cam``)
        бессмысленно — они его не матчат, и троттл остаётся no-op (это и есть баг,
        который чинит PC 0.1: телеметрия публикуется через ``proxy.merge``, значит
        правило по set-листу её не ограничивало). Поэтому merge разворачивается в
        листовые ПОЛНЫЕ пути (``path`` + относительный путь листа), и каждый лист
        проходит ту же логику правил, что и :meth:`before_set`:

        - лист без правила → пропускается (консервативно: статусы/health/данные
          без явного правила не блокируются — инвариант «status/errors always»);
        - правило ``0`` → лист вырезается навсегда (и копится в ``_pending``);
        - ``interval > 0`` → per-путь rate-limit по ``_last_pass`` (тот же контракт,
          что set: идемпотентно, последнее значение копится в ``_pending``).

        **Результат.**
        - Ни один лист не покрыт правилом → пропустить ``data`` как есть (без копии).
        - Часть листьев прошла (или есть непокрытые) → пропустить ПОДРЕЗАННОЕ
          поддерево (только прошедшие + непокрытые листья); придержанные — вырезаны.
        - Все листья покрыты правилом и все придержаны → отклонить merge целиком
          (``proceed=False``, ``rejection_reason="throttled"``) — симметрично set.

        Дёшево и правильно: телеметрийные поддеревья маленькие (единицы воркеров ×
        единицы метрик), обход листьев — копейки; при этом правила вида
        ``processes.**.state.fps`` реально прореживают телеметрийный merge.

        Args:
            path: корневой путь merge.
            data: merge-поддерево (вложенный dict).
            source: источник изменения.
            context: общий dict (для ``rejection_reason``).

        Returns:
            ``(proceed, data_or_pruned)`` — см. «Результат» выше.
        """
        now = time.monotonic()
        self._maybe_lazy_prune(now)  # Task 3.4, см. _maybe_lazy_prune

        rules = self._rules  # copy-on-write снимок: чтение без блокировки

        if not rules or not isinstance(data, dict) or not data:
            return True, data

        kept: dict = {}
        any_ruled = False  # был ли хоть один лист с правилом

        for rel, leaf in self._iter_leaves(data):
            full = f"{path}.{rel}" if path else rel
            interval = self._find_rule(full, rules)

            if interval is None:
                # Нет правила — консервативно пропускаем лист как есть.
                self._nested_set(kept, rel, leaf)
                continue

            any_ruled = True

            # Полная блокировка
            if interval == 0:
                self._pending[full] = (leaf, source)
                self._pending_since[full] = now
                continue

            last = self._last_pass.get(full)
            if last is not None and (now - last) < interval:
                # Слишком рано — придерживаем, копим последнее значение.
                self._pending[full] = (leaf, source)
                self._pending_since[full] = now
                continue

            # Пропускаем лист: обновляем тайминг, чистим pending.
            self._last_pass[full] = now
            self._pending.pop(full, None)
            self._pending_since.pop(full, None)
            self._nested_set(kept, rel, leaf)

        if not any_ruled:
            # Ни один лист не покрыт правилом — merge проходит как есть (без копии).
            return True, data

        if not kept:
            # Все листья покрыты правилом и все придержаны → отклоняем merge.
            context["rejection_reason"] = "throttled"
            return False, data

        # Частичный merge: непокрытые + прошедшие листья; придержанные — вырезаны.
        return True, kept

    # ------------------------------------------------------------------
    # Рантайм-мутаторы правил (PC 0.1) — потокобезопасно (copy-on-write)
    # ------------------------------------------------------------------

    def set_rules(self, rules: dict[str, float]) -> None:
        """Заменить ВЕСЬ набор правил (рантайм).

        Тайминги (``_last_pass`` / ``_pending``) НЕ сбрасываются: пути, потерявшие
        правило, дальше просто пропускаются (их stale-тайминги безвредны); пути с
        изменившимся интервалом переоценятся против нового интервала при следующем
        вызове — это и есть «живая» смена частоты.

        Args:
            rules: новый словарь ``{pattern: interval_sec}``.
        """
        with self._lock:
            self._rules = dict(rules)

    def update_rule(self, pattern: str, interval_sec: float) -> None:
        """Добавить/обновить одно правило (рантайм).

        Copy-on-write: под локом строим новый dict и атомарно пере-присваиваем,
        чтобы поток чтения (``_find_rule``) не увидел частично изменённый набор.

        Args:
            pattern: glob-паттерн пути.
            interval_sec: интервал в секундах (``0`` — полная блокировка).
        """
        with self._lock:
            new_rules = dict(self._rules)
            new_rules[pattern] = interval_sec
            self._rules = new_rules

    def remove_rule(self, pattern: str) -> bool:
        """Удалить одно правило по паттерну (рантайм).

        Args:
            pattern: glob-паттерн правила.

        Returns:
            True если правило было и удалено, False если такого правила нет.
        """
        with self._lock:
            if pattern not in self._rules:
                return False
            new_rules = dict(self._rules)
            del new_rules[pattern]
            self._rules = new_rules
            return True

    @property
    def rules(self) -> dict[str, float]:
        """Копия текущего набора правил (для интроспекции/тестов)."""
        return dict(self._rules)

    # ------------------------------------------------------------------
    # flush — принудительный сброс накопленных значений
    # ------------------------------------------------------------------

    def flush(self) -> list[tuple[str, Any, str]]:
        """Принудительный сброс накопленных throttled-значений.

        Вызывается при shutdown, чтобы не потерять последние ЖИВЫЕ значения.
        Покрывает и set-, и merge-листья (в ``_pending`` лежат полные пути).

        **Выбранная семантика (Task 3.4, находка G): ОТБРАСЫВАТЬ stale-записи.**
        Запись считается мёртвой, если её возраст (время с последней постановки
        в ``_pending``, ``_pending_since``) превышает :meth:`_stale_age_threshold`
        (``K × базовый_интервал`` — те же константы, что у lazy-prune). Мёртвые
        записи НЕ попадают в возвращаемый список: путь, не обновлявшийся много
        интервалов подряд, почти наверняка принадлежит остановленному/снятому
        процессу — записать его последнее известное значение в StateStore при
        shutdown значило бы воскресить давно неактуальные данные (собственно
        находка G). «Свежие» pending-значения (путь реально ждал своего
        интервала на момент shutdown) возвращаются как раньше — контракт
        вызывающей стороны (список кортежей на запись в стор) не меняется.

        Returns:
            Список кортежей ``(path, value, source)`` для каждого СВЕЖЕГО pending
            значения (stale — отброшены). После вызова ``_pending`` и
            ``_pending_since`` очищаются целиком — и свежие, и отброшенные записи.
        """
        now = time.monotonic()
        threshold = self._stale_age_threshold()

        result = [
            (path, value, source)
            for path, (value, source) in self._pending.items()
            if (now - self._pending_since.get(path, now)) <= threshold
        ]

        self._pending.clear()
        self._pending_since.clear()
        return result

    # ------------------------------------------------------------------
    # prune — точечная чистка таймингов/pending мёртвого поддерева (Task 3.4)
    # ------------------------------------------------------------------

    def prune(self, prefix: str) -> int:
        """Удалить тайминги и pending-значения по путям под ``prefix``.

        Вызывается точечно при удалении поддерева из StateStore (``state.delete``
        на корне поддерева процесса, например ``processes.cam1`` — см.
        ``StateStoreManager.handle_state_delete``, RS-2/Ж-2/LP-4 cleanup). Без
        этого тайминги/pending исчезнувшего процесса висят в словарях бессрочно
        (находка G): частые hot-swap с новыми именами/instance-id растят
        ``_last_pass``/``_pending`` без ограничения.

        Путь считается «под префиксом», если совпадает с ним целиком либо
        начинается с ``prefix + "."`` — точка как граница сегмента пути дерева,
        чтобы ``processes.cam1`` не задел ``processes.cam10``.

        Потокобезопасность: см. docstring класса — звать ТОЛЬКО из потока
        стора (того же, что обрабатывает ``state.set``/``state.merge``/
        ``state.delete``).

        Args:
            prefix: путь корня удалённого поддерева.

        Returns:
            Число удалённых записей (тайминги + pending) — для наблюдаемости/лога.
        """

        def _under_prefix(p: str) -> bool:
            return p == prefix or p.startswith(prefix + ".")

        last_pass_hits = [p for p in self._last_pass if _under_prefix(p)]
        for p in last_pass_hits:
            del self._last_pass[p]

        pending_hits = [p for p in self._pending if _under_prefix(p)]
        for p in pending_hits:
            del self._pending[p]
            self._pending_since.pop(p, None)

        return len(last_pass_hits) + len(pending_hits)

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _stale_age_threshold(self) -> float:
        """Возрастной порог «мёртвой» записи: K × макс. положительный интервал.

        Используется и lazy-prune'ом (:meth:`_maybe_lazy_prune`), и :meth:`flush`
        — единая логика «что считать устаревшим» (Task 3.4, находка G). Как и
        :meth:`_find_rule`, читает copy-on-write снимок ``self._rules`` без
        блокировки.

        Returns:
            Порог в секундах.
        """
        positive_intervals = [v for v in self._rules.values() if v > 0]
        base = max(positive_intervals) if positive_intervals else _DEFAULT_RULE_INTERVAL_SEC
        return base * _STALE_AGE_MULTIPLIER

    def _maybe_lazy_prune(self, now: float) -> None:
        """Lazy-prune таймингов/pending при превышении размера (находка G).

        Без хука удаления поддерева (:meth:`prune`) единственный доступный
        сигнал «путь исчез» — тайминг, который давно не обновлялся. Полное
        O(n)-сканирование на каждый вызов ``before_set``/``before_merge`` было
        бы лишней работой на горячем пути, поэтому сканирование запускается
        ТОЛЬКО когда ``_last_pass`` ЛИБО ``_pending`` вырос за
        ``_LAZY_PRUNE_SIZE_THRESHOLD`` — прод-нагрузка телеметрии (десятки-сотни
        путей) никогда не достигает этого порога, и lazy-prune для неё — одна
        дешёвая проверка ``len()``. Проверяем ОБА словаря: правило ``interval == 0``
        (полная блокировка) копит пути в ``_pending``/``_pending_since``, но НЕ в
        ``_last_pass`` — при потоке уникальных путей под таким правилом рос бы только
        ``_pending``, и проверка одного ``_last_pass`` его слепо пропустила бы.

        Args:
            now: уже посчитанный ``time.monotonic()`` вызывающего метода
                (переиспользуем — вторым вызовом не платим).
        """
        if max(len(self._last_pass), len(self._pending)) <= _LAZY_PRUNE_SIZE_THRESHOLD:
            return

        threshold = self._stale_age_threshold()

        stale_last_pass = [p for p, ts in self._last_pass.items() if (now - ts) > threshold]
        for p in stale_last_pass:
            del self._last_pass[p]

        stale_pending = [p for p, ts in self._pending_since.items() if (now - ts) > threshold]
        for p in stale_pending:
            self._pending.pop(p, None)
            del self._pending_since[p]

    def _find_rule(self, path: str, rules: dict[str, float] | None = None) -> float | None:
        """Найти первое матчащее правило для ``path``.

        Args:
            path: конкретный путь в дереве состояний.
            rules: снимок правил (copy-on-write) для консистентности в пределах
                одного merge; ``None`` — взять текущий ``self._rules``.

        Returns:
            Интервал в секундах, если правило найдено; ``None`` если нет.
        """
        if rules is None:
            rules = self._rules  # copy-on-write снимок: чтение без блокировки
        path_segs = tuple(path.split("."))
        for pattern, interval in rules.items():
            pattern_segs = split_pattern(pattern)
            if match_pattern(pattern_segs, path_segs):
                return interval
        return None

    @staticmethod
    def _iter_leaves(data: dict, _prefix: str = "") -> Iterator[tuple[str, Any]]:
        """Обойти листья вложенного dict.

        Лист — любое значение, не являющееся НЕпустым dict (скаляр, список, а также
        пустой dict ``{}``). Пустой dict трактуется как лист, чтобы не потерять его
        при подрезке (в телеметрии не встречается, но контракт корректен).

        Args:
            data: вложенный dict merge-поддерева.
            _prefix: накопленный относительный путь (рекурсия).

        Yields:
            Кортежи ``(относительный_точечный_путь, значение_листа)``.
        """
        for key, val in data.items():
            rel = f"{_prefix}.{key}" if _prefix else key
            if isinstance(val, dict) and val:
                yield from ThrottleMiddleware._iter_leaves(val, rel)
            else:
                yield rel, val

    @staticmethod
    def _nested_set(root: dict, relpath: str, value: Any) -> None:
        """Записать ``value`` в ``root`` по относительному точечному пути.

        Создаёт промежуточные dict-узлы. Обратная операция к :meth:`_iter_leaves`
        (собрать подрезанное поддерево из прошедших листьев).

        Args:
            root: целевой dict (модифицируется на месте).
            relpath: относительный точечный путь листа.
            value: значение листа.
        """
        segs = relpath.split(".")
        node = root
        for seg in segs[:-1]:
            node = node.setdefault(seg, {})
        node[segs[-1]] = value
