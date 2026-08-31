# -*- coding: utf-8 -*-
"""Задача 3.3: ``assemble_proc_dicts`` не материализует каталог логов в конфиг процессов.

Здесь стоял ``log_dir: str = "logs"``, и эта строка попадала в конфиг КАЖДОГО процесса.
Дальше ``_resolve_log_dir`` смотрит на env только когда каталог НЕ задан — то есть наш
дефолт бил волю вызывающего, и увести логи из ``cwd`` было НЕЧЕМ: такого поля нет ни у
``build_app``, ни у ``app.yaml``, ни у ``AppSpec``. Замер: ``examples/minimal_app`` писал
111 354 байта за прогон в ``<репозиторий>/logs/``, хотя тест выставлял env.

Тот же класс дефекта модуль уже знает про себя: докстринг рядом объясняет, почему
``expand_observability`` делается ВНУТРИ, — «разложенный снаружи L1 материализовал бы
дефолты и стал бы неперебиваемым».
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from multiprocess_framework.modules.app_module.builder import assemble_proc_dicts

#: Корень репозитория: файл — modules/app_module/tests/<файл>.
_REPO_ROOT = Path(__file__).resolve().parents[4]

#: Форма как у соседнего ``test_builder.py``: ``processes`` — СПИСОК, а не мапа.
_GENERIC_PROCESS = "multiprocess_framework.modules.process_module.core.process_module.ProcessModule"

_BLUEPRINT: Dict[str, Any] = {
    "name": "minimal",
    "processes": [
        {"process_name": "ticker", "process_class": _GENERIC_PROCESS, "plugins": []},
        {"process_name": "console_sink", "process_class": _GENERIC_PROCESS, "plugins": []},
    ],
    "wires": [],
}


def _log_dirs(blueprint: Dict[str, Any] | None = None, **kwargs) -> Dict[str, str]:
    """Каталог логов, ДОЕХАВШИЙ до менеджеров каждого процесса.

    Смотрим ``managers.logger.log_directory``, а не ``config.log_dir``: последний
    ``ProcessLaunchConfig.build`` из payload выбрасывает, поэтому проверка «ключа нет»
    была бы зелёной при любой реализации, включая дореформенную. Поймано первым
    прогоном этого файла.
    """
    dicts = assemble_proc_dicts(dict(blueprint or _BLUEPRINT), **kwargs)
    return {
        name: str(((proc.get("managers") or {}).get("logger") or {}).get("log_directory", ""))
        for name, proc in dicts.items()
    }


class TestSilentDefaultStaysSilent:
    def test_without_an_argument_the_directory_is_absolute_and_outside_the_repo(self) -> None:
        """Свойство: молчание вызывающего не превращается в относительную «logs».

        Судится ВНЕ-репозиторность, а не равенство temp-пути: «путь равен temp» прошло бы
        и для реализации, объявившей своим temp каталог внутри дерева.
        """
        got = _log_dirs()

        assert set(got) == {"ticker", "console_sink"}, "сборка обязана дать оба процесса"
        for name, value in got.items():
            resolved = Path(value)
            assert value, f"{name}: каталог логов пуст — менеджерам некуда писать"
            assert resolved.is_absolute(), f"{name}: относительный путь резолвится от cwd: {value}"
            assert _REPO_ROOT not in resolved.parents, f"{name}: логи уехали в репозиторий: {value}"

    def test_env_binding_of_the_caller_now_acts(self, tmp_path, monkeypatch) -> None:
        """То, из-за чего задача вообще существует.

        До правки ``examples/minimal_app`` выставлял ``MULTIPROCESS_LOG_DIR`` и всё равно
        писал в репозиторий: материализованный дефолт был непустым, а env смотрят только
        на пустой. Соседнюю ручку чистим явно, иначе тест мерил бы приоритет пары.
        """
        monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(tmp_path))
        monkeypatch.delenv("INSPECTOR_LOG_DIR", raising=False)

        got = _log_dirs()

        assert got == {"ticker": str(tmp_path), "console_sink": str(tmp_path)}

    def test_the_literal_logs_is_not_the_default_of_the_signature(self) -> None:
        """Проверка ИМЕННО дефолта, а не поведения: они расходятся при опечатке в ветке.

        Сверяется с ``__defaults__``/``__kwdefaults__``, а не с числом рядом: тест,
        берущий ожидание из самого испытуемого, согласится с любым ответом.
        """
        assert assemble_proc_dicts.__kwdefaults__["log_dir"] is None


class TestExplicitValueStillActs:
    def test_given_directory_reaches_every_process(self, tmp_path) -> None:
        """Приёмная сторона: без неё «дефолт не материализуется» прошло бы и для
        реализации, которая игнорирует аргумент вовсе."""
        got = _log_dirs(log_dir=str(tmp_path))

        assert got == {"ticker": str(tmp_path), "console_sink": str(tmp_path)}

    def test_per_process_log_dir_is_not_declarable_by_the_blueprint(self, tmp_path) -> None:
        """НАЗВАННОЕ ограничение, а не проверка возможности.

        Ветка ``if not cfg.log_dir`` в ассемблере выглядит как «уважаем каталог, заданный
        процессу рецептом» — но у ``ProcessConfig`` топологии поля ``log_dir`` НЕТ, ключ
        просто игнорируется, и ложной эта ветка не бывает на этой дороге никогда.
        Первая редакция теста закрепляла обратное и честно покраснела.

        Тест оставлен тревожной растяжкой: появится поле — он покраснеет, и тогда надо
        будет либо провести его до ассемблера, либо снять мёртвую ветку. Молча получить
        «поле объявлено, но не действует» — хуже обоих.
        """
        blueprint = {
            "name": "minimal",
            "processes": [
                {
                    "process_name": "ticker",
                    "process_class": _GENERIC_PROCESS,
                    "plugins": [],
                    "log_dir": str(tmp_path / "own"),
                },
                {"process_name": "console_sink", "process_class": _GENERIC_PROCESS, "plugins": []},
            ],
            "wires": [],
        }

        got = _log_dirs(blueprint, log_dir=str(tmp_path / "common"))

        assert got == {
            "ticker": str(tmp_path / "common"),
            "console_sink": str(tmp_path / "common"),
        }, "у процесса появился действующий log_dir — см. докстринг, ветку ассемблера надо решить"
