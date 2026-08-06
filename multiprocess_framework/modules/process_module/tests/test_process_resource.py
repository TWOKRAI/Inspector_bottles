# -*- coding: utf-8 -*-
"""Ф3.5 — ``Resource`` процесса: собран один раз, есть в каждой записи.

Понятие из словаря OTel — набор атрибутов того, кто породил телеметрию. Каркас
был с Ф0.5 (база контекста логгера), содержимого в нём было одно поле.

Свойства, которые здесь стерегутся:

1. набор собирается ОДИН раз (база процесса), а не на запись;
2. недостающее поле **пропускается**, а не заполняется словом «unknown»:
   отсутствие ключа честно значит «не знаем», заглушка выглядела бы знанием;
3. ни одна ветка сборки не вправе уронить процесс — Resource это украшение
   записи, а не работа;
4. инкарнация действительно берётся из реестра, а не выдумывается: без неё
   записи процесса ДО и ПОСЛЕ перезапуска неотличимы.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Dict

import pytest

from multiprocess_framework import version as fw_version_module
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.version import __version__, code_version


def _git_head_or_skip() -> str:
    """Хеш HEAD, спрошенный НЕЗАВИСИМО от проверяемого кода.

    Без git пропуск, а не зелёный прогон: зелень без оракула означала бы
    «проверить нечем», и это должно быть видно в отчёте.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            cwd=str(fw_version_module._PACKAGE_DIR),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover — среда без git
        pytest.skip("git недоступен — независимого оракула версии нет")
    if result.returncode != 0:  # pragma: no cover — копия без .git
        pytest.skip("каталог не является git-репозиторием — независимого оракула версии нет")
    return result.stdout.strip()


@pytest.fixture(autouse=True)
def _reset_version_cache():
    """Кэш версии живёт на модуле — между тестами он обязан быть чистым."""
    fw_version_module._cached_code_version = None
    yield
    fw_version_module._cached_code_version = None


class _FakeProcessData:
    def __init__(self, metadata: Dict[str, Any]) -> None:
        self.metadata = metadata


class _FakePSR:
    def __init__(self, metadata: Dict[str, Any] | None) -> None:
        self._metadata = metadata

    def get_process_data(self, name: str) -> Any:
        return _FakeProcessData(self._metadata) if self._metadata is not None else None


class _FakeShared:
    def __init__(self, psr: Any) -> None:
        self.process_state_registry = psr


def _process(*, metadata: Dict[str, Any] | None = None, config: Dict[str, Any] | None = None) -> ProcessModule:
    """Процесс без initialize(): ``_build_resource`` трогает только имя, PSR и конфиг.

    ``config_handler = None`` выставляется ЯВНО, и это не формальность:
    ``get_config`` смотрит на него первым, а у объекта, собранного через
    ``__new__``, атрибута нет вовсе — вызов падал бы ``AttributeError`` внутри
    защитного ``except`` и тихо давал набор без рецепта. Тест бы «прошёл», ничего
    не проверив. Тот же класс харнесного дефекта уже описан в докстринге
    ``ProcessModule.update_config`` (R6, 2026-07-29) — и повторился здесь.
    """
    proc = ProcessModule.__new__(ProcessModule)
    proc.name = "camera_0"
    proc.shared_resources = _FakeShared(_FakePSR(metadata))
    proc.config = dict(config or {})
    proc.config_handler = None
    return proc


