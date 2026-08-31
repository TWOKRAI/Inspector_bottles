# -*- coding: utf-8 -*-
"""Фундамент манифеста — СПИСОК фрагментов: обе формы ключа ``base``.

Зачем список (решение 2026-08-23, с замером): чтобы подключить инфраструктурный
side-effect процесс — сток истории телеметрии, рекордер, профайлер, — не трогая
общий ``base.yaml``. Вписанный в общий фундамент процесс платят ВСЕ сборки:
golden-снимки рецептов выросли на 375 строк каждый, минимальный ``hello_world``
удвоил состав процессов. Список даёт адресное подключение одной строкой.

Строковая форма обязана продолжать работать дословно — её читают все
существующие манифесты, и молчаливая поломка совместимости здесь означала бы
систему без фундамента.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from multiprocess_prototype.backend.config.manifest import load_manifest

ФРАГМЕНТ_A = {"name": "a", "processes": [{"process_name": "alpha"}], "wires": []}
ФРАГМЕНТ_B = {"name": "b", "processes": [{"process_name": "beta"}], "wires": []}


def _манифест(tmp_path: Path, base_value: object) -> Path:
    """Минимальный манифест с заданным значением ключа ``base``."""
    (tmp_path / "a.yaml").write_text(yaml.safe_dump(ФРАГМЕНТ_A), encoding="utf-8")
    (tmp_path / "b.yaml").write_text(yaml.safe_dump(ФРАГМЕНТ_B), encoding="utf-8")
    (tmp_path / "system.yaml").write_text("{}", encoding="utf-8")
    (tmp_path / "pipe.yaml").write_text(yaml.safe_dump({"name": "p", "processes": []}), encoding="utf-8")
    (tmp_path / "recipes").mkdir(exist_ok=True)

    raw: dict = {
        "name": "test",
        "system": "system.yaml",
        "pipeline": "pipe.yaml",
        "recipes": "recipes",
    }
    if base_value is not None:
        raw["base"] = base_value
    путь = tmp_path / "app.yaml"
    путь.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return путь


class TestBothFormsAreAccepted:
    def test_string_form_still_works(self, tmp_path):
        """Историческая форма — одна строка. Ломать её нельзя."""
        app = load_manifest(_манифест(tmp_path, "a.yaml"))

        assert len(app.base) == 1
        assert app.base[0].name == "a.yaml"

    def test_list_form_keeps_the_written_order(self, tmp_path):
        """Порядок склейки — порядок списка, а не алфавит и не случайность."""
        app = load_manifest(_манифест(tmp_path, ["b.yaml", "a.yaml"]))

        assert [p.name for p in app.base] == ["b.yaml", "a.yaml"]

    def test_absent_key_means_no_base_at_all(self, tmp_path):
        app = load_manifest(_манифест(tmp_path, None))

        assert app.base == ()

    def test_empty_list_means_no_base_at_all(self, tmp_path):
        app = load_manifest(_манифест(tmp_path, []))

        assert app.base == ()


class TestBrokenValueFailsLoudly:
    """Молча проглоченный мусор дал бы систему БЕЗ фундамента.

    Заметили бы это по отсутствующему процессу на стенде, а не по конфигу —
    поэтому отказ громкий и с адресом ключа.
    """

    def test_number_instead_of_path_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="base"):
            load_manifest(_манифест(tmp_path, 42))

    def test_list_with_a_non_string_element_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="base"):
            load_manifest(_манифест(tmp_path, ["a.yaml", 7]))

    def test_list_with_an_empty_string_is_refused(self, tmp_path):
        """Пустая строка — самый тихий вид опечатки: путь резолвится в каталог."""
        with pytest.raises(ValueError, match="base"):
            load_manifest(_манифест(tmp_path, ["a.yaml", ""]))


class TestBothLoadersAgree:
    """Загрузчиков манифеста в репозитории ДВА, и это ловушка.

    Боевой запуск идёт через ``multiprocess_framework.modules.app_module.manifest``
    (Ф5.11), а тесты прототипа исторически импортируют
    ``multiprocess_prototype.backend.config.manifest``. Поймано 2026-08-23:
    композиция ``base`` была реализована в прототипной копии, все её тесты
    зеленели — и бэкенд падал на старте с ``TypeError: argument should be a str
    …, not 'list'``, потому что боевой загрузчик правки не видел.

    Этот тест не устраняет дублирование (это отдельная работа), он делает
    расхождение ГРОМКИМ: любая правка одной копии без другой красит его.
    """

    @staticmethod
    def _both(tmp_path: Path, base_value: object):
        from multiprocess_framework.modules.app_module.manifest import (
            load_manifest as load_framework,
        )

        путь = _манифест(tmp_path, base_value)
        return load_manifest(путь), load_framework(путь)

    def test_string_form_resolves_identically(self, tmp_path):
        proto, framework = self._both(tmp_path, "a.yaml")

        assert tuple(proto.base) == tuple(framework.base)
        assert [p.name for p in framework.base] == ["a.yaml"]

    def test_list_form_resolves_identically(self, tmp_path):
        proto, framework = self._both(tmp_path, ["b.yaml", "a.yaml"])

        assert tuple(proto.base) == tuple(framework.base)
        assert [p.name for p in framework.base] == ["b.yaml", "a.yaml"]

    def test_absent_key_agrees(self, tmp_path):
        proto, framework = self._both(tmp_path, None)

        assert tuple(proto.base) == tuple(framework.base) == ()

    def test_broken_value_is_refused_by_both(self, tmp_path):
        from multiprocess_framework.modules.app_module.manifest import (
            load_manifest as load_framework,
        )

        путь = _манифест(tmp_path, 42)
        with pytest.raises(ValueError, match="base"):
            load_manifest(путь)
        with pytest.raises(ValueError, match="base"):
            load_framework(путь)
