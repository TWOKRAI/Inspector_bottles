# -*- coding: utf-8 -*-
"""_ruamel_doc.py — всё знание о внутренностях ruamel для записи рецепта (design.md §9.3).

Приватный модуль ``recipe``. Только здесь живут ``CommentedMap``/``CommentedSeq``,
``ca.items``/``ca.comment``, ``CommentToken``/``StreamMark``, якоря и настройка ``YAML()``.
``yaml_io.py`` зовёт только функции отсюда.

Форма токенов комментария проверена на ruamel.yaml 0.19.x:
  - хвост листа map — ``ca.items[key][2]``, хвост элемента списка — ``ca.items[i][0]``;
  - хвост несёт сначала EOL своей строки (``"\\n"``) или собственный EOL-комментарий
    (``"# eol\\n"``), затем полнострочные комментарии, которые стоят ПЕРЕД следующим соседом;
  - комментарии-заголовок контейнера — ``container.ca.comment[1]`` (список токенов), у
    родителя он же в слоте 3 ключа; эмиттер добавляет к значению токена отступ до
    ``start_mark.column``;
  - опустевший контейнер эмиттер пишет flow (``[]``/``{}``) на строке ключа: комментарий
    перед ним или внутри него даёт невалидный YAML.

ruamel импортируется лениво (внутри функций) — как и в ``yaml_io``.
"""

from __future__ import annotations

from typing import Any


def make_yaml():
    """Сконфигурированный ruamel YAML (round-trip). Лениво — см. docstring ``yaml_io``."""
    try:
        from ruamel.yaml import YAML
    except ModuleNotFoundError as exc:  # pragma: no cover - зависит от окружения
        raise RuntimeError(
            "ruamel.yaml не установлен — нужен для записи YAML с сохранением "
            "комментариев. Установи зависимости: `uv sync` (ruamel.yaml уже в pyproject)."
        ) from exc
    yaml = YAML()  # round-trip по умолчанию
    yaml.preserve_quotes = True
    yaml.width = 4096  # не переносить длинные строки
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def load_document(yaml, text: str) -> Any:
    """Прочитать документ из ТЕКСТА (не байтов — F15); пустой документ -> пустой ``CommentedMap``."""
    from ruamel.yaml.comments import CommentedMap

    doc = yaml.load(text)
    return CommentedMap() if doc is None else doc


def is_bool(value: Any) -> bool:
    """Вид «bool»: ``bool`` и ruamel ``ScalarBoolean`` (он наследует ``int``, а не ``bool``)."""
    if isinstance(value, bool):
        return True
    from ruamel.yaml.scalarbool import ScalarBoolean

    return isinstance(value, ScalarBoolean)


def has_anchor(value: Any) -> bool:
    """У скаляра ruamel есть якорь (``&name``). Plain-значения якоря не имеют."""
    get = getattr(value, "yaml_anchor", None)
    if get is None:
        return False
    anchor = get(any=True)
    return anchor is not None and anchor.value is not None


def delete_item(container: Any, key: Any, owner: tuple[Any, Any] | None = None) -> None:
    """Удалить ``container[key]``, не унося комментарий следующего соседа (design.md §2.3).

    Полнострочные комментарии из хвоста удаляемого (его самый глубокий последний лист)
    переносятся в хвост предыдущего соседа; удаляется первый — в заголовок контейнера.
    Собственный EOL-комментарий удаляемого уходит вместе с ним. Пустой хвост (пустая строка
    перед следующей секцией) у последнего элемента переходит к предыдущему соседу.

    ``owner`` — ``(родитель, ключ)`` контейнера. Опустевший контейнер эмиттер пишет flow
    (``[]``/``{}``) на строке ключа, и комментарий перед ним даёт невалидный YAML (ревью 1.1a):
    поэтому хвост уходит в слот ключа у родителя (после ``key: []``), а заголовок
    контейнера — перед ключом. Plain ``dict``/``list`` — обычный ``del``.
    """
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    if not isinstance(container, (CommentedMap, CommentedSeq)):
        del container[key]
        return
    keys = _keys(container)
    pos = keys.index(key)
    leaf = _leaf_slot(container, key)
    tail, line = _take_tail_text(*leaf), _token_line(*leaf)
    del container[key]
    if not len(container):
        _evacuate_emptied(container, owner, tail, line)
        return
    if not tail.strip():
        # только переводы строк: переносим лишь пустую строку перед следующей секцией
        if pos == len(keys) - 1 and pos > 0 and tail.count(_NL) >= 2:
            prev = _leaf_slot(container, _prev_key(container, keys, pos))
            if not _token_text(*prev).endswith(_NL * 2):
                _append_tail(*prev, tail, line)
        return
    if pos == 0:
        _share_item_header(container, owner)
        _append_header(container, tail, line)
        return
    _append_tail(*_leaf_slot(container, _prev_key(container, keys, pos)), tail, line)


