"""Токен рукопожатия сокетного канала (Task 0.12, ADR-RTR-017).

Purpose: файл токена и проверка ``hello`` для :class:`SocketChannel` /
:class:`SocketClient`. Сервер пишет токен в файл с правами 0600, клиент того же
пользователя читает его и шлёт первой строкой соединения.

Public API:
    resolve_token_path(port, env=None) -> Path
    write_token(path) -> str
    read_token(path) -> str | None
    token_authenticator(token) -> Callable[[dict], bool]
    file_token_provider(port, env=None) -> Callable[[], str | None]

Граница доверия — чтение домашнего каталога пользователя. Процессы того же
пользователя — вне модели угроз. Токен не пишется в журнал.

Stability: lite
"""

from __future__ import annotations

import hmac
import os
import secrets
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

__all__ = [
    "resolve_token_path",
    "write_token",
    "read_token",
    "token_authenticator",
    "file_token_provider",
]

_ENV_TOKEN_FILE = "BACKEND_CTL_TOKEN_FILE"


def _default_token_path(port: int) -> Path:
    """Путь по умолчанию. Не публичный: публичный путь без живого вызова — контракт."""
    return Path.home() / ".multiprocess_framework" / f"ctl_{port}.token"


def resolve_token_path(port: int, env: Mapping[str, str] | None = None) -> Path:
    """Путь файла токена для порта ``port``.

    Pre:  ``env`` — отображение переменных окружения; ``None`` → ``os.environ``.
    Post: непустое значение ``BACKEND_CTL_TOKEN_FILE`` главнее (с ``expanduser()``);
          пустое игнорируется; иначе ``~/.multiprocess_framework/ctl_<port>.token``.
          ``~`` берётся из ``HOME``/``USERPROFILE`` процесса, а не из ``env``.
          Путь не зависит от каталога журнала.
    """
    source = os.environ if env is None else env
    explicit = source.get(_ENV_TOKEN_FILE, "")
    if explicit:
        return Path(explicit).expanduser()
    return _default_token_path(port)


def write_token(path: Path) -> str:
    """Записать новый токен в ``path`` и вернуть его.

    Post: каталог создан с правами 0700 (если его не было); файл с правами 0600
          с момента создания (временный файл рядом, затем атомарная замена);
          токен — 64 hex-символа. При сбое временный файл удалён, исключение
          пробрасывается.
    """
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    token = secrets.token_hex(32)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(token + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return token


def read_token(path: Path) -> str | None:
    """Прочитать токен из ``path``.

    Post: содержимое без пробельных символов по краям; пустой файл, нет файла или
          невалидный UTF-8 (токен с мусором не валиден) → ``None``. Прочие ``OSError``
          (каталог, нет прав) пробрасываются.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return None
    value = text.strip()
    return value or None


def token_authenticator(token: str | Callable[[], str | None]) -> Callable[[dict], bool]:
    """Проверка первой строки соединения по токену.

    Pre:  ``token`` — непустая строка либо callable без аргументов. Пустая строка →
          ``ValueError``.
    Post: результат ``authenticator(msg) -> bool``. Callable читается на КАЖДЫЙ
          вызов; он вернул ``None`` или пустое → ``False`` (закрыто по умолчанию).
          ``msg["token"]`` не ``str`` или пустой → ``False`` без исключения.
          Сравнение — за константное время, по байтам UTF-8.
    """
    if isinstance(token, str):
        if not token:
            raise ValueError("token_authenticator: пустой токен")
        fixed = token

        def expected_of() -> str | None:
            return fixed

    elif callable(token):
        expected_of = token
    else:
        raise TypeError(f"token_authenticator: ожидалась строка или callable, получено {type(token).__name__}")

    def authenticate(msg: dict) -> bool:
        got = msg.get("token")
        if not isinstance(got, str) or not got:
            return False
        expected = expected_of()
        if not isinstance(expected, str) or not expected:
            return False
        try:
            return hmac.compare_digest(got.encode("utf-8"), expected.encode("utf-8"))
        except UnicodeEncodeError:  # одиночный суррогат из JSON
            return False

    return authenticate


def file_token_provider(port: int, env: Mapping[str, str] | None = None) -> Callable[[], str | None]:
    """Провайдер токена клиента из файла порта ``port``.

    Post: провайдер при КАЖДОМ вызове заново находит путь (:func:`resolve_token_path`)
          и читает файл (:func:`read_token`), без кэша: рестарт сервера меняет токен.
    """

    def provide() -> str | None:
        return read_token(resolve_token_path(port, env))

    return provide
