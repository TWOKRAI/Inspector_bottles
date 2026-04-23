"""
TreeStore — иерархическое dict-хранилище с путевым доступом.

Ключевые свойства:
- Данные хранятся как вложенный dict (_root)
- Доступ по точечным путям: "cameras.0.config.fps"
- Ключи пути всегда строки ("0", не int 0)
- Потокобезопасность через RLock
- Каждое изменение возвращает Delta (или None если значение не изменилось)
"""
from __future__ import annotations

import copy
import threading
from typing import Any, Dict, List, Optional

from state_store.core.delta import Delta, MISSING, Transaction

# Приватные сентинелы для внутренних проверок
_SENTINEL = object()   # для get() default — отличить "default не задан" от None
_NOT_FOUND = object()  # для _merge_recursive — проверка наличия ключа


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _resolve_path(path: str) -> List[str]:
    """Разбивает точечный путь на список ключей.

    Пустой путь → пустой список (означает корень дерева).
    Примеры:
        "cameras.0.config.fps" → ["cameras", "0", "config", "fps"]
        "" → []
    """
    if not path:
        return []
    return path.split(".")


def _deep_copy(value: Any) -> Any:
    """Возвращает глубокую копию значения."""
    return copy.deepcopy(value)


def _values_equal(a: Any, b: Any) -> bool:
    """Сравнивает два значения. Dict'ы сравниваются рекурсивно."""
    try:
        return a == b
    except Exception:
        # на случай нестандартных объектов
        return False


# ---------------------------------------------------------------------------
# TreeStore
# ---------------------------------------------------------------------------

