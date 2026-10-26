# -*- coding: utf-8 -*-
"""Контракт на ruamel.yaml: пин минорной версии и форма токенов комментария.

Перенос комментариев при удалении (``_ruamel_doc.delete_item``) опирается на ВНУТРЕННЮЮ форму
токенов ruamel 0.19.x: ``ca.items[key]`` — список из 4 слотов, хвост листа map лежит в слоте 2,
элемента списка — в слоте 0. Эта форма не часть публичного API ruamel; поэтому версия
зафиксирована ``>=0.19.1,<0.20``, а тут — страж: при смене версии или формы тест падает и
называет, что изменилось, — а не молча портит комментарии рецептов.

Форма читается ТОЛЬКО через функции ``recipe/_ruamel_doc.py`` (``load_document``, ``_leaf_slot``,
``_take_tail_text``), не прямым обращением к ``ca``.
"""

from __future__ import annotations

import pytest
from multiprocess_framework.modules.recipe import _ruamel_doc as rd
from ruamel.yaml.tokens import CommentToken

PINNED_MINOR_PREFIX = "0.19."  # литерал: верхняя граница пина (<0.20), а не «текущая версия»

MAP_TEXT = "a: 1  # eol-a\n# tail-a\nb: 2\n"
SEQ_TEXT = "seq:\n  - x  # eol-x\n  # tail-x\n  - y\n"


def _in_pinned_minor(version: str) -> bool:
    return version.startswith(PINNED_MINOR_PREFIX)


def _load(text: str):
    return rd.load_document(rd.make_yaml(), text)


def test_ruamel_version_is_pinned_minor():
    import ruamel.yaml

    version = ruamel.yaml.__version__
    assert _in_pinned_minor(version), (
        f"ruamel.yaml {version}: вне пина 0.19.x. Внутренняя форма токенов комментария "
        f"(ca.items, слоты, CommentToken) проверена только на 0.19.x — "
        f"сначала перепроверь test_*_trailing_comment_token_shape и _ruamel_doc, потом двигай пин."
    )


@pytest.mark.parametrize(
    ("version", "expected"),
    [("0.19.1", True), ("0.19.9", True), ("0.20.0", False), ("0.18.9", False), ("1.0.0", False)],
)
def test_pinned_minor_check_rejects_neighbours(version, expected):
    """Сама проверка границы: верхняя 0.20 и нижняя 0.19 отсекаются литералами."""
    assert _in_pinned_minor(version) is expected


def test_map_trailing_comment_token_shape():
    doc = _load(MAP_TEXT)
    node, key, slot = rd._leaf_slot(doc, "a")
    slots = node.ca.items[key]
    assert len(slots) == 4, (
        f"ruamel.yaml {_version()}: ca.items['a'] длины {len(slots)}, ожидалось 4 — форма слотов изменилась"
    )
    assert slot == 2, f"ruamel.yaml {_version()}: слот хвоста map = {slot}, ожидался 2"
    token = slots[slot]
    assert isinstance(token, CommentToken), (
        f"ruamel.yaml {_version()}: в слоте {slot} map лежит {type(token).__name__}, "
        f"ожидался CommentToken — хвостовой комментарий переехал в другой слот"
    )
    text = rd._take_tail_text(node, key, slot)
    assert token.value.startswith("# eol-a\n"), f"ruamel.yaml {_version()}: токен map = {token.value!r}"
    assert "# tail-a" in token.value
    # _take_tail_text отбрасывает собственный EOL-комментарий, оставляя перенос и хвост соседа
    assert text == "\n# tail-a\n"


def test_seq_trailing_comment_token_shape():
    seq = _load(SEQ_TEXT)["seq"]
    node, key, slot = rd._leaf_slot(seq, 0)
    slots = node.ca.items[key]
    assert len(slots) == 4, (
        f"ruamel.yaml {_version()}: ca.items[0] длины {len(slots)}, ожидалось 4 — форма слотов изменилась"
    )
    assert slot == 0, f"ruamel.yaml {_version()}: слот хвоста seq = {slot}, ожидался 0"
    token = slots[slot]
    assert isinstance(token, CommentToken), (
        f"ruamel.yaml {_version()}: в слоте {slot} seq лежит {type(token).__name__}, "
        f"ожидался CommentToken — хвостовой комментарий переехал в другой слот"
    )
    text = rd._take_tail_text(node, key, slot)
    assert token.value.startswith("# eol-x\n"), f"ruamel.yaml {_version()}: токен seq = {token.value!r}"
    assert "# tail-x" in token.value
    assert text == "\n  # tail-x\n"  # отступ комментария сохранён в тексте токена


def _version() -> str:
    import ruamel.yaml

    return ruamel.yaml.__version__
