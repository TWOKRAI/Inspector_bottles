# -*- coding: utf-8 -*-
"""Слой ``Services`` не требует бренда: env-ручки читаются парой, канон первым.

Задача 5.2 плана ``observability-roadmap``, развилка Р-5а. Основание — Н-16
приёмки F1: ``Services/auth`` и ``Services/sql`` читали **только** ``INSPECTOR_*``,
то есть переиспользуемый слой требовал бренд конкретного приложения. Линза S4
воспроизвела это, собрав чужое приложение (AcmeWidgets).

Здесь два разных инструмента, и путать их нельзя:

* **аудит** (:func:`legacy_only_readers`) — обход дерева, отвечает на «есть ли ещё
  читатели легаси-только». Он находит класс, а не конкретный дефект;
* **пара-тесты** — на каждой ручке проверяют ТРИ утверждения: канон работает,
  легаси работает, при обоих заданных выигрывает канон. Соседняя ручка чистится
  явно: тест, задавший одну из пары и оставивший вторую из окружения машины,
  меряет приоритет, а не ручку.

Границы аудита названы, а не умолчаны:

1. Судится **только** ``Services/`` — прототип (``multiprocess_prototype``) вправе
   быть брендированным, это и есть Inspector; фреймворк судится своими стражами.
2. Каталоги ``tests/`` исключены: тест **обязан** уметь задать легаси-имя в одиночку —
   именно так проверяется, что легаси-дорога жива.
3. Аудит смотрит на чтение env по имени. Ручка, собранная из переменной
   (``os.environ.get(name)``), ему не видна — таких в ``Services`` нет, и это
   проверяется отдельным ассертом на число найденных чтений.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple
from unittest.mock import patch

import pytest

from Services.sql.core.engine_factory import fork_safe_env_flag

SERVICES_ROOT = Path(__file__).resolve().parents[1]

#: Известные пары ручек слоя: канон → легаси. Реестр здесь, а не в коде сервисов:
#: аудит обязан знать, что считать «парой», иначе он судит по префиксу и врёт.
KNOWN_PAIRS: Dict[str, str] = {
    "INSPECTOR_AUTH_USERS_PATH": "MULTIPROCESS_AUTH_USERS_PATH",
    "INSPECTOR_DEV_PASSWORD": "MULTIPROCESS_DEV_PASSWORD",
    "INSPECTOR_MULTIPROCESS": "MULTIPROCESS_SQL_FORK_SAFE",
}

#: Чтение env по литеральному имени. Судится ИМЕННО чтение, а не упоминание:
#: каноничное имя, названное в докстринге и не прочитанное ни одной строкой, —
#: ровно тот дефект, который аудит обязан ловить (обещание без исполнения).
_ENV_READ = re.compile(r"""os\.environ(?:\.get)?[(\[]\s*["'](INSPECTOR_[A-Z0-9_]+)["']""")
_ENV_READ_CANON = re.compile(r"""os\.environ(?:\.get)?[(\[]\s*["'](MULTIPROCESS_[A-Z0-9_]+)["']""")


def _python_files(root: Path) -> List[Path]:
    return [p for p in root.rglob("*.py") if "tests" not in p.parts and "__pycache__" not in p.parts]


def legacy_only_readers(root: Path = SERVICES_ROOT) -> List[Tuple[str, int, str]]:
    """Чтения ``INSPECTOR_*``, рядом с которыми в файле нет каноничного имени.

    Returns:
        Список ``(путь, строка, имя)``. Пусто = ни одного читателя «легаси-только».
    """
    found: List[Tuple[str, int, str]] = []
    for path in _python_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        canon_reads = set(_ENV_READ_CANON.findall(text))
        for match in _ENV_READ.finditer(text):
            legacy = match.group(1)
            canonical = KNOWN_PAIRS.get(legacy)
            line = text[: match.start()].count("\n") + 1
            if canonical is None:
                found.append((str(path.relative_to(root)), line, f"{legacy} (пары не объявлено)"))
            elif canonical not in canon_reads:
                found.append((str(path.relative_to(root)), line, legacy))
    return found


def env_reads(root: Path = SERVICES_ROOT) -> List[str]:
    """Все имена ``INSPECTOR_*``, читаемые из env в слое (для контроля охвата)."""
    names: List[str] = []
    for path in _python_files(root):
        names += _ENV_READ.findall(path.read_text(encoding="utf-8", errors="replace"))
    return names


def dynamic_env_reads(root: Path = SERVICES_ROOT) -> List[Tuple[str, int]]:
    """Чтения env по НЕ-литеральному имени — слепая зона аудита, обязана быть пустой."""
    blind: List[Tuple[str, int]] = []
    for path in _python_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover — синтаксис ловит другой гейт
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            is_env_get = (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "environ"
            )
            if is_env_get and not isinstance(node.args[0], ast.Constant):
                blind.append((str(path.relative_to(root)), node.lineno))
    return blind


# =============================================================================
# Аудит: 0 читателей «легаси-только» в Services
# =============================================================================


def test_no_legacy_only_readers_in_services() -> None:
    """Ни одна ручка слоя не читается ТОЛЬКО под брендом Inspector (Н-16)."""
    offenders = legacy_only_readers()
    assert not offenders, "читатели легаси-только:\n" + "\n".join(
        f"  {p}:{line}  {name}" for p, line, name in offenders
    )


def test_audit_sees_a_planted_violation(tmp_path: Path) -> None:
    """Молчащий аудит не доказывает ничего: подсаживаем нарушение и требуем красноты."""
    (tmp_path / "service.py").write_text(
        'import os\nvalue = os.environ.get("INSPECTOR_DEV_PASSWORD", "")\n', encoding="utf-8"
    )
    offenders = legacy_only_readers(tmp_path)
    assert offenders, "аудит не увидел подсаженного читателя легаси-только"
    assert offenders[0][2] == "INSPECTOR_DEV_PASSWORD"


def test_audit_accepts_a_pair(tmp_path: Path) -> None:
    """И обратное: файл с парой (канон первым) аудит НЕ считает нарушением."""
    (tmp_path / "service.py").write_text(
        'import os\nvalue = os.environ.get("MULTIPROCESS_DEV_PASSWORD") or os.environ.get("INSPECTOR_DEV_PASSWORD")\n',
        encoding="utf-8",
    )
    assert legacy_only_readers(tmp_path) == []


def test_audit_has_no_blind_spot_in_services() -> None:
    """Чтений env по вычисляемому имени в слое нет — иначе аудит судил бы часть."""
    blind = dynamic_env_reads()
    assert not blind, "env читается по не-литеральному имени, аудит этого не видит: " + str(blind)


def test_every_read_legacy_name_has_a_declared_pair() -> None:
    """Каждое прочитанное легаси-имя объявлено в реестре пар (иначе аудит его пропустит)."""
    unknown = {name for name in env_reads() if name not in KNOWN_PAIRS}
    assert not unknown, f"легаси-имена без объявленной пары: {sorted(unknown)}"


# =============================================================================
# Пара-тесты: канон, легаси, приоритет — на каждой ручке
# =============================================================================


@pytest.fixture()
def clean_env():
    """Окружение без обеих ручек каждой пары: сосед чистится ЯВНО."""
    keys = list(KNOWN_PAIRS) + list(KNOWN_PAIRS.values())
    with patch.dict(os.environ, {}, clear=False):
        for key in keys:
            os.environ.pop(key, None)
        yield


@pytest.mark.parametrize(
    ("canonical", "legacy"),
    [("MULTIPROCESS_SQL_FORK_SAFE", "INSPECTOR_MULTIPROCESS")],
)
def test_sql_fork_safe_pair(canonical: str, legacy: str, clean_env: None) -> None:
    """Флаг fork-safe: канон работает, легаси работает, канон сильнее."""
    assert fork_safe_env_flag() is False, "без обеих ручек флаг обязан быть выключен"

    os.environ[canonical] = "1"
    assert fork_safe_env_flag() is True, "каноничное имя не читается"
    del os.environ[canonical]

    os.environ[legacy] = "1"
    assert fork_safe_env_flag() is True, "легаси-имя перестало работать — это поломка совместимости"

    os.environ[canonical] = "0"
    assert fork_safe_env_flag() is False, "при обоих заданных выиграло легаси, а не канон"


def test_sql_async_and_sync_read_the_same_handle(clean_env: None) -> None:
    """Обе дороги (sync/async) судят по ОДНОЙ функции: разойтись молча им нечем."""
    from Services.sql.adapters import async_adapter
    from Services.sql.core import engine_factory

    assert async_adapter.fork_safe_env_flag is engine_factory.fork_safe_env_flag


def test_auth_users_path_pair(tmp_path: Path, clean_env: None, capsys: pytest.CaptureFixture) -> None:
    """Путь к users.yaml: канон читается, легаси читается, канон сильнее.

    Судим по **напечатанному пути**, а не по коду возврата: exit 1 означает «файл
    существует» и пришёл бы и от дефолта ``~/.inspector_bottles/auth/users.yaml``,
    если он есть на машине. Тогда зелёный доказывал бы дефолт, а не ручку.
    """
    from Services.auth.bootstrap import main

    canonical_file = tmp_path / "канон.yaml"
    legacy_file = tmp_path / "легаси.yaml"
    for path in (canonical_file, legacy_file):
        path.write_text("users: {}\nroles: {}\n", encoding="utf-8")

    def path_in_use() -> str:
        assert main() == 1, "дорога не дошла до «уже инициализировано»"
        return capsys.readouterr().out

    os.environ["MULTIPROCESS_AUTH_USERS_PATH"] = str(canonical_file)
    assert str(canonical_file) in path_in_use(), "каноничное имя не читается"
    del os.environ["MULTIPROCESS_AUTH_USERS_PATH"]

    os.environ["INSPECTOR_AUTH_USERS_PATH"] = str(legacy_file)
    assert str(legacy_file) in path_in_use(), "легаси-имя перестало работать — поломка совместимости"

    os.environ["MULTIPROCESS_AUTH_USERS_PATH"] = str(canonical_file)
    out = path_in_use()
    assert str(canonical_file) in out, "при обоих заданных выиграло легаси, а не канон"
    assert str(legacy_file) not in out


def test_auth_dev_password_pair(tmp_path: Path, clean_env: None) -> None:
    """Пароль dev-пользователя: канон читается, легаси читается, канон сильнее.

    Интерактивный ввод закрыт нарочно: если ручку не прочитали, дорога уходит в
    prompt, и тест **повис бы** вместо того чтобы покраснеть — это хуже, чем его
    отсутствие. Здесь вместо ожидания приходит исключение с причиной.
    """
    from Services.auth.bootstrap import main

    users_path = str(tmp_path / "users.yaml")
    os.environ["MULTIPROCESS_AUTH_USERS_PATH"] = users_path

    def _no_prompt(*_args, **_kwargs):
        raise AssertionError("ручка пароля не прочитана — дорога ушла в интерактивный ввод")

    with (
        patch("Services.auth.bootstrap.input", _no_prompt),
        patch("Services.auth.bootstrap.getpass.getpass", _no_prompt),
    ):
        # Канон один: слабый пароль отвергается ДО записи на диск (exit 2).
        os.environ["MULTIPROCESS_DEV_PASSWORD"] = "weak"
        assert main() == 2, "каноничное имя не читается"
        assert not Path(users_path).exists()
        del os.environ["MULTIPROCESS_DEV_PASSWORD"]

        # Легаси один: та же дорога.
        os.environ["INSPECTOR_DEV_PASSWORD"] = "weak"
        assert main() == 2, "легаси-имя перестало работать — это поломка совместимости"

        # Оба: канон — слабый (exit 2), легаси — сильный (был бы exit 0 и файл на
        # диске). Выигрывает канон → exit 2 и файла нет.
        os.environ["MULTIPROCESS_DEV_PASSWORD"] = "weak"
        os.environ["INSPECTOR_DEV_PASSWORD"] = "StrongPass@1"
        assert main() == 2, "при обоих заданных выиграло легаси, а не канон"
        assert not Path(users_path).exists(), "проиграл канон: на диск лёг пользователь по легаси-паролю"
