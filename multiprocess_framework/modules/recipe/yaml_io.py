# -*- coding: utf-8 -*-
"""yaml_io.py — запись YAML с сохранением комментариев (ruamel round-trip).

Generic comment-preserving writer модуля `recipe` (C3, ADR-RCP-005). Раньше жил в
прототипе (`multiprocess_prototype/recipes/yaml_io.py`) — теперь консолидирован во
фреймворк как generic-часть модуля рецептов; прототип держит тонкий шим на этот путь.

Используется там, где файл редактирует и человек, и приложение:
  - рецепты (``recipes/*.yaml``) — заголовок-док + per-node комментарии;
  - главный конфиг ``app.yaml`` — правка умолчания без потери комментариев (активный
    pipeline пишется не сюда, а в ``<stem>.state.yaml``, ADR-APP-008).

Запись атомарна (буфер -> ``service._atomic_write``: tmp + fsync + ``os.replace``),
права файла сохраняются — см. ``_dump_atomic``.

Контракт ``update_yaml_preserving``: обновляет ТОЛЬКО указанные top-level ключи
существующего файла, не трогая остальное (комментарии, порядок, заголовок).
Замена значения ключа сохраняет комментарий, привязанный к самому ключу; теряются
лишь комментарии ВНУТРИ заменяемого поддерева (например, при полной перезаписи
``blueprint`` — это неизбежно, т.к. топология изменилась).

``update_blueprint_metadata_preserving`` работает с формой v3-рецепта (вложенный
``blueprint.metadata``) — это формат рецепта, а не прикладной домен Inspector,
поэтому writer generic (никаких cameras/robot/…).

ruamel импортируется лениво (внутри функции): модуль грузится без падения даже
если зависимость ещё не установлена — ошибка возникает только при реальной записи,
с понятным сообщением «запусти uv sync».
"""

from __future__ import annotations

import copy
import difflib
import io
import json
import os
import stat
from pathlib import Path
from typing import Any

from . import _ruamel_doc as _rd

# Настройка YAML() живёт в _ruamel_doc (design.md §9.3); имя ``_make_yaml`` остаётся здесь.
_make_yaml = _rd.make_yaml

__all__ = [
    "update_yaml_preserving",
    "update_blueprint_metadata_preserving",
    "patch_yaml_preserving",
    "apply_delta",
    "YamlPatchConflict",
]


# ---------------------------------------------------------------------------
# Дельта-движок (C-30, design.md §2): before -> after применяется к цели
# ---------------------------------------------------------------------------


class YamlPatchConflict(ValueError):
    """Путь дельты не ложится на цель (design.md §2.4). Бросается до записи — файл цел."""


_MISSING = object()