class TreeStore:
    """Иерархическое dict-хранилище с путевым доступом.

    Потокобезопасное. Все операции атомарны на уровне одного пути.
    Возвращает Delta при каждом изменении (для уведомлений).

    Примеры использования:
        store = TreeStore()
        delta = store.set("cameras.0.config.fps", 30)
        fps = store.get("cameras.0.config.fps")  # → 30
        store.merge("cameras.0", {"state": {"status": "running"}})
    """

    def __init__(self, initial: Optional[Dict[str, Any]] = None) -> None:
        # внутреннее дерево данных
        self._root: Dict[str, Any] = _deep_copy(initial) if initial else {}
        # RLock позволяет одному потоку рекурсивно захватывать блокировку
        self._lock = threading.RLock()

    # -----------------------------------------------------------------------
    # Внутренние методы навигации
    # -----------------------------------------------------------------------

    def _navigate(
        self,
        keys: List[str],
        create: bool = False,
    ) -> tuple[Dict[str, Any], str]:
        """Навигирует по дереву и возвращает (родительский_dict, последний_ключ).

        Args:
            keys: список ключей пути (непустой).
            create: если True — автоматически создаёт промежуточные dict'ы.

        Returns:
            (parent_dict, last_key) — dict, содержащий конечный узел, и его ключ.

        Raises:
            KeyError: если промежуточный узел отсутствует и create=False.
            TypeError: если промежуточный узел — не dict.
        """
        node = self._root
        # проходим все ключи кроме последнего
        for key in keys[:-1]:
            if key not in node:
                if create:
                    node[key] = {}
                else:
                    raise KeyError(f"Путь не существует: ключ '{key}' отсутствует")
            child = node[key]
            if not isinstance(child, dict):
                raise TypeError(
                    f"Промежуточный узел '{key}' — не dict (тип: {type(child).__name__})"
                )
            node = child
        return node, keys[-1]

    # -----------------------------------------------------------------------
    # Чтение
    # -----------------------------------------------------------------------

    def get(self, path: str, default: Any = _SENTINEL) -> Any:
        """Читает значение по пути.

        "cameras.0.config.fps" → 30.

        Args:
            path: точечный путь к узлу.
            default: возвращается если путь не существует.

        Raises:
            KeyError: если путь не существует и default не задан.
        """
        with self._lock:
            keys = _resolve_path(path)
            if not keys:
                # пустой путь → всё дерево
                return _deep_copy(self._root)
            try:
                parent, last_key = self._navigate(keys)
                if last_key not in parent:
                    raise KeyError(path)
                return _deep_copy(parent[last_key])
            except (KeyError, TypeError):
                if default is not _SENTINEL:
                    return default
                raise KeyError(f"Путь не существует: '{path}'")

    def get_subtree(self, path: str) -> Dict[str, Any]:
        """Возвращает поддерево как deep-copy dict.

        path='' → всё дерево.
        """
        with self._lock:
            keys = _resolve_path(path)
            if not keys:
                return _deep_copy(self._root)
            try:
                parent, last_key = self._navigate(keys)
                if last_key not in parent:
                    raise KeyError(f"Путь не существует: '{path}'")
                value = parent[last_key]
                if not isinstance(value, dict):
                    raise TypeError(
                        f"Узел '{path}' — не dict (тип: {type(value).__name__})"
                    )
                return _deep_copy(value)
            except (KeyError, TypeError):
                raise

    def has(self, path: str) -> bool:
        """Проверяет, существует ли путь в дереве."""
        with self._lock:
            keys = _resolve_path(path)
            if not keys:
                return True  # корень всегда существует
            try:
                parent, last_key = self._navigate(keys)
                return last_key in parent
            except (KeyError, TypeError):
                return False

    def keys(self, path: str = "") -> List[str]:
        """Возвращает список дочерних ключей узла.

        "cameras" → ["0", "1"]
        "" → ключи корня дерева
        """
        with self._lock:
            keys = _resolve_path(path)
            if not keys:
                return list(self._root.keys())
            try:
                parent, last_key = self._navigate(keys)
                if last_key not in parent:
                    raise KeyError(f"Путь не существует: '{path}'")
                node = parent[last_key]
                if not isinstance(node, dict):
                    return []
                return list(node.keys())
            except (KeyError, TypeError):
                raise

    # -----------------------------------------------------------------------
    # Запись
    # -----------------------------------------------------------------------

    def set(
        self, path: str, value: Any, source: str = ""
    ) -> Optional[Delta]:
        """Устанавливает значение по пути.

        Автоматически создаёт промежуточные узлы (как mkdir -p).
        Возвращает Delta или None если значение не изменилось.

        Args:
            path: точечный путь (непустой).
            value: новое значение.
            source: строка-источник изменения (для Delta).
        """
        with self._lock:
            keys = _resolve_path(path)
            if not keys:
                raise ValueError("Путь не может быть пустым для set()")

            # создаём промежуточные узлы
            parent, last_key = self._navigate(keys, create=True)

            # запоминаем старое значение
            raw_old = parent.get(last_key, _SENTINEL)
            key_existed = raw_old is not _SENTINEL
            old_value = _deep_copy(raw_old) if key_existed else MISSING
            new_value_copy = _deep_copy(value)

            # проверяем, изменилось ли значение
            if key_existed and _values_equal(old_value, new_value_copy):
                return None  # значение не изменилось

            parent[last_key] = _deep_copy(value)

            return Delta(
                path=path,
                old_value=old_value,  # MISSING если ключа не было
                new_value=new_value_copy,
                source=source,
            )

    def merge(
        self, path: str, data: Dict[str, Any], source: str = ""
    ) -> List[Delta]:
        """Глубокий merge dict в поддерево.

        Dict'ы мержатся рекурсивно, скаляры перезаписываются.
        Возвращает список дельт (по одной на каждое изменившееся листовое значение).

        Args:
            path: путь к поддереву (может быть пустым — тогда мерж в корень).
            data: данные для мержа.
            source: источник изменения.
        """
        with self._lock:
            deltas: List[Delta] = []
            self._merge_recursive(path, data, source, deltas)
            return deltas

    def _merge_recursive(
        self,
        path: str,
        data: Dict[str, Any],
        source: str,
        deltas: List[Delta],
    ) -> None:
        """Рекурсивно мержит data в поддерево по path, собирая дельты."""
        for key, value in data.items():
            child_path = f"{path}.{key}" if path else key
            if isinstance(value, dict):
                # если целевой узел тоже dict — рекурсивно мержим
                # используем _NOT_FOUND как сентинел чтобы не конфликтовать с _MISSING
                existing = self.get(child_path, default=_NOT_FOUND)
                if existing is not _NOT_FOUND and isinstance(existing, dict):
                    self._merge_recursive(child_path, value, source, deltas)
                else:
                    # целевой узел не dict или не существует — перезаписываем
                    delta = self.set(child_path, value, source=source)
                    if delta is not None:
                        deltas.append(delta)
            else:
                delta = self.set(child_path, value, source=source)
                if delta is not None:
                    deltas.append(delta)

    def delete(self, path: str, source: str = "") -> Optional[Delta]:
        """Удаляет узел по пути.

        Возвращает Delta или None если узел не существовал.

        Args:
            path: точечный путь к узлу.
            source: источник изменения.
        """
        with self._lock:
            keys = _resolve_path(path)
            if not keys:
                raise ValueError("Путь не может быть пустым для delete()")
            try:
                parent, last_key = self._navigate(keys)
            except (KeyError, TypeError):
                return None  # промежуточный узел не существует

            if last_key not in parent:
                return None  # узел уже отсутствует

            old_value = _deep_copy(parent[last_key])
            del parent[last_key]

            return Delta(
                path=path,
                old_value=old_value,
                new_value=MISSING,
                source=source,
            )

    # -----------------------------------------------------------------------
    # Транзакции
    # -----------------------------------------------------------------------

    def transaction(self, label: str = "") -> Transaction:
        """Создаёт транзакцию для batch-операций.

        Использование:
            with store.transaction("recipe_load") as tx:
                tx.set("cameras.0.config.fps", 30)
                tx.set("cameras.0.config.type", "webcam")
            # все дельты с одним transaction_id
        """
        return Transaction(self, label)

    # -----------------------------------------------------------------------
    # Снимки
    # -----------------------------------------------------------------------

    def snapshot(self, paths: Optional[List[str]] = None) -> Dict[str, Any]:
        """Создаёт снимок дерева (deep copy).

        Args:
            paths: None → всё дерево.
                   List[str] → только ветви, совпадающие с паттернами.
                   Поддерживает wildcard: '*' = один сегмент, '**' = любое количество.

        Returns:
            dict — изолированный снимок (мутации не затрагивают хранилище).
        """
        with self._lock:
            if paths is None:
                return _deep_copy(self._root)

            # собираем только совпадающие ветви
            result: Dict[str, Any] = {}
            for pattern in paths:
                pattern_keys = _resolve_path(pattern)
                self._collect_matching(self._root, pattern_keys, 0, result)
            return result

    def _collect_matching(
        self,
        node: Any,
        pattern_keys: List[str],
        depth: int,
        result: Dict[str, Any],
    ) -> None:
        """Рекурсивно собирает узлы, совпадающие с паттерном.

        Args:
            node: текущий узел дерева.
            pattern_keys: сегменты паттерна.
            depth: текущая глубина в паттерне.
            result: dict-накопитель результата (мутируется).
        """
        if depth >= len(pattern_keys):
            # паттерн исчерпан — берём текущий узел
            # (результат уже записывается на уровень выше)
            return

        if not isinstance(node, dict):
            return

        segment = pattern_keys[depth]
        is_last = depth == len(pattern_keys) - 1

        if segment == "**":
            # '**' совпадает с любым количеством уровней
            if is_last:
                # весь поддерево
                for key in node:
                    result[key] = _deep_copy(node[key])
            else:
                # '**' может поглотить 0 или более уровней
                # вариант 0: пропускаем ** и сразу смотрим следующий сегмент
                self._collect_matching(node, pattern_keys, depth + 1, result)
                # вариант 1+: ** поглощает один уровень, затем продолжаем с **
                for key, child in node.items():
                    if isinstance(child, dict):
                        sub: Dict[str, Any] = {}
                        self._collect_matching(child, pattern_keys, depth, sub)
                        if sub:
                            if key not in result:
                                result[key] = {}
                            if isinstance(result[key], dict):
                                _deep_merge_inplace(result[key], sub)
        elif segment == "*":
            # '*' совпадает ровно с одним сегментом (любым ключом)
            for key, child in node.items():
                if is_last:
                    result[key] = _deep_copy(child)
                else:
                    if isinstance(child, dict):
                        sub = {}
                        self._collect_matching(child, pattern_keys, depth + 1, sub)
                        if sub:
                            if key not in result:
                                result[key] = {}
                            if isinstance(result[key], dict):
                                _deep_merge_inplace(result[key], sub)
        else:
            # конкретный ключ
            if segment not in node:
                return
            child = node[segment]
            if is_last:
                result[segment] = _deep_copy(child)
            else:
                if isinstance(child, dict):
                    if segment not in result:
                        result[segment] = {}
                    if isinstance(result[segment], dict):
                        self._collect_matching(
                            child, pattern_keys, depth + 1, result[segment]
                        )

    def restore(
        self, data: Dict[str, Any], path: str = "", source: str = ""
    ) -> List[Delta]:
        """Заменяет поддерево целиком.

        Текущее содержимое поддерева удаляется, новые данные устанавливаются.
        Возвращает все дельты (удаления + установки).

        Args:
            data: новые данные.
            path: путь к поддереву ("" = корень).
            source: источник изменения.
        """
        with self._lock:
            deltas: List[Delta] = []

            keys = _resolve_path(path)
            if not keys:
                # заменяем корень
                old_root = _deep_copy(self._root)
                new_root = _deep_copy(data)
                if not _values_equal(old_root, new_root):
                    deltas.append(
                        Delta(
                            path="",
                            old_value=old_root,
                            new_value=new_root,
                            source=source,
                        )
                    )
                    self._root = new_root
                return deltas

            # заменяем поддерево
            parent, last_key = self._navigate(keys, create=True)
            old_value = _deep_copy(parent.get(last_key, _SENTINEL))
            new_value = _deep_copy(data)

            if old_value is not _SENTINEL and _values_equal(old_value, new_value):
                return deltas  # без изменений

            parent[last_key] = new_value
            deltas.append(
                Delta(
                    path=path,
                    old_value=MISSING if old_value is _SENTINEL else old_value,
                    new_value=new_value,
                    source=source,
                )
            )
            return deltas


# ---------------------------------------------------------------------------
# Утилита для внутреннего merge dict'ов
# ---------------------------------------------------------------------------

def _deep_merge_inplace(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    """Рекурсивно мержит source в target (in-place)."""
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            _deep_merge_inplace(target[key], value)
        else:
            target[key] = value
