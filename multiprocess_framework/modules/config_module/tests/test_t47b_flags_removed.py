# -*- coding: utf-8 -*-
"""Task 4.7b (transport-single-policy) — реестр флагов: один режим shm, без переключателей.

Слепой acceptance-тест (tester, от критериев приёмки 4.7b, без чтения реализации 4.7b).

Контракт (литералы):
  * в реестре нет ``FW_SHM_OWNER_INCARNATION`` / ``FW_SHM_HANDLE_CACHE`` / ``FW_SHM_ZERO_COPY``;
  * ``FW_SHM_LOAN_PROTOCOL`` остаётся ВЫКЛЮЧЕННЫМ, в описании есть слово ``FROZEN``, а его
    ``requires`` не называет ни удалённых, ни вообще отсутствующих в реестре флагов;
  * ``FW_SHM_[A-Z_]+`` в ``*.py`` / ``*.yaml`` вне файла реестра, каталогов тестов и документации
    встречается ТОЛЬКО как ``LOAN_PROTOCOL`` / ``PREFIX_CLEANUP``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from multiprocess_framework.modules.config_module import feature_flags as ff

REMOVED = ("FW_SHM_OWNER_INCARNATION", "FW_SHM_HANDLE_CACHE", "FW_SHM_ZERO_COPY")
ALLOWED_SUFFIXES = {"LOAN_PROTOCOL", "PREFIX_CLEANUP"}

REPO_ROOT = Path(__file__).resolve().parents[4]
REGISTRY_FILE = Path(ff.__file__).resolve()
_PATTERN = re.compile(r"FW_SHM_[A-Z_]+")
# Каталоги, которые приёмка исключает: тесты, документация, служебное/временное.
_SKIP_DIRS = {"tests", "docs", "plans", ".git", ".venv", ".claude", "graphify-out", "__pycache__", "node_modules"}


@pytest.mark.parametrize("name", REMOVED)
def test_removed_flags_absent_from_registry(name: str) -> None:
    assert name not in ff.FLAGS, f"{name} должен быть удалён из реестра (один режим shm)"
    assert name not in [f.name for f in ff._FLAG_LIST], f"{name} остался в _FLAG_LIST"


def test_loan_protocol_frozen_without_dangling_requires() -> None:
    assert "FW_SHM_LOAN_PROTOCOL" in ff.FLAGS, "LOAN_PROTOCOL остаётся в реестре (заморожен, не удалён)"
    flag = ff.FLAGS["FW_SHM_LOAN_PROTOCOL"]
    assert flag.default is False, "LOAN_PROTOCOL должен оставаться выключенным по умолчанию"
    assert "FROZEN" in flag.doc, f"в описании LOAN_PROTOCOL нет пометки FROZEN: {flag.doc!r}"
    for req in flag.requires:
        assert req not in REMOVED, f"requires ссылается на удалённый флаг {req}"
        assert req in ff.FLAGS, f"requires ссылается на флаг, которого нет в реестре: {req}"


def _tracked_sources() -> list[Path]:
    """*.py / *.yaml репозитория (отслеженные + неотслеженные, без игнорируемых) через git."""
    out = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "--", "*.py", "*.yaml"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    ).stdout.splitlines()
    files: list[Path] = []
    for rel in out:
        p = Path(rel)
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.name.startswith("test_") or p.name == "conftest.py":
            continue
        full = (REPO_ROOT / p).resolve()
        if full == REGISTRY_FILE or not full.is_file():
            continue
        files.append(full)
    return files


@pytest.mark.xfail(strict=True, reason="RED-спека 4.7b, реализации нет")
def test_no_fw_shm_refs_outside_registry() -> None:
    offenders: dict[str, set[str]] = {}
    scanned = _tracked_sources()
    assert len(scanned) > 500, f"сканер нашёл подозрительно мало файлов ({len(scanned)}) — сломан обход"
    for path in scanned:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        bad = {m for m in _PATTERN.findall(text) if m[len("FW_SHM_") :] not in ALLOWED_SUFFIXES}
        if bad:
            offenders[path.relative_to(REPO_ROOT).as_posix()] = bad
    assert not offenders, "остались упоминания удалённых FW_SHM_*:\n" + "\n".join(
        f"  {p}: {sorted(v)}" for p, v in sorted(offenders.items())
    )
