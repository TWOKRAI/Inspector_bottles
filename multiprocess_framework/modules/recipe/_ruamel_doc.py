# -*- coding: utf-8 -*-
"""_ruamel_doc.py — всё знание о внутренностях ruamel для записи рецепта (design.md §9.3).

Приватный модуль ``recipe``. Только здесь живут ``CommentedMap``/``CommentedSeq``,
``ca.items``/``ca.comment``, ``CommentToken``/``CommentMark``, якоря и настройка ``YAML()``.
``yaml_io.py`` зовёт только функции отсюда.

Форма токенов комментария проверена на ruamel.yaml 0.19.x:
  - хвост листа map — ``ca.items[key][2]``, хвост элемента списка — ``ca.items[i][0]``;
  - хвост несёт сначала EOL своей строки (``"\\n"``) или собственный EOL-комментарий
    (``"# eol\\n"``), затем полнострочные комментарии, которые стоят ПЕРЕД следующим соседом;
  - комментарии-заголовок контейнера — ``container.ca.comment[1]`` (список токенов);
    эмиттер добавляет к значению токена отступ до ``start_mark.column``.

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


def delete_item(container: Any, key: Any) -> None:
    """Удалить ``container[key]``, не унося комментарий следующего соседа (design.md §2.3).

    Полнострочные комментарии из хвоста удаляемого (его самый глубокий последний лист)
    переносятся в хвост предыдущего соседа; удаляется первый — в заголовок контейнера.
    Собственный EOL-комментарий удаляемого уходит вместе с ним. Plain ``dict``/``list`` —
    обычный ``del``.
    """
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    if not isinstance(container, (CommentedMap, CommentedSeq)):
        del container[key]
        return
    keys = list(container) if isinstance(container, CommentedMap) else list(range(len(container)))
    pos = keys.index(key)
    tail = _take_tail_text(*_leaf_slot(container, key))
    del container[key]
    if not tail.strip():
        return  # переносить нечего (только перевод строки / пустые строки)
    if pos == 0:
        _append_header(container, tail)
        return
    prev_key = keys[pos - 1] if isinstance(container, CommentedMap) else pos - 1
    _append_tail(*_leaf_slot(container, prev_key), tail)


# ---------------------------------------------------------------------------
# внутреннее
# ---------------------------------------------------------------------------


def _slot(container: Any) -> int:
    from ruamel.yaml.comments import CommentedMap

    return 2 if isinstance(container, CommentedMap) else 0


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
    slots = node.ca.items.get(key)
    token = slots[slot] if slots else None
    text = token.value if token is not None else ""
    if text.startswith("#"):  # собственный EOL-комментарий удаляемого — уходит с ним
        text = text[text.index("\n") :] if "\n" in text else ""
    return text


def _append_tail(node: Any, key: Any, slot: int, tail: str) -> None:
    """Дописать ``tail`` в хвост листа. Ведущий ``\\n`` хвоста — EOL удалённой строки: он лишний,
    если у листа уже есть токен (тот уже несёт свой EOL), иначе он и есть EOL листа."""
    from ruamel.yaml.error import CommentMark
    from ruamel.yaml.tokens import CommentToken

    slots = node.ca.items.setdefault(key, [None, None, None, None])
    old = slots[slot]
    if old is None:
        value, column = tail, _first_comment_column(tail)
    else:
        joined = tail[1:] if tail.startswith("\n") and old.value.endswith("\n") else tail
        value, column = old.value + joined, old.start_mark.column
    slots[slot] = CommentToken(value, CommentMark(column), None)


def _append_header(container: Any, tail: str) -> None:
    """Перенести ``tail`` в комментарий-заголовок контейнера (удалён первый элемент).

    Эмиттер сам отступает до ``start_mark.column`` — поэтому отступ первой строки
    снимается и передаётся колонкой: строка выходит в файл с прежним отступом."""
    from ruamel.yaml.error import CommentMark
    from ruamel.yaml.tokens import CommentToken

    body = tail[1:] if tail.startswith("\n") else tail
    stripped = body.lstrip(" ")
    if container.ca.comment is None:
        container.ca.comment = [None, []]
    if container.ca.comment[1] is None:
        container.ca.comment[1] = []
    container.ca.comment[1].append(CommentToken(stripped, CommentMark(len(body) - len(stripped)), None))


def _first_comment_column(text: str) -> int:
    for line in text.split("\n"):
        if line.strip():
            return len(line) - len(line.lstrip(" "))
    return 0
