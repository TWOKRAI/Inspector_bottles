"""Паспорт машины: что за железо, ОС и коммит дали числа отчёта. Никогда не бросает."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import psutil

KEYS = (
    "host",
    "cpu_model",
    "cores_physical",
    "cores_logical",
    "freq_mhz",
    "ram_gb",
    "gpu",
    "os",
    "python",
    "cv2",
    "commit",
    "commit_dirty",
)


def _safe(fn, *args):
    """Любой сбой пробы -> None: паспорт неполный, но бенч идёт дальше."""
    try:
        return fn(*args)
    except Exception:  # noqa: BLE001
        return None


def _run(cmd: list[str]) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=True)
    return out.stdout


def _cpu_model() -> str | None:
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            name = winreg.QueryValueEx(key, "ProcessorNameString")[0]
        return str(name).strip() or None
    if sys.platform.startswith("linux"):
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip() or None
    return platform.processor() or None


def _freq_mhz() -> float | None:
    freq = psutil.cpu_freq()
    if freq is None:
        return None
    return round(freq.current or freq.max, 1) or None


def _gpu() -> str | None:
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return None
    out = subprocess.run(
        [exe, "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, timeout=5, check=True
    ).stdout
    names = [line.strip() for line in out.splitlines() if line.strip()]
    return "; ".join(names) or None


def _cv2_version() -> str | None:
    import cv2

    return cv2.__version__


def _commit(repo: Path) -> str | None:
    # Каталог внутри чужого репозитория (например %TEMP% в домашнем git) не наш HEAD:
    # `repo` обязан быть корнем рабочего дерева, иначе commit неизвестен.
    top = _run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"]).strip()
    if not top or not os.path.samefile(top, repo):
        return None
    return _run(["git", "-C", str(repo), "rev-parse", "HEAD"]).strip() or None


def _commit_dirty(repo: Path) -> bool:
    return bool(_run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"]).strip())


def collect_passport(repo: Path) -> dict:
    """Ровно ключи `KEYS`; неизвестное -> None."""
    commit = _safe(_commit, repo)
    return {
        "host": _safe(platform.node) or None,
        "cpu_model": _safe(_cpu_model),
        "cores_physical": _safe(psutil.cpu_count, False),
        "cores_logical": os.cpu_count(),
        "freq_mhz": _safe(_freq_mhz),
        "ram_gb": _safe(lambda: round(psutil.virtual_memory().total / 2**30, 1)),
        "gpu": _safe(_gpu),
        "os": _safe(platform.platform),
        "python": _safe(platform.python_version),
        "cv2": _safe(_cv2_version),
        "commit": commit,
        "commit_dirty": _safe(_commit_dirty, repo) if commit else None,
    }
