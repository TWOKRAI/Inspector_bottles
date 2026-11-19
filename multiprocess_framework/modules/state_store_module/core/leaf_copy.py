"""leaf_copy.py — копия состояния у клиента: хранит ТОЛЬКО листья (ADR-SS-024 A3).

Правило одно для всех копий (``StateProxy._cache``, накопитель стока телеметрии,
``TelemetryReadModel._state``): **копия хранит листья; dict-дельта заменяет
поддерево целиком**. Раньше правило было написано дважды и неполно: dict
раскладывался в листья, но старые листья поддерева не снимались, а read-model
клала dict как значение. Итог — вид робота показывал ``x_mm`` 10.0 при сторе 55.0.

Наивная чистка поддерева сканом копии стоит 835 мкс на dict-дельту при 12 тыс.
ключей. Поэтому рядом с данными живёт индекс детей: цена ``put`` — размер
поддерева, а не размер копии.

Потокобезопасности нет, как и у ``dict`` до неё: лок держит вызывающий.

Purpose:
    Единая копия состояния «путь листа -> значение» для клиентов стора: ``put``
    заменяет поддерево, индекс детей держит цену записи пропорциональной поддереву.

Public API:
    - LeafCopy — копия-листья (MutableMapping) с индексом детей
    - flatten_leaves — раскладка dict в листья (единая для копии и журнала ресинка)
    - project_leaves — проекция копии-листьев на шаблон подписки
    - paths_with_matched_descendants — пути, у которых среди пар есть потомок

Stability: lite
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any, Iterator

from .subscription_manager import match_pattern, split_pattern

__all__ = [
    "LeafCopy",
    "flatten_leaves",
    "paths_with_matched_descendants",
    "project_leaves",
]


def flatten_leaves(path: str, value: Any) -> list[tuple[str, Any]]:
    """Непустой dict -> его листья (в порядке ключей), ``{}`` -> ничего, иначе один лист.

    Единственная раскладка dict -> листья: ею пользуются ``LeafCopy.put`` и журнал
    защиты ресинка ``StateProxy`` (иначе он охранял бы не то, что лежит в кэше).
    """
    if not isinstance(value, dict):
        return [(path, value)]
    out: list[tuple[str, Any]] = []
    for key, nested in value.items():
        out.extend(flatten_leaves(f"{path}.{key}", nested))
    return out


class LeafCopy(MutableMapping[str, Any]):
    """Плоская копия «путь листа -> значение» плюс индекс детей.

    ``_data`` — листья в порядке вставки. ``_kids`` — путь узла -> ПОЛНЫЕ пути
    прямых детей; корень — ключ ``""``.

    Чтение (``[]``, ``get``, ``keys``, ``items`` ...) идёт прямо в ``_data``:
    миксины ``Mapping`` не используются, чтобы ``get`` на горячем пути не шёл
    через ``KeyError``.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._kids: dict[str, set[str]] = {}

    # --- чтение: прямо в _data ---

    def __getitem__(self, path: str) -> Any:
        return self._data[path]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, path: object) -> bool:
        return path in self._data

    def get(self, path: str, default: Any = None) -> Any:
        return self._data.get(path, default)

    def keys(self):  # type: ignore[override]
        return self._data.keys()

    def items(self):  # type: ignore[override]
        return self._data.items()

    def values(self):  # type: ignore[override]
        return self._data.values()

    # --- сырая запись одного листа ---

    def has_children(self, path: str) -> bool:
        """Есть ли в копии листья СТРОГО под ``path`` (по индексу, O(1))."""
        return bool(self._kids.get(path))

    def copy(self) -> dict[str, Any]:
        """Копия листьев ОДНИМ вызовом ``dict`` (атомарна под GIL, быстрее ``dict(self)``).

        ``dict(LeafCopy)`` идёт через ``keys()`` и Python-уровневый ``__getitem__`` на
        каждый ключ: читатель в другом потоке ловит ``KeyError`` от писателя и платит
        в разы дороже. Снимки целой копии берут этот метод.
        """
        return dict(self._data)

    def __setitem__(self, path: str, value: Any) -> None:
        """СЫРАЯ запись одного листа: значение кладётся как есть, dict не разворачивается.

        Пустой путь — ``ValueError``: корень ``""`` служит ключом индекса, и лист с таким
        путём зациклил бы обход (``_kids[""] == {""}``). Хранилище дерева пустой путь не
        отдаёт (``TreeStore.set``/``delete`` его отвергают, ``merge`` строит непустые).
        """
        if not path:
            raise ValueError("LeafCopy: пустой путь")
        if path not in self._data:
            self._link(path)
        self._data[path] = value

    def __delitem__(self, path: str) -> None:
        """Удалить лист и снять связи вверх, пока узел пуст."""
        del self._data[path]
        self._unlink(path)

    def _link(self, path: str) -> None:
        """Связать путь с родителем, и так вверх до первого уже связанного предка."""
        node = path
        while True:
            head, _, _ = node.rpartition(".")
            kids = self._kids.setdefault(head, set())
            if node in kids:
                return
            kids.add(node)
            if not head:
                return
            node = head

    def _unlink(self, path: str) -> None:
        """Снять связи вверх, пока у узла нет ни детей, ни собственного значения."""
        node = path
        while True:
            if node in self._data:
                if not self._kids.get(node):
                    self._kids.pop(node, None)  # лист без детей: пустое множество не держим
                return
            if self._kids.get(node):
                return
            self._kids.pop(node, None)
            head, _, _ = node.rpartition(".")
            kids = self._kids.get(head)
            if kids is None:
                return
            kids.discard(node)
            if not head:
                if not kids:
                    del self._kids[head]
                return
            node = head

    # --- смысловая запись дельты ---

    def put(self, path: str, value: Any) -> tuple[list[str], list[str]]:
        """Дельта заменяет поддерево: dict -> его листья, ``{}`` -> пусто, скаляр -> один лист.

        Возвращает ``(written, removed)``. Листья, которые есть и в старом, и в
        новом поддереве, НЕ удаляются: они сохраняют позицию в порядке вставки,
        а в read-model — кольцо истории. Снимается СТАРОЕ до записи нового: иначе
        снялись бы только что записанные листья.
        """
        if not path:
            raise ValueError("LeafCopy: пустой путь")
        new = flatten_leaves(path, value)
        keep = {p for p, _ in new}
        removed = [p for p in self._leaves_under(path) if p not in keep]
        for p in removed:
            del self[p]
        # Лист-предок (``a`` при записи ``a.b``) тоже снимается: у узла не может
        # быть и значения, и детей.
        head, sep, _ = path.rpartition(".")
        while sep:
            if head in self._data:
                del self[head]
                removed.append(head)
            head, sep, _ = head.rpartition(".")
        for p, v in new:
            self[p] = v
        return [p for p, _ in new], removed

    def drop(self, path: str) -> list[str]:
        """Снять путь и всё поддерево, вернуть снятые листья. Пустой путь — ничего (``[]``)."""
        if not path:
            return []
        gone = self._leaves_under(path)
        for p in gone:
            del self[p]
        return gone

    def _leaves_under(self, path: str) -> list[str]:
        """Листья в поддереве ``path`` (включая сам ``path``) — по индексу, а не сканом копии."""
        out = [path] if path in self._data else []
        stack = list(self._kids.get(path, ()))
        while stack:
            node = stack.pop()
            if node in self._data:
                out.append(node)
            stack.extend(self._kids.get(node, ()))
        return out


