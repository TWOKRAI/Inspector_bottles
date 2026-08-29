# -*- coding: utf-8 -*-
"""RED (Task 0.1, критерий 2) — голый `forget_declarations()` обязан отказывать.

Независимый приёмочный тест, написанный ДО реализации. Источник — Acceptance
criteria задачи 0.1 (`plans/observability-closure/phase-0-trust-gate.md`): «голый
сброс каталога больше невозможен», и Step 3 той же задачи, где названа КОНКРЕТНАЯ
фикстура-замена — ``declarations_snapshot`` (autouse, session- и function-scope в
`statistics_module/tests/conftest.py` и `process_module/tests/conftest.py`). Это
формулировка задачи, а не подсмотренная реализация — реализации ещё нет.

Сейчас `forget_declarations(kind=None, names=None)` тихо чистит реестр ЦЕЛИКОМ и
не отказывает никак (проверено вручную интерпретатором перед записью теста).
После задачи он обязан поднимать `TypeError`, и текст ошибки должен НАЗЫВАТЬ
адрес фикстуры-замены — иначе автор следующего голого вызова получит красный
тест без подсказки, чем пользоваться вместо, и полезет искать сам.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules import observability_declarations as decls

#: Имя фикстуры-замены по Step 3 задачи 0.1 — то, что текст ошибки обязан назвать.
_REPLACEMENT_FIXTURE_NAME = "declarations_snapshot"


def test_bare_forget_declarations_raises_typeerror() -> None:
    """`forget_declarations()` без `names` и без `kind` -> `TypeError`.

    Снимок/восстановление реестра вокруг вызова — тестовая гигиена: в ТЕКУЩЕМ
    (дефектном) поведении вызов реально стирает весь процессный реестр, и без
    отката эта проверка испортила бы каталог метрик соседним тестам сессии
    (в частности — страж `test_declarations_leak_session_catalogue_guard.py`).
    Это подстраховка теста, а не часть проверяемого свойства.
    """
    with decls._LOCK:
        declared_backup = dict(decls._DECLARED)
        consumed_backup = decls._RULES_CONSUMED
    try:
        with pytest.raises(TypeError):
            decls.forget_declarations()
    finally:
        with decls._LOCK:
            decls._DECLARED.clear()
            decls._DECLARED.update(declared_backup)
            decls._RULES_CONSUMED = consumed_backup


def test_bare_forget_declarations_typeerror_names_the_replacement_fixture() -> None:
    """Текст ошибки называет `declarations_snapshot` — подсказку, чем пользоваться вместо."""
    with decls._LOCK:
        declared_backup = dict(decls._DECLARED)
        consumed_backup = decls._RULES_CONSUMED
    try:
        with pytest.raises(TypeError) as excinfo:
            decls.forget_declarations()
        message = str(excinfo.value)
        assert _REPLACEMENT_FIXTURE_NAME in message, (
            f"TypeError не называет адрес фикстуры-замены {_REPLACEMENT_FIXTURE_NAME!r}: {message!r}"
        )
    finally:
        with decls._LOCK:
            decls._DECLARED.clear()
            decls._DECLARED.update(declared_backup)
            decls._RULES_CONSUMED = consumed_backup
