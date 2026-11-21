# -*- coding: utf-8 -*-
"""Корневая автофикстура ``_restore_app_env_keys`` откатывает env приложения между тестами (C-99).

Порядок определений — часть теста: ``test_01``/``test_03`` — «писатели» (пишут ``os.environ``
напрямую, как ``apply_env_aliases``/``SystemLauncher``), ``test_02``/``test_04`` — «жертвы»
(видят env после своего писателя). Реальный писатель C-99 стоит ПЕРВЫМ, писатель всех ключей — после
его жертвы: при выключенной фикстуре красными становятся ровно жертвы, а не писатель C-99, заражённый
утечкой предыдущего (C99-3). Писатель кладёт своё имя в ``_WRITERS_RAN``, жертва первой строкой это
проверяет: ``-k``/``--deselect``/``--lf`` без писателя дают красный, а не зелёный ноль (C99-4).
"""

from __future__ import annotations

import os

import pytest

from multiprocess_framework.modules.app_module import ENV_ALIAS_PAIRS, apply_env_aliases

#: Ожидаемый набор ключей — литералы (не выводятся из кода, который проверяется).
_KEYS = (
    "MULTIPROCESS_PID_FILE",
    "INSPECTOR_PID_FILE",
    "MULTIPROCESS_LOG_DIR",
    "INSPECTOR_LOG_DIR",
    "MULTIPROCESS_MANIFEST",
    "INSPECTOR_MANIFEST",
    "MULTIPROCESS_LOG_LEVEL",
    "INSPECTOR_LOG_LEVEL",
    "MULTIPROCESS_FRAME_TRACE",
    "INSPECTOR_FRAME_TRACE",
    "MULTIPROCESS_HEALTH_LOG_ONLY",
    "INSPECTOR_HEALTH_LOG_ONLY",
    "MULTIPROCESS_HEALTH_BREAKER_THRESHOLD",
    "INSPECTOR_HEALTH_BREAKER_THRESHOLD",
    "MULTIPROCESS_HEALTH_BREAKER_COOLDOWN",
    "INSPECTOR_HEALTH_BREAKER_COOLDOWN",
    "INSPECTOR_PRESENTATION",
    "MPF_APP_NAME",
)

#: Имена писателей, отработавших в этом процессе; жертва без своего писателя краснеет (C99-4).
_WRITERS_RAN: set[str] = set()


@pytest.fixture(scope="module", autouse=True)
def _clean_env_with_one_preset():
    """Старт модуля: все 18 ключей сняты, ``INSPECTOR_LOG_LEVEL=WARNING`` задан заранее.

    Выше по области, чем функциональная автофикстура: её снимок берётся уже после этого —
    значит, «прежнее значение» ключа в тестах ниже — ровно ``WARNING``, а остальные ключи отсутствуют
    (независимо от env, с которым запущен прогон). Конец модуля возвращает env как был.
    """
    saved = {key: os.environ.get(key) for key in _KEYS}
    for key in _KEYS:
        os.environ.pop(key, None)
    os.environ["INSPECTOR_LOG_LEVEL"] = "WARNING"
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_00_key_list_matches_env_alias_pairs() -> None:
    """Список ``_KEYS`` теста = 8 пар ``ENV_ALIAS_PAIRS`` + ``INSPECTOR_PRESENTATION`` + ``MPF_APP_NAME``.

    Ловит дрейф ``ENV_ALIAS_PAIRS``. Кортеж ``_APP_ENV_KEYS`` корневого ``conftest.py`` НЕ сверяет:
    совпадение с ним держит жертва ``test_04`` через запись ``test_03`` (C99-7).
    """
    from_pairs = {name for pair in ENV_ALIAS_PAIRS for name in pair} | {"INSPECTOR_PRESENTATION", "MPF_APP_NAME"}

    assert len(ENV_ALIAS_PAIRS) == 8
    assert len(_KEYS) == 18
    assert set(_KEYS) == from_pairs


def test_01_writer_is_real_apply_env_aliases() -> None:
    """Писатель C-99: задан только каноничный ключ, ``apply_env_aliases()`` дописывает легаси-ключ в ``os.environ``."""
    os.environ["MULTIPROCESS_MANIFEST"] = "/tmp/custom_app.yaml"

    filled = apply_env_aliases()
    _WRITERS_RAN.add("test_01_writer_is_real_apply_env_aliases")

    # Вторым дописан «зеркальный» MULTIPROCESS_LOG_LEVEL — от предзаданного INSPECTOR_LOG_LEVEL.
    assert filled == ["INSPECTOR_MANIFEST", "MULTIPROCESS_LOG_LEVEL"]
    assert os.environ["INSPECTOR_MANIFEST"] == "/tmp/custom_app.yaml"


def test_02_victim_sees_no_manifest_after_real_writer() -> None:
    """Жертва C-99: ни легаси-, ни каноничного ключа манифеста — ``resolve_manifest_path`` вернёт дефолт."""
    assert "test_01_writer_is_real_apply_env_aliases" in _WRITERS_RAN, "писатель не отработал — гоняйте файл целиком"

    # Значения — в локальные имена: assert по имени печатает значение ключа; ``os.environ.get(...)`` прямо в
    # assert pytest разворачивает в ``environ({...})`` и выносит весь env (с секретами) в лог.
    legacy, canonical, mirror = (
        os.environ.get(key) for key in ("INSPECTOR_MANIFEST", "MULTIPROCESS_MANIFEST", "MULTIPROCESS_LOG_LEVEL")
    )
    assert legacy is None
    assert canonical is None
    assert mirror is None
    assert os.environ["INSPECTOR_LOG_LEVEL"] == "WARNING"


def test_03_writer_sets_every_key_directly() -> None:
    """Писатель: напрямую в ``os.environ`` все 18 ключей и перезапись предзаданного ``INSPECTOR_LOG_LEVEL``."""
    for key in _KEYS:
        os.environ[key] = "leaked"
    os.environ["INSPECTOR_LOG_LEVEL"] = "DEBUG"
    _WRITERS_RAN.add("test_03_writer_sets_every_key_directly")

    assert os.environ["INSPECTOR_PID_FILE"] == "leaked"


def test_04_victim_sees_prior_state_after_direct_writer() -> None:
    """Жертва: отсутствовавшие ключи снова отсутствуют, предзаданный вернулся к ``WARNING``, а не ``DEBUG``."""
    assert "test_03_writer_sets_every_key_directly" in _WRITERS_RAN, "писатель не отработал — гоняйте файл целиком"

    present = {key: os.environ[key] for key in _KEYS if key in os.environ}

    assert present == {"INSPECTOR_LOG_LEVEL": "WARNING"}
