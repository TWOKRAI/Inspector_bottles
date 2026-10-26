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
from typing import Any, Callable

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
    _Delta(doc, after).run(doc, before, after)
    _dump_atomic(yaml, doc, path, newline=eol, expected=_expected_by_pyyaml(text, before, after))
    return True


def apply_delta(
    target: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    on_insert: Callable[[tuple, Any], Any] | None = None,
) -> dict[str, Any]:
    """Та же дельта ``before -> after`` на plain-dict ``target``.

    ``target`` не мутируется: возврат — новая глубокая копия с применённой дельтой.

    ``on_insert(path, value) -> value`` вызывается ТОЛЬКО для поддерева, вставляемого целиком: ключа или
    элемента списка нет в ``target`` и он действительно создаётся (design.md §2.3, §10.5). Результат вызова
    встаёт в ``target`` вместо ``value`` (глубокой копии из ``after``). Изменённые листья, замена значения
    и ключ, который не создаётся (равен в ``before`` и ``after``), хук не вызывают; детей вставленного
    поддерева он не обходит. ``path`` — кортеж ключей и индексов от корня ``after`` (место поддерева в ``after``).

    Raises:
        YamlPatchConflict: путь дельты не ложится на ``target``.
    """
    result = copy.deepcopy(target)
    if not _equal(before, after):
        _Delta(result, after, on_insert).run(result, before, after)
    return result


