"""subscription_manager.py — Управление подписками с glob-style matching.

Процессы подписываются на изменения в дереве состояний по паттернам путей.
Паттерны поддерживают wildcard-синтаксис:
  - '*'  — ровно один сегмент пути
  - '**' — ноль или более сегментов пути

SubscriptionManager потокобезопасен (RLock).
Дедупликация по subscriber — ответственность DeltaDispatcher (Task 4b).
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from functools import lru_cache

from .delta import Delta

# ---------------------------------------------------------------------------
# Subscription — описание одной подписки
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Subscription:
    """Одна подписка процесса на изменения по паттерну.

    Attributes:
        sub_id: уникальный идентификатор подписки.
        pattern: паттерн пути, например 'cameras.*.config.*'.
        subscriber: имя процесса-подписчика.
        exclude_sources: кортеж источников, от которых подписчик
            НЕ хочет получать уведомления (например, свои собственные).
    """

    sub_id: str
    pattern: str
    subscriber: str
    exclude_sources: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Кэширование разбора паттернов
# ---------------------------------------------------------------------------

@lru_cache(maxsize=256)
def _split_pattern(pattern: str) -> tuple[str, ...]:
    """Разбивает паттерн по '.' и кэширует результат.

    Паттернов обычно мало (десятки), а match() вызывается тысячи раз,
    поэтому кэширование split даёт заметный выигрыш.
    """
    if not pattern:
        return ()
    return tuple(pattern.split("."))


# ---------------------------------------------------------------------------
# Рекурсивный матчер паттернов
# ---------------------------------------------------------------------------

def _match_pattern(pattern_segs: tuple[str, ...], path_segs: tuple[str, ...]) -> bool:
    """Рекурсивно проверяет совпадение паттерна с путём.

    Правила:
      - '*'  — совпадает ровно с одним сегментом (любым).
      - '**' — совпадает с 0, 1, 2, ... N сегментами.
      - Остальные сегменты — точное совпадение (case-sensitive).

    Args:
        pattern_segs: кортеж сегментов паттерна.
        path_segs: кортеж сегментов пути.

    Returns:
        True если паттерн совпадает с путём.
    """
    # Оба пустые — совпадение
    if not pattern_segs and not path_segs:
        return True

    # Паттерн пуст, путь нет — нет совпадения
    if not pattern_segs:
        return False

    head = pattern_segs[0]

    if head == "**":
        # '**' может поглотить 0 сегментов: пропускаем '**'
        if _match_pattern(pattern_segs[1:], path_segs):
            return True
        # '**' может поглотить 1+ сегментов: съедаем один сегмент пути
        return bool(path_segs and _match_pattern(pattern_segs, path_segs[1:]))

    # Паттерн не пуст, но путь кончился — нет совпадения
    if not path_segs:
        return False

    # '*' — любой один сегмент, или точное совпадение
    if head == "*" or head == path_segs[0]:
        return _match_pattern(pattern_segs[1:], path_segs[1:])

    return False


# ---------------------------------------------------------------------------
# SubscriptionManager
# ---------------------------------------------------------------------------

class SubscriptionManager:
    """Управление подписками с glob-style matching.

    Потокобезопасен — все мутирующие методы защищены RLock.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # sub_id → Subscription
        self._subscriptions: dict[str, Subscription] = {}
        # subscriber → set[sub_id] — индекс для быстрого unsubscribe_all
        self._by_subscriber: dict[str, set[str]] = {}

    def subscribe(
        self,
        pattern: str,
        subscriber: str,
        exclude_sources: tuple[str, ...] = (),
    ) -> str:
        """Создать подписку на паттерн.

        Args:
            pattern: glob-паттерн пути (например 'cameras.*.config.*').
            subscriber: имя процесса-подписчика.
            exclude_sources: источники, от которых НЕ нужны уведомления.

        Returns:
            sub_id — уникальный идентификатор подписки.
        """
        sub_id = str(uuid.uuid4())
        sub = Subscription(
            sub_id=sub_id,
            pattern=pattern,
            subscriber=subscriber,
            exclude_sources=exclude_sources,
        )

        # Предварительно кэшируем разбор паттерна
        _split_pattern(pattern)

        with self._lock:
            self._subscriptions[sub_id] = sub
            if subscriber not in self._by_subscriber:
                self._by_subscriber[subscriber] = set()
            self._by_subscriber[subscriber].add(sub_id)

        return sub_id

    def unsubscribe(self, sub_id: str) -> bool:
        """Удалить подписку по ID.

        Args:
            sub_id: идентификатор подписки.

        Returns:
            True если подписка была найдена и удалена, False если не найдена.
        """
        with self._lock:
            sub = self._subscriptions.pop(sub_id, None)
            if sub is None:
                return False

            # Убираем из индекса по subscriber
            subscriber_subs = self._by_subscriber.get(sub.subscriber)
            if subscriber_subs is not None:
                subscriber_subs.discard(sub_id)
                if not subscriber_subs:
                    del self._by_subscriber[sub.subscriber]

            return True

    def unsubscribe_all(self, subscriber: str) -> int:
        """Удалить все подписки подписчика (при disconnect).

        Args:
            subscriber: имя процесса-подписчика.

        Returns:
            Количество удалённых подписок.
        """
        with self._lock:
            sub_ids = self._by_subscriber.pop(subscriber, None)
            if not sub_ids:
                return 0

            count = len(sub_ids)
            for sub_id in sub_ids:
                self._subscriptions.pop(sub_id, None)

            return count

    def match(self, delta: Delta) -> list[Subscription]:
        """Найти все подписки, совпадающие с путём дельты.

        Учитывает exclude_sources: если delta.source в exclude_sources
        подписки — подписка пропускается.

        Один subscriber с двумя матчащими подписками → обе вернутся
        (дедупликация — задача DeltaDispatcher).

        Args:
            delta: дельта изменения с path и source.

        Returns:
            Список совпавших подписок.
        """
        path_segs = tuple(delta.path.split(".")) if delta.path else ()

        with self._lock:
            # Копируем список подписок под локом, матчим без лока
            subs_snapshot = list(self._subscriptions.values())

        result: list[Subscription] = []
        for sub in subs_snapshot:
            # Фильтр по источнику
            if sub.exclude_sources and delta.source in sub.exclude_sources:
                continue

            pattern_segs = _split_pattern(sub.pattern)
            if _match_pattern(pattern_segs, path_segs):
                result.append(sub)

        return result

    def get_subscribers(self, path: str) -> set[str]:
        """Получить множество уникальных подписчиков для пути.

        Создаёт временную Delta с пустым source для матчинга.
        exclude_sources не применяется (source пустой).

        Args:
            path: путь в дереве состояний.

        Returns:
            Множество имён подписчиков.
        """
        # Создаём «фиктивную» дельту только для матчинга пути
        dummy_delta = Delta(
            path=path,
            old_value=None,
            new_value=None,
            source="",
        )
        matched = self.match(dummy_delta)
        return {sub.subscriber for sub in matched}

    @property
    def subscription_count(self) -> int:
        """Общее количество активных подписок."""
        with self._lock:
            return len(self._subscriptions)

    # -----------------------------------------------------------------------
    # Публичные снимки для shutdown / DevTools (ADR-SS-013)
    # Раньше StateStoreManager.shutdown и StateInspector.subscriptions лезли
    # к приватным `_lock` / `_subscriptions` / `_by_subscriber`.
    # Теперь публичный, потокобезопасный snapshot.
    # -----------------------------------------------------------------------

    def subscribers(self) -> list[str]:
        """Снимок имён подписчиков, у которых есть хотя бы одна подписка.

        Returns:
            Список имён процессов-подписчиков (без дубликатов, порядок не гарантируется).
        """
        with self._lock:
            return list(self._by_subscriber.keys())

    def all_subscriptions(self) -> list[Subscription]:
        """Снимок всех активных подписок.

        Returns:
            Список Subscription (frozen dataclass — безопасно отдавать наружу).
        """
        with self._lock:
            return list(self._subscriptions.values())


# ---------------------------------------------------------------------------
# Публичные алиасы для использования в health/, middleware/
# Избегаем утечки приватных имён (_match_pattern, _split_pattern)
# ADR-SS-004
# ---------------------------------------------------------------------------

match_pattern = _match_pattern
split_pattern = _split_pattern
