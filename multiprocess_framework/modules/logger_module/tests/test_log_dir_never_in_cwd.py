# -*- coding: utf-8 -*-
"""Задача 3.3 (`plans/observability-roadmap.md`, этап 3): логи не пишутся рядом с cwd.

`log_paths` обещает: «без явной привязки файлы не должны попадать в дерево пакета».
Обещание отменялось МАТЕРИАЛИЗОВАННЫМ ДЕФОЛТОМ — слой выше подставлял относительную
строку ``"logs"``, и защита за ним получала уже непустой путь, который честно резолвила
от ``cwd``. Цена измерена: корневой ``logs/`` дорос до 467 МиБ, полный прогон гейта
дописывал в него 428 736 байт.

Здесь сторожится СВОЙСТВО, а не строка: путь молчащего конфига обязан лежать ВНЕ дерева
репозитория. Проверка «путь равен temp» была бы слабее — она прошла бы и для
``<репозиторий>/logs``, если однажды кто-то объявит его «своим temp».
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from multiprocess_framework.modules.logger_module.core.logger_core import LoggerCore

#: Корень репозитория: этот файл — modules/logger_module/tests/<файл>.
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _resolve(log_directory: str | None, process_name: str | None = "camera_0") -> Path:
    """Позвать чистый расчёт пути на утином ``self``.

    Метод считает путь и ничего больше не трогает, а живой ``LoggerManager`` — синглтон
    с потоками и каналами: поднимать его ради одной строки значило бы мерить не то.
    """
    stub = SimpleNamespace(
        config=SimpleNamespace(log_directory=log_directory),
        process=SimpleNamespace(name=process_name) if process_name else None,
    )
    return Path(LoggerCore._resolved_file_path(stub, "system.log", "logs/system.log"))


class TestSilentConfigStaysOutOfTheRepository:
    def test_path_of_a_silent_config_is_outside_the_repo_tree(self) -> None:
        """Главное свойство задачи 3.3."""
        resolved = _resolve(log_directory=None)

        assert resolved.is_absolute(), f"относительный путь резолвится от cwd: {resolved}"
        assert _REPO_ROOT not in resolved.parents, f"молчащий конфиг увёл логи в дерево репозитория: {resolved}"

    def test_process_name_still_gets_its_own_subdirectory(self) -> None:
        """Пара к предыдущему: уводя каталог из cwd, нельзя потерять раскладку по процессам.

        Без этой проверки «путь вне репозитория» прошёл бы и для реализации, склеившей
        все восемь процессов в один файл.
        """
        assert _resolve(log_directory=None).parent.name == "camera_0"

    def test_env_binding_is_honoured_for_a_silent_config(self, tmp_path, monkeypatch) -> None:
        """Воля оператора действует: она и есть штатный способ увести логи куда надо."""
        monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(tmp_path))

        resolved = _resolve(log_directory=None)

        assert tmp_path in resolved.parents


class TestExplicitDirectoryIsNotTouched:
    def test_absolute_directory_from_config_wins(self, tmp_path) -> None:
        """Прод задаёт каталог всегда (``system.log_dir``) — эта дорога не менялась."""
        resolved = _resolve(log_directory=str(tmp_path / "prototype_2"))

        assert resolved.parent == tmp_path / "prototype_2" / "camera_0"

    def test_relative_directory_from_config_is_still_relative_to_cwd(self, tmp_path, monkeypatch) -> None:
        """Заданный ОТНОСИТЕЛЬНЫЙ каталог по-прежнему резолвится от cwd — и это НЕ дефект.

        Именно так работает `logs/prototype_2` у прототипа. Тест закрепляет границу
        правки: чинили молчание конфига, а не право вызывающего указать путь от cwd.
        Он же ловит попытку «починить» задачу 3.3 запретом относительных путей — это
        сломало бы прод.
        """
        monkeypatch.chdir(tmp_path)

        resolved = _resolve(log_directory="logs/prototype_2")

        assert resolved.parent == tmp_path / "logs" / "prototype_2" / "camera_0"

    def test_without_a_process_the_directory_is_used_as_is(self, tmp_path) -> None:
        """Процесса нет → подпапки по имени нет, но каталог тот же."""
        resolved = _resolve(log_directory=str(tmp_path), process_name=None)

        assert resolved.parent == tmp_path


class TestNoRelativeLogsLiteralLeftInTheModule:
    def test_the_materialized_default_is_gone_from_the_source(self) -> None:
        """Страж РЕГРЕССИИ по тексту — намеренно, и вот почему.

        Свойство выше ловит возврат дефекта на ЭТОЙ дороге. Но соблазн написать
        ``Path("logs")`` живёт в самом файле (так было до задачи 3.3), и вернуть его
        можно в соседнем методе, где свойства нет. Дешёвая проверка на литерал
        закрывает именно это: не логику, а рецидив приёма.
        """
        module_file = Path(__file__).resolve().parents[1] / "core" / "logger_core.py"
        text = module_file.read_text(encoding="utf-8")
        # Упоминания в докстрингах законны и нужны (они объясняют, почему так нельзя):
        # строки с ``разметкой`` из проверки исключаются, судится только код.
        code = "\n".join(line for line in text.splitlines() if "``" not in line)

        assert '_Path("logs")' not in code
        assert 'Path("logs")' not in code