def _share_item_header(container: Any, owner: tuple[Any, Any] | None) -> None:
    """Контейнер — элемент списка: его заголовок и комментарий-перед-элементом у списка
    (``parent.ca.items[i][1]``) должны быть ОДНИМ списком токенов, иначе representer
    ruamel падает ``assert val == nc`` в ``merge_comments`` (ревью 1.1a)."""
    from ruamel.yaml.comments import CommentedSeq

    parent, pkey = owner if owner is not None else (None, None)
    if not isinstance(parent, CommentedSeq):
        return
    slots = parent.ca.items.setdefault(pkey, [None, None, None, None])
    comment = container.ca.comment
    own = comment[1] if comment is not None else None
    shared = slots[1] if slots[1] is not None else (own if own is not None else [])
    if own is not None and own is not shared:
        shared.extend(t for t in own if all(t is not s for s in shared))
    slots[1] = shared
    container.ca.comment = [comment[0] if comment is not None else None, shared]


def replace_item(container: Any, key: Any, value: Any) -> None:
    """``container[key] = value``. Скаляр сменился контейнером — EOL-комментарий прежней строки
    снимается: перед блочным значением эмиттер склеивает строки (``kk: 2.5   -``, ревью 1.1a).
    Полнострочные комментарии хвоста (они стоят перед следующим соседом) остаются в слоте."""
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    old = container[key]
    container[key] = value
    if not isinstance(container, (CommentedMap, CommentedSeq)):
        return
    if not isinstance(value, (dict, list)) or isinstance(old, (dict, list)):
        return
    slot = _slot(container)
    token = _token(container, key, slot)
    if token is None:
        return
    rest = _take_tail_text(container, key, slot)
    container.ca.items[key][slot] = None if not rest.strip() else _comment_token(rest, token)


def _comment_token(value: str, like: Any) -> Any:
    from ruamel.yaml.tokens import CommentToken

    return CommentToken(value, _mark(_first_comment_column(value), getattr(like.start_mark, "line", 0)), None)


# ---------------------------------------------------------------------------
# внутреннее
# ---------------------------------------------------------------------------

_NL = "\n"


def _slot(container: Any) -> int:
    from ruamel.yaml.comments import CommentedMap

    return 2 if isinstance(container, CommentedMap) else 0


def _keys(container: Any) -> list:
    from ruamel.yaml.comments import CommentedMap

    return list(container) if isinstance(container, CommentedMap) else list(range(len(container)))


def _prev_key(container: Any, keys: list, pos: int) -> Any:
    from ruamel.yaml.comments import CommentedMap

    return keys[pos - 1] if isinstance(container, CommentedMap) else pos - 1


def _token(node: Any, key: Any, slot: int) -> Any:
    slots = node.ca.items.get(key)
    return slots[slot] if slots else None


def _token_text(node: Any, key: Any, slot: int) -> str:
    token = _token(node, key, slot)
    return token.value if token is not None else ""


def _token_line(node: Any, key: Any, slot: int) -> int:
    token = _token(node, key, slot)
    return getattr(getattr(token, "start_mark", None), "line", 0) or 0


def _mark(column: int, line: int = 0):
    """Метка нового токена с ``line`` и ``column``. ``CommentMark`` (только ``column``) роняет
    сравнение меток в ruamel: ``StreamMark.__eq__`` читает ``other.line`` (ревью 1.1a)."""
    from ruamel.yaml.error import StreamMark

    return StreamMark(None, 0, line, column)


def _leaf_slot(container: Any, key: Any) -> tuple[Any, Any, int]:
    """(контейнер, ключ, слот) токена после самого глубокого последнего листа ``container[key]``."""
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    node, k = container, key
    while True:
        value = node[k]
        if isinstance(value, CommentedMap) and len(value):
            node, k = value, list(value)[-1]
        elif isinstance(value, CommentedSeq) and len(value):
            node, k = value, len(value) - 1
        else:
            return node, k, _slot(node)


def _take_tail_text(node: Any, key: Any, slot: int) -> str:
    """Текст хвостового токена без собственного EOL-комментария листа."""
    text = _token_text(node, key, slot)
    if text.startswith("#"):  # собственный EOL-комментарий удаляемого — уходит с ним
        text = text[text.index(_NL) :] if _NL in text else ""
    return text


