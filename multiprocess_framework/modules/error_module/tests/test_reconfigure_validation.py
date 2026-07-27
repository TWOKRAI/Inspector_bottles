# -*- coding: utf-8 -*-
"""R9 у ErrorManager: свой валидатор и целость severity-маршрутов при отказе.

Почему отдельный файл, а не проверка на логгере: у ErrorManager разбор конфига
СВОЙ (``_normalize_error_config`` + ``expand_error_manager_config``), потому что
он принимает и плоский error-dict, и развёрнутый LoggerManagerConfig. Наследовать
валидатор логгера было нельзя — проверено: ``LoggerManagerConfig.model_validate``
на плоском error-dict ЛИШНИЕ поля игнорирует и возвращает дефолтный конфиг, то
есть «проверка», пропускающая любую опечатку.

Слом-инъекции, измерено:
  B5 удалить ``ErrorManager._validate_config`` (унаследовать родительский)
     → красный: rejected_config_does_not_touch_channels.
     Первая редакция этого теста НЕ ловила B5 и была зелёной под собственным
     сломом: она подавала ``batch_overflow_policy`` — поле, которое знают ОБА
     валидатора, так что родительский справлялся сам. Различает их только
     поле самого ErrorManager (``error_file_path`` → разворачивается в
     ``channels.errors_file.file_path``): родительский его не знает и
     пропускает мусор молча.
  B8 не восстанавливать слепок конфига в ``ErrorManager.__init__``
     → красный: include_stacktrace_survives_rollback
"""

from __future__ import annotations

from pathlib import Path

from ..core.error_manager import ErrorManager


def _error_manager(tmp_path: Path) -> ErrorManager:
    em = ErrorManager(
        config={
            "app_name": "r9_errors",
            "log_directory": str(tmp_path),
            "default_level": "WARNING",
        }
    )
    em.initialize()
    return em


def test_flat_config_typo_rejected(tmp_path: Path) -> None:
    """Опечатка в ПЛОСКОМ error-конфиге отвергается, реестр цел.

    Именно та форма, которую родительский валидатор пропустил бы молча.
    """
    em = _error_manager(tmp_path)
    try:
        before = sorted(em._channel_registry.names())
        assert before, "предусловие: каналы есть"

        applied = em.reconfigure(
            {
                "app_name": "r9_errors",
                "log_directory": str(tmp_path),
                "batch_overflow_policy": "drop_middle",
            }
        )

        assert applied is False, "невалидная политика переполнения должна отвергаться"
        assert sorted(em._channel_registry.names()) == before, "отказ снёс реестр каналов"
    finally:
        em.shutdown()


def test_expanded_config_typo_rejected(tmp_path: Path) -> None:
    """Вторая форма ввода — развёрнутый конфиг — проверяется так же."""
    em = _error_manager(tmp_path)
    try:
        before = sorted(em._channel_registry.names())
        raw = em.config.model_dump()
        raw["batch_overflow_policy"] = "drop_middle"

        assert em.reconfigure(raw) is False
        assert sorted(em._channel_registry.names()) == before
    finally:
        em.shutdown()


def test_severity_routes_survive_rejection(tmp_path: Path) -> None:
    """Отвергнутый reload не имеет права оставить ошибки без маршрута.

    ``_level_to_channel`` строится по составу реестра. Пустой реестр после отказа
    означал бы пустой severity-роутинг: ERROR/CRITICAL уходили бы в floor, а
    сигнал «маршрут сломан» — из-за опечатки в неродственном поле.
    """
    em = _error_manager(tmp_path)
    try:
        before_routes = dict(em._level_to_channel)
        assert before_routes.get("ERROR"), "предусловие: маршрут ERROR построен"

        em.reconfigure({"app_name": "r9_errors", "batch_overflow_policy": "drop_middle"})

        assert dict(em._level_to_channel) == before_routes, "severity-маршруты потеряны на отказе"

        em.error("после отвергнутого reload ошибка обязана дойти по маршруту", module="r9")
        em.flush()
        # Путь берём фактический, а не из config.channels: там лежит
        # незарезолвленное относительное 'logs/errors.log', и тест читал бы
        # боевой лог репозитория вместо своего tmp_path. Резолв кладёт файл в
        # <log_directory>/logs/errors.log — относительный префикс сохраняется.
        errors_log = tmp_path / "logs" / "errors.log"
        assert errors_log.exists(), f"файл ошибок не создан: {errors_log}"
        assert "после отвергнутого reload" in errors_log.read_text(encoding="utf-8", errors="replace")
    finally:
        em.shutdown()


