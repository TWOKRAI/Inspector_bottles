# -*- coding: utf-8 -*-
"""Task 4.7b — имена SHM-сегментов: один режим, уникальность ВСЕГДА (без env-флагов).

Слепой acceptance-тест (tester, от критериев приёмки 4.7b, без чтения реализации 4.7b).

Контракт (литералы):
  * все ``FW_SHM_*`` сняты (``monkeypatch.delenv``) — поведение от env не зависит;
  * два владельца (``owner="A"`` и ``owner="B"``) с одним ключом ``mask`` получают РАЗНЫЕ имена
    сегментов — и на Windows-ветке имени, и на POSIX-ветке (платформа подменяется:
    ``shm.is_windows`` → True/False);
  * имя несёт владельца и pid (токены, разделённые ``_``): ``"A" in tokens``, ``str(os.getpid()) in tokens``;
  * повторное создание тем же владельцем (после освобождения первого набора) даёт НОВОЕ имя.

Владельцы и ключ короткие намеренно: имя длиннее ``_MAX_BASE_NAME_LEN`` схлопывается в хеш
(владелец перестаёт читаться в имени) — это отдельный механизм, здесь не проверяется.

Допущение: имя берётся из ``create_shm_blocks(...)[i].name`` (фактическое имя сегмента), без
``owner_incarnation=`` — после 4.7b этого kwarg может не быть, поведение обязано быть «всегда уникально».
"""

from __future__ import annotations

import os

import pytest

from multiprocess_framework.modules.shared_resources_module.memory.platform import shm as shm_mod

SIZE = 1024


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in [k for k in os.environ if k.startswith("FW_SHM_") or k == "FW_QOS_PROFILES"]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def made():
    """Реестр созданных сегментов: закрываем всё в конце даже при падении теста."""
    blocks: list = []
    yield blocks
    for b in blocks:
        try:
            shm_mod.close_shm(b, unlink=True)
        except Exception:  # noqa: BLE001 — уборка
            pass


def _create(made: list, owner: str) -> str:
    blocks = shm_mod.create_shm_blocks("mask", SIZE, 1, owner=owner)
    assert blocks is not None and len(blocks) == 1, f"сегмент не создан (owner={owner})"
    made.extend(blocks)
    return blocks[0].name


def _assert_distinct_owners(made: list) -> None:
    pid = str(os.getpid())
    name_a = _create(made, "A")
    name_b = _create(made, "B")
    assert name_a != name_b, f"два владельца с ключом mask получили одно имя: {name_a!r}"
    tokens_a, tokens_b = name_a.split("_"), name_b.split("_")
    assert "A" in tokens_a and "B" in tokens_b, f"владелец не читается в имени: {name_a!r} / {name_b!r}"
    assert pid in tokens_a and pid in tokens_b, f"pid не в имени: {name_a!r} / {name_b!r}"


def test_two_owners_mask_distinct_posix_without_env(monkeypatch, made) -> None:
    monkeypatch.setattr(shm_mod, "is_windows", lambda: False)
    _assert_distinct_owners(made)


def test_two_owners_mask_distinct_windows_without_env(monkeypatch, made) -> None:
    monkeypatch.setattr(shm_mod, "is_windows", lambda: True)
    _assert_distinct_owners(made)


@pytest.mark.parametrize("windows", [False, True], ids=["posix", "windows"])
def test_same_owner_creating_again_gets_new_name(monkeypatch, made, windows: bool) -> None:
    monkeypatch.setattr(shm_mod, "is_windows", lambda: windows)
    first = shm_mod.create_shm_blocks("mask", SIZE, 1, owner="A")
    assert first is not None
    name_1 = first[0].name
    shm_mod.close_shm(first[0], unlink=True)  # первый набор освобождён — коллизии «живого» имени нет
    name_2 = _create(made, "A")
    assert name_2 != name_1, f"повторное создание тем же владельцем вернуло то же имя: {name_1!r}"