class TestResourceContent:
    def test_full_set_is_collected(self) -> None:
        proc = _process(
            metadata={"routing_incarnation": 3},
            config={"observability_recipe_path": "d:/proj/recipes/dualcam_synth.yaml"},
        )
        resource = proc._build_resource()

        assert resource["proc_name"] == "camera_0"
        assert resource["incarnation"] == 3
        assert resource["recipe"] == "dualcam_synth", "в записи должно ехать имя рецепта, а не путь"
        assert resource["fw_version"], "версия фреймворка не собрана"

    def test_pid_is_this_process_not_its_parent(self) -> None:
        """Ф4.4: ``pid`` — единственное, что осталось от «процессора обогащения».

        Оракул — сама ОС: ``os.getpid()`` спрашивается тестом отдельно. Поле
        отвечает на вопрос, на который инкарнация не отвечает: инкарнация
        различает ИНСТАНСЫ по логике фреймворка, а pid — единственный ключ,
        по которому запись сшивается с внешним миром (диспетчер задач, дамп,
        вывод сторонней утилиты).

        Опасность, ради которой тест и написан: набор собирается на
        инициализации, и если сборку когда-нибудь перенесут в родителя
        (ассемблер), pid станет РОДИТЕЛЬСКИМ — одинаковым у всех процессов и
        правдоподобным настолько, что заметить это будет нечем.
        """
        resource = _process()._build_resource()

        assert resource["pid"] == os.getpid()
        assert isinstance(resource["pid"], int), "pid обязан быть числом — по нему сравнивают, а не показывают"

    def test_incarnation_comes_from_the_registry_not_from_thin_air(self) -> None:
        """Без инкарнации записи ДО и ПОСЛЕ перезапуска неотличимы — вот её цена."""
        before = _process(metadata={"routing_incarnation": 0})._build_resource()
        after = _process(metadata={"routing_incarnation": 1})._build_resource()

        assert before["incarnation"] == 0
        assert after["incarnation"] == 1
        assert before["incarnation"] != after["incarnation"]

    def test_version_names_the_commit_that_produced_the_record(self) -> None:
        """В записи — идентичность КОДА, а не рукописная константа (Н-5).

        Оракул независимый: хеш спрашивается у git отдельным вызовом, а не
        берётся из проверяемой функции — иначе тест согласился бы с любым
        ответом, включая «версия не менялась четыре месяца».

        До решения владельца 2026-08-05 здесь стояло сравнение с
        ``__version__``: оно было зелёным и ровно поэтому бесполезным —
        константа не двигалась сквозь ``state_store``, ``chain`` и всю
        переделку наблюдаемости, и записи разных срезов дерева были
        неотличимы.
        """
        head = _git_head_or_skip()

        fw_version = _process()._build_resource()["fw_version"]

        assert head in fw_version, f"запись не называет коммит, который её породил: {fw_version!r}"
        assert fw_version.startswith(__version__), (
            f"семантическая часть версии потеряна: {fw_version!r} — по ней читают линию релиза"
        )


class TestCodeVersionMapping:
    """Как ответ git превращается в версию записи (Н-5, решение владельца 2026-08-05).

    Отображение проверяется на подставленном ответе, а не на живом дереве:
    «грязное» состояние репозитория тестом не управляемо, а гарантия
    «грязь названа» нужна ровно тогда, когда она есть.
    """

    def test_clean_tree_gives_semantic_version_plus_commit(self, monkeypatch) -> None:
        monkeypatch.setattr(fw_version_module, "_git_describe", lambda: "9950851b")
        assert code_version() == "2.0.0+9950851b"

    def test_dirty_tree_is_named(self, monkeypatch) -> None:
        """Без суффикса хеш ВРЁТ о том, какой код выполнялся."""
        monkeypatch.setattr(fw_version_module, "_git_describe", lambda: "9950851b-dirty")
        assert code_version() == "2.0.0+9950851b.dirty"

    def test_tagged_tree_keeps_the_whole_description(self, monkeypatch) -> None:
        monkeypatch.setattr(fw_version_module, "_git_describe", lambda: "v2.1.0-3-g9950851b")
        assert code_version() == "2.0.0+v2.1.0.3.g9950851b"

    def test_no_git_falls_back_to_the_bare_constant(self, monkeypatch) -> None:
        """Отсутствие идентичности видно по самому значению — заглушки нет."""
        monkeypatch.setattr(fw_version_module, "_git_describe", lambda: "")
        assert code_version() == "2.0.0"