def patch_yaml_preserving(path: str | Path, before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Применить дельту ``before -> after`` к ruamel-документу файла, сохранив комментарии.

    Returns:
        ``True`` — файл записан (или создан из ``after``, если его не было);
        ``False`` — дельта пуста, файл не открывался на запись.

    Raises:
        YamlPatchConflict: путь дельты не ложится на файл; файл не тронут.
    """
    path = Path(path)
    yaml = _make_yaml()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        _dump_atomic(yaml, copy.deepcopy(after), path)
        return True
    if _equal(before, after):
        return False

    raw = path.read_bytes()
    eol = _detect_eol(raw)
    # Текст с universal newlines: в ruamel байты не подаются (F15, иначе ``\r\r\n``).
    text = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8").read()
    doc = _rd.load_document(yaml, text)
    if not isinstance(doc, dict):
        raise YamlPatchConflict(f"корень документа {path.name}: {type(doc).__name__}, дельта ждёт mapping")
    _Delta(doc, after).apply_map(doc, before, after, ())
    _dump_atomic(yaml, doc, path, newline=eol)
    return True


def apply_delta(target: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Та же дельта ``before -> after`` на plain-dict ``target``.

    ``target`` не мутируется: возврат — новая глубокая копия с применённой дельтой.

    Raises:
        YamlPatchConflict: путь дельты не ложится на ``target``.
    """
    result = copy.deepcopy(target)
    if not _equal(before, after):
        _Delta(result, after).apply_map(result, before, after, ())
    return result


def _detect_eol(raw: bytes) -> str:
    """EOL файла — терминатор первой строки по сырым байтам; без терминатора — ``\\n``."""
    first = raw.find(b"\n")
    return "\r\n" if first > 0 and raw[first - 1 : first] == b"\r" else "\n"


def _kind(value: Any) -> str:
    """Вид значения (design.md §2.2.3): ``bool`` проверяется раньше ``int``."""
    if _rd.is_bool(value):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if value is None:
        return "none"
    if isinstance(value, dict):
        return "map"
    if isinstance(value, list):
        return "list"
    return "other"


def _equal(a: Any, b: Any) -> bool:
    """Семантическое равенство: порядок ключей map не важен, вид скаляра важен (``1 != True != 1.0``)."""
    kind = _kind(a)
    if kind != _kind(b):
        return False
    if kind == "map":
        return a.keys() == b.keys() and all(_equal(a[k], b[k]) for k in a)
    if kind == "list":
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    return a == b


def _elem_key(value: Any) -> str:
    """Ключ элемента списка для SequenceMatcher (design.md §2.2.2); JSON различает ``1``/``1.0``/``true``."""
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:  # ключи map разных типов не сортируются
        return repr(value)


def _fmt(path: tuple) -> str:
    out = ""
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out or "<корень>"


def _walk(root: Any, path: tuple) -> Any:
    node = root
    for part in path:
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and isinstance(part, int) and 0 <= part < len(node):
            node = node[part]
        else:
            return _MISSING
    return node


def _shared_refs(root: Any) -> dict[int, tuple[Any, list[tuple]]]:
    """Узлы, на которые ссылаются из нескольких мест (якорь + алиас): ``id -> (узел, пути)``.

    Контейнер, встреченный дважды, — алиас; скаляр — только с якорем (мелкие int интернированы).
    Узел держится в значении, чтобы его ``id`` не переиспользовался после удаления."""
    seen: dict[int, tuple[Any, list[tuple]]] = {}

    def walk(node: Any, path: tuple) -> None:
        if isinstance(node, (dict, list)):
            entry = seen.setdefault(id(node), (node, []))
            entry[1].append(path)
            if len(entry[1]) > 1:
                return
            items = node.items() if isinstance(node, dict) else enumerate(node)
            for key, child in items:
                walk(child, (*path, key))
        elif _rd.has_anchor(node):
            seen.setdefault(id(node), (node, []))[1].append(path)

    walk(root, ())
    return {i: entry for i, entry in seen.items() if len(entry[1]) > 1}


class _Delta:
    """Один рекурсивный проход дельты по цели (ruamel-документ или plain-dict)."""

    def __init__(self, target: Any, after_root: dict[str, Any]) -> None:
        self._after_root = after_root
        self._shared = _shared_refs(target)
        self._done: set[int] = set()

    def apply_map(self, node: Any, before: dict, after: dict, path: tuple) -> None:
        if not isinstance(node, dict):
            raise YamlPatchConflict(f"{_fmt(path)}: в цели {type(node).__name__}, дельта ждёт mapping")
        if not self._enter_shared(node, after, path):
            return
        for key in before:
            if key not in after and key in node:
                _rd.delete_item(node, key)
        for key, new in after.items():
            child_path = (*path, key)
            if key not in node:  # нормализованный before шире цели (F10) — создаём целиком
                node[key] = copy.deepcopy(new)
            elif key in before:
                self.set_child(node, key, before[key], new, child_path)
            elif not _equal(node[key], new):  # ключа нет в before, но цель его держит
                self._replace(node, key, new, child_path)

    def apply_list(self, node: Any, before: list, after: list, path: tuple) -> None:
        if not isinstance(node, list):
            raise YamlPatchConflict(f"{_fmt(path)}: в цели {type(node).__name__}, дельта ждёт список")
        if not self._enter_shared(node, after, path):
            return
        matcher = difflib.SequenceMatcher(
            None, [_elem_key(x) for x in before], [_elem_key(x) for x in after], autojunk=False
        )
        # С конца к началу: индексы левее текущего опкода не сдвигаются.
        for tag, i1, i2, j1, j2 in reversed(matcher.get_opcodes()):
            if tag == "equal":
                continue
            if i2 > len(node):
                raise YamlPatchConflict(f"{_fmt((*path, i2 - 1))}: индекс вне списка цели (длина {len(node)})")
            overlap = min(i2 - i1, j2 - j1) if tag == "replace" else 0
            for t in range(overlap):
                self.set_child(node, i1 + t, before[i1 + t], after[j1 + t], (*path, i1 + t))
            for i in reversed(range(i1 + overlap, i2)):
                _rd.delete_item(node, i)
            for offset, value in enumerate(after[j1 + overlap : j2]):
                node.insert(i1 + overlap + offset, copy.deepcopy(value))

    def set_child(self, container: Any, key: Any, before: Any, after: Any, path: tuple) -> None:
        if _equal(before, after):
            return
        if isinstance(before, dict) and isinstance(after, dict):
            self.apply_map(container[key], before, after, path)
        elif isinstance(before, list) and isinstance(after, list):
            self.apply_list(container[key], before, after, path)
        else:  # изменённый скаляр или смена типа (§2.2.4) — значение целиком
            self._replace(container, key, after, path)

    def _replace(self, container: Any, key: Any, after: Any, path: tuple) -> None:
        if id(container[key]) in self._shared:
            raise YamlPatchConflict(f"{_fmt(path)}: узел с якорем заменяется целиком — алиас не разрывается молча")
        container[key] = copy.deepcopy(after)

    def _enter_shared(self, node: Any, after: Any, path: tuple) -> bool:
        """Узел с якорем меняется на месте, только если ``after`` во всех местах ссылок одинаков.

        ``False`` — правка уже применена через другое место ссылки (повтор не нужен)."""
        entry = self._shared.get(id(node))
        if entry is None:
            return True
        if id(node) in self._done:
            return False
        for ref in entry[1]:
            other = _walk(self._after_root, ref)
            if other is not _MISSING and not _equal(other, after):
                places = ", ".join(_fmt(p) for p in entry[1])
                raise YamlPatchConflict(f"{_fmt(path)}: узел с якорем — after различается в местах ссылок ({places})")
        self._done.add(id(node))
        return True


def update_yaml_preserving(path: str | Path, updates: dict[str, Any]) -> None:
    """Обновить top-level ключи YAML-файла, сохранив комментарии/структуру.

    Существующий файл — round-trip load + перезапись значений только ключей из
    ``updates`` (остальное, включая заголовок-комментарий, не тронуто). Новый файл —
    создаётся из ``updates``.

    Args:
        path: путь к YAML-файлу.
        updates: top-level ключи для записи (значения заменяются целиком).
    """
    path = Path(path)
    yaml = _make_yaml()

    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            data = yaml.load(f)
        if data is None:
            from ruamel.yaml.comments import CommentedMap

            data = CommentedMap()
    else:
        from ruamel.yaml.comments import CommentedMap

        data = CommentedMap()

    for key, value in updates.items():
        data[key] = value

    path.parent.mkdir(parents=True, exist_ok=True)
    _dump_atomic(yaml, data, path)


def _dump_atomic(yaml, data: Any, path: Path, newline: str = "\n") -> None:
    """Сериализовать в буфер и записать через ``service._atomic_write`` (tmp в том же
    каталоге + fsync + ``os.replace``; при сбое tmp убирается, старый файл цел).

    Сбой сериализации (ruamel не представил значение) случается ДО открытия файла —
    файл не тронут вовсе. Права файла сохраняются: ``mkstemp`` создаёт tmp с 0600,
    поэтому после замены mode исходного файла возвращается ``chmod``. Нового файла нет —
    сначала ``touch`` (mode по umask процесса, как прежний ``open("w")``), при сбое он
    удаляется.
    ponytail: chmod ПОСЛЕ ``os.replace`` — между заменой и chmod файл виден с 0600
    (читатель-другой пользователь получит EACCES на микросекунды); убрать окно —
    copymode на tmp внутри ``_atomic_write`` (service.py).

    ``newline`` — EOL файла (дельта-движок сохраняет EOL исходника, design.md §2.3);
    ruamel пишет ``\\n``, замена — после дампа."""
    from .service import _atomic_write

    # Прежний open("w") писал СКВОЗЬ симлинк и падал PermissionError на файле 0444 — сохраняем оба
    # свойства для всех вызывающих (ревью 1.2a it.2, F1). ponytail: жёсткая ссылка атомарной заменой
    # рвётся, каталог 0555 теперь не даёт записать (нужен tmp рядом) — ADR-RCP-008; таких файлов 0.
    path = Path(os.path.realpath(path))
    if path.exists() and not os.access(path, os.W_OK):
        raise PermissionError(f"файл только для чтения: {path}")

    buf = io.StringIO()
    yaml.dump(data, buf)
    text = buf.getvalue()
    if newline != "\n":
        text = text.replace("\n", newline)
    raw = text.encode("utf-8")
    created = not path.exists()
    if created:
        path.touch()
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        _atomic_write(path, raw)
        os.chmod(path, mode)
    except BaseException:
        if created:
            path.unlink(missing_ok=True)
        raise


def update_blueprint_metadata_preserving(path: str | Path, metadata_updates: dict[str, Any]) -> None:
    """Точечно обновить ``blueprint.metadata.<key>``, сохранив ВСЕ комментарии.

    В отличие от :func:`update_yaml_preserving`, НЕ перезаписывает весь ``blueprint``
    (что стёрло бы комментарии внутри него — per-node ``# --- ... ---`` и т.п.), а
    меняет только указанные ключи внутри ``blueprint.metadata`` на ruamel-документе.
    Применяется для авто-персиста layout (gui_positions / locked_nodes), который не
    должен портить рецепт при каждом перетаскивании ноды.

    No-op, если файла нет, он пуст или в нём нет вложенного ``blueprint`` (raw-topology
    без editor-обёртки — layout писать некуда).

    Args:
        path: путь к YAML-файлу рецепта.
        metadata_updates: ключи для записи в ``blueprint.metadata`` (значения заменяются
            целиком — напр. ``{"gui_positions": {...}, "locked_nodes": [...]}``).
    """
    from ruamel.yaml.comments import CommentedMap

    path = Path(path)
    if not path.exists():
        return
    yaml = _make_yaml()
    with path.open("r", encoding="utf-8") as f:
        doc = yaml.load(f)
    if not isinstance(doc, dict):
        return
    bp = doc.get("blueprint")
    if not isinstance(bp, dict):
        # raw-topology без вложенного blueprint — layout некуда писать.
        return

    meta = bp.get("metadata")
    if not isinstance(meta, dict):
        meta = CommentedMap()
        bp["metadata"] = meta
    for key, value in metadata_updates.items():
        meta[key] = value

    _dump_atomic(yaml, doc, path)
