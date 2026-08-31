# -*- coding: utf-8 -*-
"""Задача 3.3: harness не кормит корневой ``logs/`` репозитория.

``headless_backend`` поднимает НАСТОЯЩУЮ систему из девяти процессов, и они писали в
``<репозиторий>/logs/prototype_2/`` — потому что так велит ``system.yaml``, а тесту
каталог никто не задавал. Замер: один прогон ``test_capabilities.py`` дописывал
**163 909 байт**, полный корневой гейт — **428 736**; каталог дорос до 467 МиБ.

Процессы здесь НЕ поднимаются: судится собранная конфигурация. Живое доказательство
снято дельта-методом по файлам каталога (163 909 → 0 байт при 12 зелёных тестах) —
поднимать девять процессов ради этого в каждом прогоне незачем.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from backend_ctl import harness as harness_module
from backend_ctl.harness import BackendHarness, build_headless_launcher

#: Корень репозитория: файл — backend_ctl/tests/<файл>.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _logger_dirs(launcher: Any) -> Dict[str, str]:
    """Каталог логов, доехавший до менеджеров каждого процесса собранной системы."""
    processes: List[Tuple[str, Dict[str, Any]]] = launcher._processes
    return {
        name: str(((proc.get("managers") or {}).get("logger") or {}).get("log_directory", ""))
        for name, proc in processes
    }


class TestBuilderHonoursTheGivenDirectory:
    def test_given_directory_reaches_every_process(self, tmp_path) -> None:
        launcher = build_headless_launcher(with_base=True, log_dir=str(tmp_path))
        dirs = _logger_dirs(launcher)

        assert dirs, "сборка обязана дать процессы — иначе проверка ниже вакуумна"
        for name, value in dirs.items():
            assert value, f"{name}: каталог логов пуст"
            assert tmp_path == Path(value) or tmp_path in Path(value).parents, (
                f"{name}: каталог не тот, что задан: {value}"
            )

    def test_repository_logs_appear_nowhere_in_the_built_configuration(self, tmp_path) -> None:
        """Пара к предыдущему: мало «наш путь есть», нужно «чужого нет».

        Проверка только на присутствие своего каталога прошла бы и для сборки, которая
        ПОМИМО него оставила ``logs/prototype_2`` где-нибудь ещё — а писателей у процесса
        несколько (логи, ошибки, статистика), и хватит одного забытого.
        """
        launcher = build_headless_launcher(with_base=True, log_dir=str(tmp_path))
        blob = repr(launcher._processes)

        assert "prototype_2" not in blob, "в собранной конфигурации остался каталог из yaml"
        assert str(_REPO_ROOT) not in blob.replace(str(tmp_path), ""), (
            "в собранной конфигурации остался путь внутри репозитория"
        )

    def test_without_the_argument_the_yaml_value_still_acts(self) -> None:
        """Граница правки: дефолт НЕ менялся.

        28 из 34 живых зондов каталог себе не задают, и подмена дефолта на временный
        увела бы их логи туда, где оператор их не ищет. Тест краснеет, если кто-то
        «доведёт задачу до конца», поменяв дефолт заодно.
        """
        launcher = build_headless_launcher(with_base=True)
        dirs = _logger_dirs(launcher)

        assert dirs
        assert all("prototype_2" in value for value in dirs.values()), f"дефолт разошёлся с system.yaml: {dirs}"


class TestHarnessForwardsTheDirectory:
    def test_harness_passes_its_log_dir_to_the_builder(self, tmp_path, monkeypatch) -> None:
        """Проводка от параметра harness до сборщика.

        Это проверка ПРОВОДА, и она названа так намеренно: реальную систему тест не
        поднимает (девять процессов ради одного аргумента), а без провода параметр был бы
        принят и потерян — ровно тот класс, где «механизм назван и не действует».
        """
        seen: Dict[str, Any] = {}

        def _fake_builder(**kwargs: Any) -> Any:
            seen.update(kwargs)
            raise RuntimeError("дальше не идём — нужен только аргумент")

        monkeypatch.setattr(harness_module, "build_headless_launcher", _fake_builder)

        harness = BackendHarness(with_base=True, log_dir=str(tmp_path))
        with pytest.raises(RuntimeError):
            harness.start()

        assert seen.get("log_dir") == str(tmp_path)

    def test_the_session_fixture_binds_a_directory_at_all(self) -> None:
        """Страж самой фикстуры: она обязана ЗАДАВАТЬ каталог, а не полагаться на yaml.

        Без этой проверки правка могла бы уехать обратно одной строкой, и гейт снова начал
        бы кормить репозиторий — молча, потому что все тесты остались бы зелёными.
        """
        source = (Path(__file__).parent / "conftest.py").read_text(encoding="utf-8")

        assert "log_dir=" in source, "фикстура headless_backend перестала задавать каталог логов"
