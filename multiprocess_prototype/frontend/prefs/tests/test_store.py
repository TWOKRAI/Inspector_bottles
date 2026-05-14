"""Тесты UiPrefsStore — простой kv-store для UI-предпочтений."""

from __future__ import annotations

from pathlib import Path

import yaml

from multiprocess_prototype.frontend.prefs.store import UiPrefsStore


class TestUiPrefsStore:
    """Тесты UiPrefsStore."""

    def test_get_default_when_missing(self, tmp_path: Path) -> None:
        """get() возвращает default если файл отсутствует."""
        prefs_file = tmp_path / "ui_prefs.yaml"
        store = UiPrefsStore(path=prefs_file)

        # Файла нет — возвращаем default
        assert store.get("any.key", "x") == "x"
        assert store.get("missing", None) is None
        assert store.get("deeply.nested.key", 42) == 42

    def test_set_persists_to_yaml(self, tmp_path: Path) -> None:
        """set() сохраняет значение на диск; новый экземпляр видит его."""
        prefs_file = tmp_path / "ui_prefs.yaml"
        store = UiPrefsStore(path=prefs_file)

        store.set("settings.view_mode", "table")

        # Новый экземпляр читает с диска
        store2 = UiPrefsStore(path=prefs_file)
        assert store2.get("settings.view_mode") == "table"

        # Файл создан и содержит нужные данные
        assert prefs_file.exists()
        raw = yaml.safe_load(prefs_file.read_text(encoding="utf-8"))
        assert raw == {"settings": {"view_mode": "table"}}

    def test_dotted_keys_isolate(self, tmp_path: Path) -> None:
        """set("a.b", ...) и set("a.c", ...) не пересекаются."""
        prefs_file = tmp_path / "ui_prefs.yaml"
        store = UiPrefsStore(path=prefs_file)

        store.set("a.b", 1)
        store.set("a.c", 2)

        assert store.get("a.b") == 1
        assert store.get("a.c") == 2

        # Оба ключа под родительским "a"
        raw = yaml.safe_load(prefs_file.read_text(encoding="utf-8"))
        assert raw == {"a": {"b": 1, "c": 2}}

    def test_all_returns_copy(self, tmp_path: Path) -> None:
        """all() возвращает независимую копию словаря."""
        prefs_file = tmp_path / "ui_prefs.yaml"
        store = UiPrefsStore(path=prefs_file)
        store.set("x", "hello")

        snapshot = store.all()
        # Мутация snapshot не меняет store
        snapshot["x"] = "changed"
        assert store.get("x") == "hello"

    def test_atomic_write_creates_tmp_then_replaces(self, tmp_path: Path) -> None:
        """Атомарная запись: .tmp файл больше не существует после set()."""
        prefs_file = tmp_path / "ui_prefs.yaml"
        store = UiPrefsStore(path=prefs_file)

        store.set("key", "value")

        # После успешного replace — .tmp не должно существовать
        tmp_file = prefs_file.with_suffix(".yaml.tmp")
        assert not tmp_file.exists()
        assert prefs_file.exists()

    def test_get_returns_none_for_missing_key(self, tmp_path: Path) -> None:
        """get() без default возвращает None для отсутствующего ключа."""
        prefs_file = tmp_path / "ui_prefs.yaml"
        store = UiPrefsStore(path=prefs_file)
        store.set("a", 1)

        assert store.get("b") is None

    def test_empty_yaml_file_handled(self, tmp_path: Path) -> None:
        """Пустой YAML-файл не вызывает ошибку, get() возвращает default."""
        prefs_file = tmp_path / "ui_prefs.yaml"
        prefs_file.write_text("", encoding="utf-8")

        store = UiPrefsStore(path=prefs_file)
        assert store.get("key", "default") == "default"
