"""Токен рукопожатия сокетного канала.

Purpose: файл токена и проверка ``hello`` для :class:`SocketChannel` /
:class:`SocketClient`.

Public API:
    resolve_token_path(port, env=None) -> Path
    write_token(path) -> str
    read_token(path) -> str | None
    token_authenticator(token) -> Callable[[dict], bool]
    file_token_provider(port, env=None) -> Callable[[], str | None]

Stability: lite
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

__all__ = [
    "resolve_token_path",
    "write_token",
    "read_token",
    "token_authenticator",
    "file_token_provider",
]


def resolve_token_path(port: int, env: Mapping[str, str] | None = None) -> Path:
    """Путь файла токена для порта ``port``."""
    return Path("unset")


def write_token(path: Path) -> str:
    """Записать новый токен в ``path`` и вернуть его."""
    return ""


def read_token(path: Path) -> str | None:
    """Прочитать токен из ``path``."""
    return None


def token_authenticator(token: str | Callable[[], str | None]) -> Callable[[dict], bool]:
    """Проверка первой строки соединения по токену."""
    return lambda m: True


def file_token_provider(port: int, env: Mapping[str, str] | None = None) -> Callable[[], str | None]:
    """Провайдер токена клиента из файла порта ``port``."""
    return lambda: None
