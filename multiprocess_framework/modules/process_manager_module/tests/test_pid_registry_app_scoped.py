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
  самым именем) — иначе уборка снесла бы рабочий файл.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

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
        assert pid_registry.pid_file_path().name == "Inspector_Bottles_system_pids.jsonl"

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
        """Приложение с именем 'inspector': файл — свой рабочий, а не чужой хвост.

        Без этой развилки уборка удаляла бы реестр прямо под работающей системой.
        """
        monkeypatch.setenv("MPF_APP_NAME", "inspector")
        legacy_file.write_text('{"pid": 1, "ct": null}\n', encoding="utf-8")
        assert pid_registry.pid_file_path() == legacy_file
        assert pid_registry.legacy_pid_file_path() is None

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