class TestGitIsAskedOnceAndNeverBreaksTheProcess:
    def test_git_is_asked_once_per_process(self, monkeypatch) -> None:
        """35 мс однократно на старте — это цена решения; 35 мс на запись — нет."""
        calls: list[list[str]] = []

        def _spy(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout="9950851b\n", stderr="")

        monkeypatch.setattr(fw_version_module.subprocess, "run", _spy)

        first = code_version()
        for _ in range(50):
            code_version()

        assert first == "2.0.0+9950851b"
        assert len(calls) == 1, f"git спрошен {len(calls)} раз вместо одного — кэш не держит"

    def test_git_is_asked_about_dirtiness_and_about_the_right_tree(self, monkeypatch) -> None:
        """Утверждение на ГРАНИЦЕ ОС: что именно спрошено у git.

        Отображение ``-dirty`` → ``.dirty`` проверено выше на подставленном
        ответе, но если из argv убрать ``--dirty``, git такого ответа просто
        никогда не даст — и все те тесты останутся зелёными. Здесь стережётся
        сам вопрос, а не перевод ответа. По той же причине проверяется ``cwd``:
        рабочий каталог воркера может быть любым, а спрашивать надо про дерево
        фреймворка.
        """
        seen: Dict[str, Any] = {}

        def _spy(argv, **kwargs):
            seen["argv"] = argv
            seen["cwd"] = kwargs.get("cwd")
            seen["timeout"] = kwargs.get("timeout")
            return subprocess.CompletedProcess(argv, 0, stdout="9950851b\n", stderr="")

        monkeypatch.setattr(fw_version_module.subprocess, "run", _spy)
        code_version()

        assert "--dirty" in seen["argv"], f"о грязи дерева не спрошено — суффикс не появится никогда: {seen['argv']}"
        assert seen["cwd"] == str(fw_version_module._PACKAGE_DIR), (
            "git спрошен про чужое дерево — рабочий каталог процесса тут ни при чём"
        )
        # Ревью Fable: снятие timeout оставляло все тесты зелёными — соседний
        # `test_hanging_git...` сам поднимает TimeoutExpired, то есть сторожит
        # ветку обработки, а не механизм, который её порождает. Без срока
        # зависший git подвесил бы инициализацию процесса.
        assert seen["timeout"], "у вызова git нет срока — зависший git подвесит инициализацию процесса"

    def test_missing_git_binary_does_not_raise(self, monkeypatch) -> None:
        def _boom(argv, **kwargs):
            raise FileNotFoundError("git не установлен")

        monkeypatch.setattr(fw_version_module.subprocess, "run", _boom)
        assert code_version() == "2.0.0"

    def test_non_zero_exit_does_not_raise(self, monkeypatch) -> None:
        """Развёрнутая копия без ``.git``: git отвечает, но отказом."""

        def _fail(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 128, stdout="", stderr="not a git repository")

        monkeypatch.setattr(fw_version_module.subprocess, "run", _fail)
        assert code_version() == "2.0.0"

    def test_hanging_git_does_not_hang_the_process(self, monkeypatch) -> None:
        def _hang(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 5)

        monkeypatch.setattr(fw_version_module.subprocess, "run", _hang)
        assert code_version() == "2.0.0"


class TestMissingPiecesAreOmittedNotFaked:
    def test_no_registry_no_incarnation_key(self) -> None:
        proc = _process(metadata=None)
        assert "incarnation" not in proc._build_resource()

    def test_no_recipe_no_recipe_key(self) -> None:
        assert "recipe" not in _process(metadata={"routing_incarnation": 1})._build_resource()

    def test_empty_recipe_path_is_not_an_empty_name(self) -> None:
        """Пустой путь — это «не знаем», а не рецепт с пустым именем."""
        proc = _process(config={"observability_recipe_path": ""})
        assert "recipe" not in proc._build_resource()

    def test_process_name_is_always_there(self) -> None:
        """Минимум набора не зависит ни от чего внешнего."""
        proc = ProcessModule.__new__(ProcessModule)
        proc.name = "lonely"
        proc.shared_resources = None
        proc.config = {}
        proc.config_handler = None
        assert proc._build_resource()["proc_name"] == "lonely"


