# -*- coding: utf-8 -*-
"""pid-реестр привязан к приложению, а не к продукту (D4).

До D4 имя дефолтного файла было прибито к одному продукту
(``inspector_system_pids.jsonl``) — и это не косметика: два приложения на
фреймворке делили ОДИН файл в общей temp-директории, поэтому старт второго
реапал живые процессы первого.

Что доказывается:
- имя файла зависит от ``MPF_APP_NAME`` → два приложения не пересекаются;
- имя нейтрально по умолчанию (нет следа продукта);
- env-ручка (обе формы пары) перекрывает дефолт;
- легаси-реестр прежнего имени НЕ осиротел: он реапается и удаляется;
- легаси-реестр НЕ трогается, когда он же является текущим (приложение с тем
  самым именем) — иначе уборка снесла бы рабочий файл;
- (D2) имя по умолчанию включает отпечаток корня checkout: два checkout одного
  приложения не делят реестр и не реапают друг друга; прежнее неразделённое имя D4
  не реапается и не удаляется.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import psutil
import pytest

import multiprocess_framework
from multiprocess_framework.modules.process_manager_module.launcher import pid_registry


@pytest.fixture(autouse=True)
def _isolated_temp(monkeypatch, tmp_path):
    """Чистый env + СВОЙ temp на каждый тест.

    ``tempfile.gettempdir()`` кэширует результат, поэтому подмена ``TMPDIR``/``TEMP``
    на него не действует — реестры уходили бы в общий системный temp и копили хвосты
    между прогонами (первая редакция этого файла так и покраснела: два ``register_self``
    вместо одного). Патчим саму функцию — это единственный вход pid_registry в temp.
    """
    for key in ("MPF_APP_NAME", "MULTIPROCESS_PID_FILE", "INSPECTOR_PID_FILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    yield


class TestDefaultNameIsAppScoped:
    def test_neutral_by_default(self):
        """Без MPF_APP_NAME имя файла не содержит имени продукта."""
        name = pid_registry.default_pid_file_name()
        assert "inspector" not in name.lower()
        assert name.endswith("_system_pids.jsonl")

    def test_two_apps_get_two_files(self, monkeypatch):
        """Разные приложения → разные файлы (иначе второе реапает процессы первого)."""
        monkeypatch.setenv("MPF_APP_NAME", "AppOne")
        first = pid_registry.pid_file_path()
        monkeypatch.setenv("MPF_APP_NAME", "AppTwo")
        second = pid_registry.pid_file_path()
        assert first != second
        assert first.parent == second.parent  # оба в temp — расходятся именно именем

    def test_app_name_appears_in_file_name(self, monkeypatch):
        monkeypatch.setenv("MPF_APP_NAME", "Inspector Bottles")
        name = pid_registry.pid_file_path().name
        assert re.fullmatch(r"Inspector_Bottles_[0-9a-f]{8}_system_pids\.jsonl", name), name

    @pytest.mark.parametrize("env_key", ["MULTIPROCESS_PID_FILE", "INSPECTOR_PID_FILE"])
    def test_env_handle_overrides_default(self, monkeypatch, tmp_path, env_key):
        """Обе ручки пары перекрывают дефолт (легаси-алиас не потерян)."""
        explicit = tmp_path / "explicit.jsonl"
        monkeypatch.setenv("MPF_APP_NAME", "AppOne")
        monkeypatch.setenv(env_key, str(explicit))
        assert pid_registry.pid_file_path() == explicit

    def test_canonical_handle_wins_over_legacy(self, monkeypatch, tmp_path):
        canonical, legacy = tmp_path / "canon.jsonl", tmp_path / "legacy.jsonl"
        monkeypatch.setenv("MULTIPROCESS_PID_FILE", str(canonical))
        monkeypatch.setenv("INSPECTOR_PID_FILE", str(legacy))
        assert pid_registry.pid_file_path() == canonical


class TestLegacyRegistryIsNotOrphaned:
    """Старый файл продуктового имени обязан быть подобран, а не забыт."""

    @pytest.fixture
    def legacy_file(self, tmp_path):
        # temp уже изолирован autouse-фикстурой — реальный системный temp не трогаем.
        return Path(tempfile.gettempdir()) / "inspector_system_pids.jsonl"

    def test_legacy_file_is_seen(self, monkeypatch, legacy_file):
        monkeypatch.setenv("MPF_APP_NAME", "AppOne")
        legacy_file.write_text('{"pid": 1, "ct": null}\n', encoding="utf-8")
        assert pid_registry.legacy_pid_file_path() == legacy_file

    def test_absent_legacy_file_is_none(self, monkeypatch, legacy_file):
        monkeypatch.setenv("MPF_APP_NAME", "AppOne")
        if legacy_file.exists():
            legacy_file.unlink()
        assert pid_registry.legacy_pid_file_path() is None

    def test_legacy_not_reported_when_it_is_the_current_file(self, monkeypatch, legacy_file):
        """Явная ручка указывает на легаси-файл: он — свой рабочий, а не чужой хвост.

        Без этой развилки уборка удаляла бы реестр прямо под работающей системой.
        (С D2 дефолтное имя приложения 'inspector' с ним уже не совпадает — см. тест ниже.)
        """
        monkeypatch.setenv("MULTIPROCESS_PID_FILE", str(legacy_file))
        legacy_file.write_text('{"pid": 1, "ct": null}\n', encoding="utf-8")
        assert pid_registry.pid_file_path() == legacy_file
        assert pid_registry.legacy_pid_file_path() is None

    def test_inspector_app_unscoped_file_is_not_legacy(self, monkeypatch, legacy_file):
        """Приложение 'inspector': ``inspector_system_pids.jsonl`` — неразделённый реестр D4.

        Он не легаси «до D4» (его не реапают и не удаляют), и текущий реестр теперь другой.
        """
        monkeypatch.setenv("MPF_APP_NAME", "inspector")
        legacy_file.write_text('{"pid": 1, "ct": null}\n', encoding="utf-8")
        assert pid_registry.pid_file_path() != legacy_file
        assert pid_registry.legacy_pid_file_path() is None

    def test_case_insensitive_fs_same_file_is_not_legacy(self, monkeypatch, tmp_path, legacy_file):
        """``MPF_APP_NAME=Inspector`` на регистронезависимой ФС — тот же файл, другая строка."""
        probe = tmp_path / "CaseProbe"
        probe.write_text("", encoding="utf-8")
        if not (tmp_path / "caseprobe").exists():
            pytest.skip("регистрозависимая ФС: имена Inspector_… и inspector_… — разные файлы")
        monkeypatch.setenv("MPF_APP_NAME", "Inspector")
        legacy_file.write_text('{"pid": 1, "ct": null}\n', encoding="utf-8")
        assert pid_registry.legacy_pid_file_path() is None

    def test_legacy_of_other_app_is_still_reaped(self, monkeypatch, legacy_file):
        """Граница D2 (зелёный пин ДО и ПОСЛЕ): другое приложение по-прежнему реапает легаси."""
        monkeypatch.setenv("MPF_APP_NAME", "AppOne")
        victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            ct = psutil.Process(victim.pid).create_time()
            legacy_file.write_text(json.dumps({"pid": victim.pid, "ct": ct}) + "\n", encoding="utf-8")
            pid_registry.reap_and_reset()
            victim.wait(timeout=10)
            assert not legacy_file.exists()
        finally:
            if victim.poll() is None:
                victim.kill()
                victim.wait(timeout=5)

    def test_reap_removes_legacy_file(self, monkeypatch, tmp_path, legacy_file):
        """reap_and_reset подбирает легаси-реестр и удаляет его; текущий остаётся пустым."""
        current = tmp_path / "current.jsonl"
        current.write_text('{"pid": 999999, "ct": null}\n', encoding="utf-8")
        monkeypatch.setenv("MULTIPROCESS_PID_FILE", str(current))
        legacy_file.write_text('{"pid": 999998, "ct": null}\n', encoding="utf-8")

        logs: list[str] = []
        pid_registry.reap_and_reset(log=logs.append)

        assert not legacy_file.exists(), "легаси-реестр остался — его хвосты не убьёт никто"
        assert current.exists() and current.read_text(encoding="utf-8") == ""
        assert any("легаси-реестр" in line for line in logs), f"подбор легаси не назван в журнале: {logs!r}"

    def test_reap_without_legacy_file_is_silent(self, monkeypatch, tmp_path, legacy_file):
        """Нет легаси — нет записи о нём (иначе шум на каждом старте)."""
        if legacy_file.exists():
            legacy_file.unlink()
        current = tmp_path / "current.jsonl"
        current.write_text("", encoding="utf-8")
        monkeypatch.setenv("MULTIPROCESS_PID_FILE", str(current))

        logs: list[str] = []
        pid_registry.reap_and_reset(log=logs.append)
        assert not any("легаси" in line for line in logs), logs


class TestRegisterSelfFollowsAppName:
    def test_two_apps_write_to_their_own_files(self, monkeypatch, tmp_path):
        """Пара, а не переименование: каждое приложение пишет в СВОЙ реестр."""
        monkeypatch.setenv("MPF_APP_NAME", "AppOne")
        one = pid_registry.pid_file_path()
        pid_registry.register_self(one)

        monkeypatch.setenv("MPF_APP_NAME", "AppTwo")
        two = pid_registry.pid_file_path()
        pid_registry.register_self(two)

        assert one != two
        for path in (one, two):
            entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            assert len(entries) == 1, f"{path.name}: чужие записи протекли в реестр приложения"


class TestCheckoutScope:
    """Область реестра — приложение И checkout (D2)."""

    @pytest.fixture
    def root_of(self, monkeypatch):
        """Подмена шва ``_checkout_root``: имитирует checkout в другом каталоге."""

        def _set(path: str) -> None:
            monkeypatch.setattr(pid_registry, "_checkout_root", lambda: Path(path))

        return _set

    @staticmethod
    def _live_victim_registered(path: Path) -> subprocess.Popen:
        victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        ct = psutil.Process(victim.pid).create_time()
        path.write_text(json.dumps({"pid": victim.pid, "ct": ct}) + "\n", encoding="utf-8")
        return victim

    def test_two_checkouts_two_files(self, root_of):
        root_of("/work/checkout_a")
        first = pid_registry.default_pid_file_name("AppOne")
        root_of("/work/checkout_b")
        second = pid_registry.default_pid_file_name("AppOne")
        assert first != second
        for name in (first, second):
            assert re.fullmatch(r"AppOne_[0-9a-f]{8}_system_pids\.jsonl", name), name

    def test_same_checkout_same_file(self, root_of):
        root_of("/work/checkout_a")
        assert pid_registry.default_pid_file_name("AppOne") == pid_registry.default_pid_file_name("AppOne")
        assert pid_registry.pid_file_path() == pid_registry.pid_file_path()

    def test_real_root_is_the_dir_containing_the_package(self):
        """Шов без подмены: корень — каталог над пакетом (литерал из ``__file__``, не из кода под тестом)."""
        expected = Path(multiprocess_framework.__file__).resolve().parent.parent
        assert pid_registry._checkout_root() == expected

    def test_unscoped_d4_file_is_never_reaped(self, monkeypatch, tmp_path):
        """Файл прежнего имени ``<app>_system_pids.jsonl`` — не реапается и не удаляется."""
        monkeypatch.setenv("MPF_APP_NAME", "AppOne")
        d4_file = tmp_path / "AppOne_system_pids.jsonl"
        victim = self._live_victim_registered(d4_file)
        try:
            before = d4_file.read_bytes()
            assert pid_registry.pid_file_path() != d4_file
            pid_registry.reap_and_reset()
            assert victim.poll() is None, "реестр прежнего имени реапнут — убит процесс чужого запуска"
            assert d4_file.read_bytes() == before, "реестр прежнего имени изменён/удалён"
        finally:
            victim.kill()
            victim.wait(timeout=5)

    def test_neighbour_checkout_survives_reap(self, monkeypatch, root_of):
        monkeypatch.setenv("MPF_APP_NAME", "AppOne")
        root_of("/work/checkout_a")
        reg_a = pid_registry.pid_file_path()
        victim = self._live_victim_registered(reg_a)
        try:
            before = reg_a.read_bytes()
            root_of("/work/checkout_b")
            assert pid_registry.pid_file_path() != reg_a
            assert pid_registry.reap_and_reset() == 0
            assert victim.poll() is None, "реап из checkout B убил процесс checkout A"
            assert reg_a.read_bytes() == before
        finally:
            victim.kill()
            victim.wait(timeout=5)

    def test_checkout_root_failure_degrades_not_raises(self, monkeypatch):
        """Корень не определился -> общее имя, а не исключение (``clear()`` считает путь вне try)."""
        monkeypatch.setattr(multiprocess_framework, "__path__", None)
        assert pid_registry._checkout_root() == Path("unknown-checkout")
        name = pid_registry.default_pid_file_name("AppOne")
        assert re.fullmatch(r"AppOne_[0-9a-f]{8}_system_pids\.jsonl", name), name
        pid_registry.clear()  # не падает