def test_valid_reconfigure_still_applies(tmp_path: Path) -> None:
    """Парная половина: проверки выше не должны держаться на сломанном reconfigure."""
    em = _error_manager(tmp_path)
    try:
        assert (
            em.reconfigure(
                {
                    "app_name": "r9_errors",
                    "log_directory": str(tmp_path),
                    "batch_max_pending": 4242,
                    "batch_overflow_policy": "drop_newest",
                }
            )
            is True
        )
        assert em.config.batch_max_pending == 4242
        assert em._channel_registry.names(), "валидный reload оставил менеджер без каналов"
        assert em._level_to_channel.get("ERROR"), "валидный reload не перестроил severity-маршруты"
    finally:
        em.shutdown()


def test_rejected_config_does_not_touch_channels(tmp_path: Path) -> None:
    """Свой валидатор отличим от отката: отвергнутый конфиг не закрывает каналы.

    По именам каналов два исхода неразличимы — откат воссоздаёт тот же набор.
    Различает только тождество объектов. Именно эта проверка ловит подмену
    ``ErrorManager._validate_config`` родительским: тот на плоском error-dict
    ничего не проверяет, отказ съезжает на второй рубеж, и каналы пересоздаются.
    """
    em = _error_manager(tmp_path)
    try:
        channel_before = em._channel_registry.get("errors_file")
        assert channel_before is not None, "предусловие: канал ошибок есть"

        # Поле ЭТОГО менеджера, а не логгера: ``error_file_path`` разворачивается
        # в ``channels.errors_file.file_path``. Родительский валидатор такого
        # поля не знает и пропускает мусор молча — измерено, не предположено.
        assert em.reconfigure({"app_name": "r9_errors", "error_file_path": 123}) is False

        assert em._channel_registry.get("errors_file") is channel_before, (
            "канал ошибок пересоздан: конфиг отвергнут уже после разрушения реестра"
        )
    finally:
        em.shutdown()


def test_include_stacktrace_survives_rollback(tmp_path: Path, monkeypatch) -> None:
    """Откат возвращает и флаг трейсбеков, которого нет в LoggerManagerConfig.

    Слепок для отката у родителя — развёрнутый LoggerManagerConfig; в нём
    ``include_stacktrace`` отсутствует, а ``_normalize_error_config`` на такой
    форме подставляет True. Откат тихо включил бы трейсбеки тому, кто их
    выключил — и узнал бы он об этом по трейсбекам в проде.
    """
    em = ErrorManager(
        config={
            "app_name": "r9_errors",
            "log_directory": str(tmp_path),
            "include_stacktrace": False,
        }
    )
    em.initialize()
    try:
        calls = {"n": 0}
        original = em._setup_channels

        def _explode_once() -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("не смог открыть файл канала")
            original()

        monkeypatch.setattr(em, "_setup_channels", _explode_once)

        assert em.reconfigure({"app_name": "r9_errors", "log_directory": str(tmp_path)}) is False
        assert calls["n"] >= 2, "откат не пересобирал каналы вовсе"
        assert em._include_stacktrace is False, "откат тихо включил трейсбеки"
        assert em._channel_registry.names(), "откат не вернул каналы"
    finally:
        em.shutdown()


def test_include_stacktrace_survives_rejection(tmp_path: Path) -> None:
    """Флаг ErrorManager, которого нет в LoggerManagerConfig, тоже не сползает.

    ``_rebuild_from_config`` выставляет ``_include_stacktrace`` ДО пересборки
    каналов — на отвергнутом конфиге он не должен выставляться вовсе.
    """
    em = ErrorManager(
        config={
            "app_name": "r9_errors",
            "log_directory": str(tmp_path),
            "include_stacktrace": False,
        }
    )
    em.initialize()
    try:
        assert em._include_stacktrace is False, "предусловие: трейсбеки выключены"
        em.reconfigure({"app_name": "r9_errors", "batch_overflow_policy": "drop_middle"})
        assert em._include_stacktrace is False, "отвергнутый конфиг тихо включил трейсбеки"
    finally:
        em.shutdown()
