"""Тесты для _DeprecatedExtrasDict — deprecation shim для ctx.extras.

Task D.4 / Phase D (cross-tab-architecture).
Проверяет: warning при чтении deprecated ключей, тишина при записи/contains/итерации.
"""

from __future__ import annotations

import warnings

import pytest

from multiprocess_prototype.frontend._deprecated_extras import (
    _DEPRECATED_KEYS_MAP,
    _DeprecatedExtrasDict,
)
from multiprocess_prototype.frontend.app_context import build_app_context


# ---------------------------------------------------------------------------
# 1. Deprecated ключ через __getitem__ эмитит DeprecationWarning
# ---------------------------------------------------------------------------


def test_deprecated_key_emits_warning() -> None:
    """__getitem__ на deprecated ключе выдаёт DeprecationWarning с указанием замены."""
    extras = _DeprecatedExtrasDict({"topology_holder": object()})
    with pytest.warns(DeprecationWarning, match="topology"):
        _ = extras["topology_holder"]


# ---------------------------------------------------------------------------
# 2. Не-deprecated ключ — тихо, никакого предупреждения
# ---------------------------------------------------------------------------


def test_non_deprecated_key_silent() -> None:
    """Чтение ключа, не входящего в _DEPRECATED_KEYS_MAP, не эмитит предупреждений."""
    extras = _DeprecatedExtrasDict({"random_key": "some_value"})
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # любой warning → exception
        result = extras["random_key"]
    assert result == "some_value"


# ---------------------------------------------------------------------------
# 3. get() тоже предупреждает для deprecated ключей
# ---------------------------------------------------------------------------


def test_get_method_warns_for_deprecated() -> None:
    """extras.get('topology_holder') — тоже эмитит DeprecationWarning."""
    extras = _DeprecatedExtrasDict({"topology_holder": "holder_obj"})
    with pytest.warns(DeprecationWarning, match="topology"):
        result = extras.get("topology_holder")
    assert result == "holder_obj"


# ---------------------------------------------------------------------------
# 4. __setitem__ — тихо (запись не предупреждает)
# ---------------------------------------------------------------------------


def test_setitem_silent() -> None:
    """Запись deprecated ключа не эмитит предупреждений."""
    extras = _DeprecatedExtrasDict()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        extras["topology_holder"] = "new_holder"
    # Проверяем значение с подавлением warnings (чтение — отдельная история)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert extras["topology_holder"] == "new_holder"


def test_setitem_silent_for_multiple_keys() -> None:
    """Множественная запись deprecated ключей — всё тихо."""
    extras = _DeprecatedExtrasDict()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for key in list(_DEPRECATED_KEYS_MAP.keys()):
            extras[key] = f"value_{key}"


# ---------------------------------------------------------------------------
# 5. __contains__ (in) — тихо
# ---------------------------------------------------------------------------


def test_contains_silent() -> None:
    """Оператор 'in' для deprecated ключа не эмитит предупреждений."""
    extras = _DeprecatedExtrasDict({"topology_holder": "holder"})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = "topology_holder" in extras
    assert result is True


# ---------------------------------------------------------------------------
# 6. Backward-compat: AppContext с extras продолжает работать (smoke)
# ---------------------------------------------------------------------------


def test_existing_code_still_works() -> None:
    """Smoke-тест: AppContext с _DeprecatedExtrasDict работает как раньше.

    Проверяем, что imports нет exception, extras заполняется и читается.
    Warnings подавляем — только проверяем отсутствие exception.
    """
    from unittest.mock import MagicMock

    process = MagicMock()
    process._bridge = MagicMock()

    ctx = build_app_context(process, config={"key": "val"})
    # Запись — тихая
    ctx.extras["topology_holder"] = "holder_obj"
    ctx.extras["recipe_manager"] = "recipe_obj"
    ctx.extras["custom_non_deprecated"] = "other"

    # Чтение с подавлением warnings (backward-compat: значения доступны)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert ctx.extras["topology_holder"] == "holder_obj"
        assert ctx.extras["recipe_manager"] == "recipe_obj"
        assert ctx.extras["custom_non_deprecated"] == "other"


# ---------------------------------------------------------------------------
# 7. Сообщение содержит имя поля AppServices
# ---------------------------------------------------------------------------


def test_warning_message_includes_replacement() -> None:
    """Warning-сообщение содержит 'app_services.topology' — точное поле AppServices."""
    extras = _DeprecatedExtrasDict({"topology_holder": "holder"})
    with pytest.warns(DeprecationWarning, match=r"app_services\.topology"):
        _ = extras["topology_holder"]


# ---------------------------------------------------------------------------
# 8. Параметризованный: все ключи из _DEPRECATED_KEYS_MAP эмитят warning
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("deprecated_key", list(_DEPRECATED_KEYS_MAP.keys()))
def test_all_mapped_keys_emit_warning(deprecated_key: str) -> None:
    """Каждый deprecated ключ при чтении эмитит DeprecationWarning с правильной заменой."""
    replacement = _DEPRECATED_KEYS_MAP[deprecated_key]
    extras = _DeprecatedExtrasDict({deprecated_key: "some_value"})

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _ = extras[deprecated_key]

    assert len(caught) == 1
    assert issubclass(caught[0].category, DeprecationWarning)
    msg = str(caught[0].message)
    assert f"app_services.{replacement}" in msg, f"Ожидалось 'app_services.{replacement}' в сообщении: {msg!r}"