# ---------------------------------------------------------------------------
# Проекция копии-листьев на шаблон (Task 2.8a2); серверный replay до Task 2.8 другой
# ---------------------------------------------------------------------------


def paths_with_matched_descendants(pairs: list[tuple[str, Any]]) -> set[str]:
    """Пути, у которых среди pairs есть потомок: тот же шаблон матчит глубже."""
    covered: set[str] = set()
    for path, _ in pairs:
        if not path:
            continue
        covered.add("")  # любой непустой путь — потомок корня
        head, sep, _ = path.rpartition(".")
        while sep and head not in covered:  # цепочка предков уже внесена целиком
            covered.add(head)
            head, sep, _ = head.rpartition(".")
    return covered


def project_leaves(pattern: str, leaves: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """Клиентская проекция копии-листьев на шаблон (ADR-SS-024 A3).

    Пары (путь, значение) по путям, которые матчит шаблон: узел приходит dict-ом
    целиком, если шаблон не матчит его потомков, иначе приходят потомки.
    Порядок — по первому листу узла в ``leaves``.
    """
    segs = split_pattern(pattern.strip("."))
    fixed = sum(1 for s in segs if s != "**")
    var = "**" in segs
    matched: dict[str, None] = {}
    for leaf in leaves:
        parts = tuple(leaf.split("."))
        lo, hi = (max(fixed, 1), len(parts)) if var else (len(segs), min(len(segs), len(parts)))
        for k in range(lo, hi + 1):
            if match_pattern(segs, parts[:k]):
                matched.setdefault(".".join(parts[:k]))
    covered = paths_with_matched_descendants([(p, None) for p in matched])
    nodes = [p for p in matched if p not in covered or p in leaves]
    return _assemble(nodes, leaves)


def _assemble(nodes: list[str], leaves: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """Один проход по ``leaves``: лист кладётся в dict своего узла из ``nodes``.

    Узел — префикс листа по границе-точке или сам лист (тогда значение как есть).
    Результат — по порядку первого появления узла в ``leaves``; лист без узла
    пропускается.

    Скалярный лист — всегда узел (правило стора: лист отдаётся, dict-узел — только если
    не covered). Если в копии рядом лежат ``a.n`` и ``a.n.x`` (сырая запись опроса или
    ресинка): под шаблоном без ``**`` (``a.*``) приходит ``a.n`` значением, а ``a.n.x``
    не вкладывается в него (иначе ``TypeError``); под ``a.**`` приходят оба листа.
    """
    wanted = set(nodes)
    out: dict[str, Any] = {}
    for leaf, value in leaves.items():
        parts = leaf.split(".")
        for k in range(len(parts), 0, -1):  # самый глубокий узел: лист-узел побеждает предка
            node = ".".join(parts[:k])
            if node not in wanted:
                continue
            if k == len(parts):
                out[node] = value
                break
            # Предок-лист между узлом и этим листом (включая сам узел) — он побеждает.
            if any(".".join(parts[:j]) in leaves for j in range(k, len(parts))):
                break
            target = out.setdefault(node, {})
            for key in parts[k:-1]:
                target = target.setdefault(key, {})
            target[parts[-1]] = value
            break
    return list(out.items())