def _expected_by_pyyaml(text: str, before: dict[str, Any], after: dict[str, Any]) -> Any:
    """Чтение дампа глазами PyYAML, которое ждём после записи: исходный текст, прочитанный PyYAML, плюс та же дельта.

    Неизменённое слово YAML 1.1 (``yes``, ``on``) ruamel (1.2) держит строкой, а PyYAML читает как bool — сверка
    дампа с ruamel-документом отказывала бы любую запись по такому файлу (design.md §7, Р4). Исходный текст,
    который PyYAML не читает или дельта на него не ложится, — ``_MISSING``: сверка с ruamel-документом, как раньше.
    """
    import yaml as pyyaml

    try:
        original = pyyaml.safe_load(text)
        if not isinstance(original, dict):
            return _MISSING
        return apply_delta(original, before, after)
    except (pyyaml.YAMLError, YamlPatchConflict):
        return _MISSING


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
    if isinstance(value, (list, tuple)):  # кортеж ruamel пишет списком (ревью 1.1b р2, F1)
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

    def __init__(
        self, target: Any, after_root: dict[str, Any], on_insert: Callable[[tuple, Any], Any] | None = None
    ) -> None:
        self._after_root = after_root
        self._on_insert = on_insert
        self._shared = _shared_refs(target)
        self._done: set[int] = set()

    def run(self, target: Any, before: dict, after: dict) -> None:
        """Применить дельту, сверить места ссылок алиасов уже на итоговой цели и довести
        ruamel-документ до формы для эмиттера (flow пустым контейнерам, общий заголовок элемента)."""
        self.apply_map(target, before, after, ())
        self._check_shared(target)
        _rd.finalize(target)

    def _check_shared(self, target: Any) -> None:
        """Узел с якорем во ВСЕХ местах ссылок итоговой цели равен ``after`` там же (design.md §2.3).

        Пути берутся из цели ПОСЛЕ правки — сдвиги списков уже учтены (ревью 1.1a, S1/S3)."""
        for node, refs in _shared_refs(target).values():
            for ref in refs:
                expected = _walk(self._after_root, ref)
                if expected is not _MISSING and not _equal(node, expected):
                    places = ", ".join(_fmt(p) for p in refs)
                    raise YamlPatchConflict(
                        f"{_fmt(ref)}: узел с якорем — after различается в местах ссылок ({places})"
                    )

    def apply_map(self, node: Any, before: dict, after: dict, path: tuple, owner: tuple | None = None) -> None:
        if not isinstance(node, dict):
            raise YamlPatchConflict(f"{_fmt(path)}: в цели {type(node).__name__}, дельта ждёт mapping")
        if not self._enter_shared(node, after, path):
            return
        for key in before:
            if key not in after and key in node:
                _rd.delete_item(node, key, owner=owner)
        for key, new in after.items():
            child_path = (*path, key)
            if key not in node:  # нормализованный before шире цели
                if key in before and _equal(before[key], new):
                    continue  # правки по пути нет — умолчание в файл не пишется (design §2.3, §10.5)
                node[key] = self._inserted(child_path, new)  # создаём целиком, с промежуточными контейнерами (F10)
            elif key in before:
                self.set_child(node, key, before[key], new, child_path)
            elif not _equal(node[key], new):  # ключа нет в before, но цель его держит
                self._replace(node, key, new, child_path)

    def apply_list(self, node: Any, before: list, after: list, path: tuple, owner: tuple | None = None) -> None:
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
                _rd.delete_item(node, i, owner=owner)
            for offset, value in enumerate(after[j1 + overlap : j2]):
                # Путь для хука — место элемента в ``after`` (не в промежуточном списке цели).
                node.insert(i1 + overlap + offset, self._inserted((*path, j1 + overlap + offset), value))

    def _inserted(self, path: tuple, value: Any) -> Any:
        """Копия вставляемого поддерева; с ``on_insert`` — его результат (design.md §2.3)."""
        copied = copy.deepcopy(value)
        return copied if self._on_insert is None else self._on_insert(path, copied)

    def set_child(self, container: Any, key: Any, before: Any, after: Any, path: tuple) -> None:
        if _equal(before, after):
            return
        if isinstance(before, dict) and isinstance(after, dict):
            self.apply_map(container[key], before, after, path, owner=(container, key))
        elif isinstance(before, list) and isinstance(after, list):
            self.apply_list(container[key], before, after, path, owner=(container, key))
        else:  # изменённый скаляр или смена типа (§2.2.4) — значение целиком
            self._replace(container, key, after, path)

    def _replace(self, container: Any, key: Any, after: Any, path: tuple) -> None:
        if id(container[key]) in self._shared:
            raise YamlPatchConflict(f"{_fmt(path)}: узел с якорем заменяется целиком — алиас не разрывается молча")
        _rd.replace_item(container, key, copy.deepcopy(after))

    def _enter_shared(self, node: Any, after: Any, path: tuple) -> bool:
        """Узел с якорем правится один раз; ``False`` — правка уже применена через другое место
        ссылки. Равенство ``after`` во всех местах ссылок сверяет ``_check_shared`` ПОСЛЕ правки:
        буквальные пути цели до правки не учитывают сдвиги списков (ревью 1.1a, S1/S3)."""
        if id(node) not in self._shared:
            return True
        if id(node) in self._done:
            return False
        self._done.add(id(node))
        return True


def update_yaml_preserving(path: str | Path, updates: dict[str, Any]) -> None:
    """Обновить top-level ключи YAML-файла, сохранив комментарии/структуру.

    Тонкий контракт над дельта-движком (design.md §2.1): ``before`` — текущее поддерево
    файла по ключам ``updates``, ``after`` — те же ключи с новыми значениями. Значение
    ключа заменяется целиком по итоговому содержимому (ключи внутри, которых нет в новом
    значении, удаляются), но равные части не трогаются — комментарии внутри них живы.
    Пустая дельта — без записи; EOL файла сохраняется. Новый файл создаётся из ``updates``.
    Узел с якорем меняется на месте во всех местах ссылок, в том числе вне переданных ключей
    (design.md §2.3).

    Args:
        path: путь к YAML-файлу.
        updates: top-level ключи для записи (значения заменяются целиком).
    """
    path = Path(path)
    after = dict(updates)
    if not path.exists():
        patch_yaml_preserving(path, {}, after)
        return
    current = _read_plain(path)
    if not isinstance(current, dict):
        raise YamlPatchConflict(f"корень документа {path.name}: {type(current).__name__}, ждали mapping")
    before = {key: current[key] for key in after if key in current}
    patch_yaml_preserving(path, before, after)