class TestCollectionNeverBreaksTheProcess:
    """Resource — украшение записи; уронить им инициализацию нельзя."""

    def test_exploding_registry_does_not_raise(self) -> None:
        class _Boom:
            def get_process_data(self, name: str) -> Any:
                raise RuntimeError("реестр развалился")

        proc = _process()
        proc.shared_resources = _FakeShared(_Boom())
        resource = proc._build_resource()
        assert resource["proc_name"] == "camera_0"
        assert "incarnation" not in resource

    def test_exploding_config_does_not_raise(self) -> None:
        class _BoomConfig(ProcessModule):
            def get_config(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
                raise RuntimeError("конфиг развалился")

        proc = _BoomConfig.__new__(_BoomConfig)
        proc.name = "camera_0"
        proc.shared_resources = _FakeShared(_FakePSR({"routing_incarnation": 2}))
        proc.config = {}
        proc.config_handler = None
        resource = proc._build_resource()
        assert resource["incarnation"] == 2, "падение одной ветки не должно уносить остальные"
        assert "recipe" not in resource


class TestResourceIsCollectedOnceAndReachesRecords:
    def test_real_initialize_puts_the_whole_set_into_the_base(self) -> None:
        """ПРОВОДКА: настоящий ``initialize()``, а не повтор его строки.

        Первая редакция этого теста сама звала
        ``set_base_context(**proc._build_resource())`` — то есть повторяла строку
        шага 9 вместо того, чтобы её проверить. Слом-инъекция это и показала:
        откат шага 9 к прежнему ``proc_name=self.name`` не убивал НИ ОДНОГО
        теста. Собрать набор верно и не поставить его — то же самое, что не
        собрать.

        Свидетель — ``fw_version``: в прежней строке его не было, поэтому его
        присутствие в базе доказывает, что зовётся именно ``_build_resource``.
        """
        process = ProcessModule("resource_wiring_probe")
        try:
            assert process.initialize() is True, "initialize() не прошёл на пустом конфиге"

            logger = process.get_manager("logger")
            assert logger is not None, "логгера нет — проверять проводку не на чем"
            base = logger._get_base_context()

            assert base.get("proc_name") == "resource_wiring_probe"
            assert base.get("fw_version"), "в базе процесса нет fw_version — шаг 9 кладёт не Resource, а одно имя"
        finally:
            process.shutdown()

    def test_every_record_carries_the_resource(self, tmp_path: Any) -> None:
        """Сквозная пара на НАСТОЯЩЕМ логгере: набор виден в записи."""
        from multiprocess_framework.modules.logger_module.core.log_config import LogLevel, LogScope
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        class _Sink:
            name = "collect"

            def __init__(self) -> None:
                self.records: list = []

            def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
                self.records.append(data)
                return {"status": "success"}

            def close(self) -> None: ...

        logger = LoggerManager(
            manager_name="ResourceProbe",
            config={
                "app_name": "res",
                "log_directory": str(tmp_path),
                "enable_batching": False,
                "modules": {},
                "channels": {"f": {"type": "file", "enabled": True, "file_path": str(tmp_path / "a.log")}},
                "scopes": {"SYSTEM": {"channels": ["f"]}},
            },
        )
        logger.initialize()
        try:
            sink = _Sink()
            logger.add_tap(sink, min_level="DEBUG", name="collect")
            logger.set_base_context(**_process(metadata={"routing_incarnation": 5})._build_resource())

            logger.log(LogScope.SYSTEM, LogLevel.INFO, "любая запись", module="m")

            extra = sink.records[0]["extra"]
            assert extra["proc_name"] == "camera_0"
            assert extra["incarnation"] == 5
            assert extra["fw_version"]
        finally:
            logger.shutdown()


@pytest.mark.parametrize("field", ["proc_name", "fw_version", "incarnation", "recipe"])
def test_resource_field_names_are_stable(field: str) -> None:
    """Имена полей — контракт наружу (стор, GUI, будущий экспортёр OTLP).

    Литералами, а не производной от кода: тест, берущий имена из проверяемого
    места, согласится с любым переименованием.
    """
    resource = _process(
        metadata={"routing_incarnation": 1},
        config={"observability_recipe_path": "r/x.yaml"},
    )._build_resource()
    assert field in resource


class TestConfigDeliveryShapes:
    """Ключ рецепта обязан находиться в ОБЕИХ формах доставки конфига.

    Live-прогон webcam_sketch (ревью Ф3, 2026-08-05): ассемблер кладёт
    ``observability_recipe_path`` ВНУТРЬ ``proc_dict["config"]``, а ребёнок
    получает конфигом весь proc_dict — прикладные ключи у него лежат под
    ``config.<ключ>``. Плоскую форму видят PM-оркестратор и тестовый харнес;
    код, читавший только её, на живом стенде молча терял поле ``recipe`` во
    всех записях. Класс уже записан в памяти проекта после 5.12 («форма
    доставки конфига различается», хелпер ``read_process_config``) — и
    повторился здесь, потому что харнес Ф3.5 пинил только плоскую форму.

    Вложенная форма проверяется на НАСТОЯЩЕМ ``Config`` в роли
    ``config_handler`` (dot-notation — его свойство): фейковый словарь с
    самодельной точечной адресацией доказывал бы фейк, а не проводку.
    """

    def test_recipe_is_found_in_the_nested_live_shape(self) -> None:
        from multiprocess_framework.modules.config_module import Config

        proc = _process()
        proc.config_handler = Config(
            initial_data={"config": {"observability_recipe_path": "recipes/webcam_sketch.yaml"}}
        )
        assert proc._build_resource().get("recipe") == "webcam_sketch", (
            "живая форма доставки (ключ внутри proc_dict['config']) осталась без имени рецепта"
        )

    def test_flat_shape_still_wins_when_both_present(self) -> None:
        from multiprocess_framework.modules.config_module import Config

        proc = _process()
        proc.config_handler = Config(
            initial_data={
                "observability_recipe_path": "recipes/flat.yaml",
                "config": {"observability_recipe_path": "recipes/nested.yaml"},
            }
        )
        assert proc._build_resource().get("recipe") == "flat"