def _evacuate_emptied(container: Any, owner: tuple[Any, Any] | None, tail: str, line: int) -> None:
    """Контейнер опустел: его комментарии — к родителю (заголовок — перед ключом, хвост — после)."""
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    # Блочный пустой контейнер эмиттер пишет ``[]``/``{}`` ПОСЛЕ комментария ключа (на отдельной
    # строке — невалидно); flow-стиль ставит его на строку ключа, комментарий — следом.
    container.fa.set_flow_style()
    parent, pkey = owner if owner is not None else (None, None)
    if not isinstance(parent, (CommentedMap, CommentedSeq)):
        # корень документа: заголовок пустого корня перед ``{}`` валиден
        if tail.strip():
            _append_header(container, tail, line)
        return
    header, eol = _pop_container_comments(container, parent, pkey)
    if header.strip():
        pkeys = _keys(parent)
        ppos = pkeys.index(pkey)
        if ppos == 0:
            _append_header(parent, header, line)
        else:
            _append_tail(*_leaf_slot(parent, _prev_key(parent, pkeys, ppos)), header, line)
    if eol:  # EOL-комментарий строки ключа остаётся на ней: ``key: []  # c``
        tail = eol + (tail[1:] if tail.startswith(_NL) else tail)
    if tail.strip() or tail.count(_NL) >= 2:
        _append_tail(parent, pkey, _slot(parent), tail, line)


def _pop_container_comments(container: Any, parent: Any, pkey: Any) -> tuple[str, str]:
    """Снять с контейнера заголовок (``ca.comment[1]`` и слот 3 ключа у родителя) и EOL-комментарий
    строки ключа (``ca.comment[0]``). Заголовок возвращается в форме хвоста: ``\\n`` + строки с отступом."""
    tokens: list[Any] = []
    eol = ""
    comment = container.ca.comment
    if comment is not None:
        if comment[0] is not None:
            eol = comment[0].value if comment[0].value.endswith(_NL) else comment[0].value + _NL
        tokens.extend(comment[1] or [])
        container.ca.comment = None
    slots = parent.ca.items.get(pkey)
    post = _slot(parent)
    if comment is not None and comment[0] is not None and slots is not None and slots[post] is not None:
        if slots[post] is comment[0] or slots[post].value == comment[0].value:
            slots[post] = None  # тот же EOL-токен зеркалится в слоте ключа у родителя — не дублировать
    if slots is not None and len(slots) > 3 and slots[3]:
        tokens.extend(t for t in slots[3] if all(t is not seen for seen in tokens))
        slots[3] = None
    lines = [(" " * t.start_mark.column + t.value) if t.value.startswith("#") else t.value for t in tokens]
    return (_NL + "".join(lines)) if lines else "", eol


def _append_tail(node: Any, key: Any, slot: int, tail: str, line: int = 0) -> None:
    """Дописать ``tail`` в хвост листа. Ведущий ``\\n`` хвоста — EOL удалённой строки: он лишний,
    если у листа уже есть токен (тот уже несёт свой EOL), иначе он и есть EOL листа."""
    from ruamel.yaml.tokens import CommentToken

    slots = node.ca.items.setdefault(key, [None, None, None, None])
    old = slots[slot]
    if old is None:
        value, column = tail, _first_comment_column(tail)
    else:
        joined = tail[1:] if tail.startswith(_NL) and old.value.endswith(_NL) else tail
        value, column = old.value + joined, old.start_mark.column
        line = getattr(old.start_mark, "line", line)
    slots[slot] = CommentToken(value, _mark(column, line), None)


def _append_header(container: Any, tail: str, line: int = 0) -> None:
    """Перенести ``tail`` в комментарий-заголовок контейнера (удалён первый элемент).

    Эмиттер сам отступает до ``start_mark.column`` — поэтому отступ первой строки
    снимается и передаётся колонкой: строка выходит в файл с прежним отступом."""
    from ruamel.yaml.tokens import CommentToken

    body = tail[1:] if tail.startswith(_NL) else tail
    stripped = body.lstrip(" ")
    if container.ca.comment is None:
        container.ca.comment = [None, []]
    if container.ca.comment[1] is None:
        container.ca.comment[1] = []
    container.ca.comment[1].append(CommentToken(stripped, _mark(len(body) - len(stripped), line), None))


def _first_comment_column(text: str) -> int:
    for part in text.split(_NL):
        if part.strip():
            return len(part) - len(part.lstrip(" "))
    return 0