def _read_plain(path: Path) -> Any:
    """Содержимое файла как plain-структура (dict/list; скаляры ruamel — подклассы builtin).

    Текст с universal newlines (как в движке, F15); пустой файл -> ``{}``."""
    text = io.TextIOWrapper(io.BytesIO(path.read_bytes()), encoding="utf-8").read()
    return _plain(_rd.load_document(_make_yaml(), text))


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_plain(child) for child in value]
    return value


def _dump_atomic(yaml, data: Any, path: Path, newline: str = "\n", expected: Any = _MISSING) -> None:
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
    try:
        yaml.dump(data, buf)
    except AssertionError as exc:  # внутренний assert ruamel (``merge_comments``), не наш контракт
        raise ValueError(f"{path}: дамп ruamel не удался — запись отменена, файл цел") from exc
    text = buf.getvalue()
    _verify_dump(text, data, path, expected)
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


def _verify_dump(text: str, data: Any, path: Path, expected: Any = _MISSING) -> None:
    """Страховка записи: дамп читается тем загрузчиком, которым рецепты читают потребители
    (PyYAML ``safe_load``, YAML 1.1), и даёт те же данные — иначе ``ValueError`` до записи.

    Ловит невалидный YAML от переноса комментариев, склейку строк и строки вида ``On``/``yes``,
    которые дампер YAML 1.2 пишет без кавычек, а PyYAML читает как bool (ревью 1.1a).

    ``expected`` — чтение, которое ждём, уже в пространстве PyYAML (``_expected_by_pyyaml``); без него —
    записываемые данные ``data``. Нужен, чтобы неизменённое ``yes`` файла не отказывало запись (Р4)."""
    import yaml as pyyaml

    try:
        loaded = pyyaml.safe_load(text)
    except pyyaml.YAMLError as exc:
        raise ValueError(f"{path.name}: дамп не читается PyYAML — запись отменена, файл цел: {exc}") from exc
    if not _equal(loaded, _plain(data) if expected is _MISSING else expected):
        raise ValueError(f"{path.name}: PyYAML читает дамп иначе, чем записываемые данные — запись отменена, файл цел")


def update_blueprint_metadata_preserving(path: str | Path, metadata_updates: dict[str, Any]) -> None:
    """Точечно обновить ``blueprint.metadata.<key>``, сохранив ВСЕ комментарии.

    Тонкий контракт над дельта-движком (design.md §2.1): в отличие от
    :func:`update_yaml_preserving`, ``before``/``after`` строятся на уровне
    ``blueprint.metadata`` — остальной ``blueprint`` (per-node ``# --- ... ---`` и т.п.) в
    дельту не входит. Значение каждого ключа заменяется целиком по итоговому содержимому,
    равные части и комментарии внутри них не трогаются; пустая дельта — без записи.
    Узел с якорем меняется на месте во всех местах ссылок, в том числе вне ``blueprint.metadata``
    (design.md §2.3).
    Применяется для авто-персиста layout (gui_positions / locked_nodes), который не
    должен портить рецепт при каждом перетаскивании ноды.

    No-op, если файла нет, он пуст или в нём нет вложенного ``blueprint`` (raw-topology
    без editor-обёртки — layout писать некуда).

    Args:
        path: путь к YAML-файлу рецепта.
        metadata_updates: ключи для записи в ``blueprint.metadata`` (значения заменяются
            целиком — напр. ``{"gui_positions": {...}, "locked_nodes": [...]}``).
    """
    path = Path(path)
    if not path.exists():
        return
    current = _read_plain(path)
    if not isinstance(current, dict):
        return
    blueprint = current.get("blueprint")
    if not isinstance(blueprint, dict):
        # raw-topology без вложенного blueprint — layout некуда писать.
        return

    if "metadata" in blueprint:
        old_meta = blueprint["metadata"]
        base = old_meta if isinstance(old_meta, dict) else {}
        before = {"blueprint": {"metadata": old_meta}}
    else:
        base = {}
        before = {"blueprint": {}}
    after = {"blueprint": {"metadata": {**base, **metadata_updates}}}
    patch_yaml_preserving(path, before, after)
