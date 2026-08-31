"""
SystemLauncher — фасад запуска системы (Refactored).

Dict at Boundary: принимает только (name, proc_dict). Конвертация config → dict
выполняется в app-слое через process() из data_schema_module.

Нормализация: merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA) —
consumer определяет ожидаемый формат, недостающие ключи заполняются.
"""

import time as _time
from multiprocessing import Event as _MpEvent
from typing import Optional, Dict, Any, List, Tuple, Callable

from ...logger_module.utils import FallbackLogger
from ...data_schema_module import merge_with_defaults
from .schema import DEFAULT_PROCESS_SCHEMA
from .spawner import ProcessSpawner

_logger = FallbackLogger(__name__)

# Ф7 G.3 M8a (ADR-SRM-011): "output_frames" — универсальный slot generic-процессов
# (FrameShmMiddleware, GenericProcess._init_data_pipeline), выделяемый ЛЕНИВО и НЕ
# объявленный в processes_config ни в каком виде — его невозможно извлечь парсингом
# конфига без инвазивных изменений (пришлось бы знать о GenericProcess/FrameShmMiddleware
# на уровне SystemLauncher, что нарушает границы модулей). Именованная константа вместо
# магической строки; используется как БЕЗУСЛОВНЫЙ fallback-префикс (и добавка к
# префиксам, извлечённым из config-регионов — см. _cleanup_shm_at_startup).
_DEFAULT_FRAME_SLOT_PREFIX = "output_frames"

# Task 1.2 (M14): подкаталог журнала лаунчера внутри базы логов. Лаунчер — код ДО
# существования хоть одного процесса, поэтому «каталог процесса» ему взять неоткуда;
# имя фиксировано, чтобы записи искали по известному адресу, а не «где-то в base».
_LAUNCHER_LOG_DIR_NAME = "launcher"

# Ревью Task 1.2 (F1): на платформе, где висящих сегментов не бывает, «очищено 0» —
# это свойство платформы, а не показание об уборке. Голый ноль читается как «уборка
# работала и ничего не нашла», и именно так его прочитал живой стенд. Литерал
# критерия («cleanup_stale_shm: очищено N») при этом сохранён — приёмочный тест
# независимого тестера ищет его регуляркой, и подмена строки увела бы его в красный
# ровно на той платформе, где стоит стенд.
_SHM_CLEANUP_NOT_APPLICABLE = (
    " (уборка на этой платформе недоступна: ОС освобождает mapping при закрытии последнего handle, "
    "висящих сегментов не бывает — ноль здесь структурный)"
)


def _shm_platform_note() -> str:
    """Пояснение к числу освобождённых сегментов — только там, где число не показание."""
    from ...shared_resources_module.memory.platform import is_posix

    return "" if is_posix() else _SHM_CLEANUP_NOT_APPLICABLE


class SystemLauncher:
    """
    Фасад запуска системы процессов.

    Реализует ISystemLauncher.
    Dict at Boundary: add_process(name, proc_dict) — только dict.
    Конвертация в app: launcher.add_process(*build_process_with_workers(Process1Config(), Worker1Config())).

    Args:
        config: Конфиг процессов (альтернатива add_process).
        stop_timeout: Время ожидания graceful stop (секунды).
        on_shutdown: Callback, вызываемый при завершении системы.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        stop_timeout: float = 5.0,
        on_shutdown: Optional[Callable[[], None]] = None,
        orchestrator_class_path: Optional[str] = None,
        orchestrator_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._config = config
        self._processes: List[Tuple[str, Dict[str, Any]]] = []
        self._spawner: Optional[ProcessSpawner] = None
        self._stop_timeout = stop_timeout
        self._on_shutdown = on_shutdown
        # Путь к классу оркестратора (None = default ProcessManagerProcess).
        self._orchestrator_class_path = orchestrator_class_path
        # Дополнительный конфиг для оркестратора (Dict at Boundary).
        # Ключи попадают напрямую в process_config оркестратора и доступны
        # через self.get_config(key) внутри ProcessManagerProcess.
        self._orchestrator_config: Dict[str, Any] = orchestrator_config or {}
        # Event, который ProcessManagerProcess выставляет после завершения
        # своего initialize() (все дочерние процессы spawned и запущены).
        self._system_ready_event: _MpEvent = _MpEvent()
        # ОБЩИЙ system-wide stop: проброшен ВСЕМ процессам (PM + дети). Любой
        # процесс (напр. GUI при закрытии) взводит его → каждый lifecycle-цикл
        # видит и гасится сам, ПАРАЛЛЕЛЬНО (не последовательно по команде PM).
        self._system_stop_event: _MpEvent = _MpEvent()
        # Task 1.2 (M14): журнал лаунчера. Поднимается ЛЕНИВО, на первой записи —
        # см. _ensure_observability. Конструктор их не создаёт намеренно: он
        # зовётся и там, где ни одной записи не будет (сборка конфига в тестах),
        # а подъём менеджеров открывает файлы и создаёт каталоги.
        self._logger_manager: Optional[Any] = None
        self._error_manager: Optional[Any] = None
        # Подъём журнала уже ПРОБОВАЛИ — успешно или нет (ревью Task 1.2, F2).
        # Флагом идемпотентности был сам ``_logger_manager``, а он ставится только
        # на успехе: неписуемый каталог логов означал новую попытку на КАЖДОЙ
        # записи (замер: 5 записей → 5 аварийных выходов; отдельная инъекция с
        # падающим ErrorManager дала 3 живых LoggerManager'а на 3 записи, каждый
        # со своими открытыми файлами и потоком подметальщика, и ни один не
        # закрывался). Отказ подъёма — состояние, а не событие.
        self._observability_attempted: bool = False
        # Журнал закрыт ``stop()``. Второго подъёма не будет: ``stop()`` обязан
        # быть терминальным, иначе следующая же запись воскрешает журнал (ревью
        # Task 1.2, F3: три ``stop()`` давали три подъёма и три строки закрытия).
        self._observability_closed: bool = False
        # Отказы уборки SHM на старте. Счётчик, а не только запись в журнал:
        # «терять можно, молчать нельзя» — по одной строке в errors.log нельзя
        # ответить «сколько раз», а именно повтор отличает разовый сбой от
        # сломанной уборки. Виден в get_stats()["startup"].
        self._shm_cleanup_failures: int = 0
        # Сколько сегментов освобождено последней уборкой ПЕРВОГО блока
        # (config-объявленные имена). Состояний ТРИ, а не два (ревью Task 1.2, F6),
        # и читаются они парой с ``_shm_cleanup_failures``:
        #   None + 0 отказов  — уборка не выполнялась ни разу;
        #   None + ≥1 отказов — выполнялась и УПАЛА (число неизвестно);
        #   int               — выполнилась, освободила столько имён.
        # На Windows это число всегда 0 и это не показание об уборке, а свойство
        # платформы (см. ``cleanup_stale_shm``). Префиксный блок (за флагом
        # FW_SHM_PREFIX_CLEANUP) в это число НЕ входит — у него своя строка журнала.
        self._shm_cleanup_segments: Optional[int] = None
        # Отказы стартовой работы с PID-реестром (реап осиротевших хвостов, чистка
        # на штатной остановке). Тот же класс, что и у SHM: раньше стоял голый
        # ``except: pass`` на пути лаунчера ДО существования хоть одного процесса
        # (ревью Task 1.2, F8). Провалившийся реап означает выживших от прошлого
        # запуска, а проявится это позже и в другом месте.
        self._pid_registry_failures: int = 0

    def _ensure_observability(self) -> None:
        """Поднять журнал лаунчера: ``{база логов}/launcher/`` — system.log + errors.log.

        **Тем же конфигом слоёв, что у процессов, а не своим механизмом**
        (Task 1.2, M14). Пара конфигов берётся у :func:`managers_from_log_dir` —
        той же функции, из которой собирается L0 каждого процесса
        (``base_managers_payload`` → пересборка на boot). Второй сборки «как у
        процессов, только для лаунчера» здесь нет намеренно: она разошлась бы с
        первой на первой же правке — молча, потому что расхождение видно только
        по тому, куда легли файлы.

        **База каталога — тем же резолвером** (:func:`resolve_base_log_dir`), и
        это вторая половина того же правила (ревью Task 1.2, F4). Общей была
        только ``managers_from_log_dir``, а АРГУМЕНТ ей считали две разные
        функции: лаунчер — ``default_log_base_directory()``, слой L0 процессов —
        ``resolve_base_log_dir()``. При пустом окружении они давали РАЗНЫЕ
        деревья (``…/Temp/multiprocess_framework/logs`` против относительного
        ``logs``) — ровно тот класс, который ADR-PM-044 объявляет закрытым.
        Страж — ``TestOneBaseForTheWholeRun``.

        **Почему у лаунчера ВООБЩЕ свой менеджер, а не запись через первый
        процесс.** Всё, что лаунчер делает (реап PID-реестра, уборка SHM, спавн
        оркестратора), происходит ДО существования хоть одного процесса — то
        есть до того, как появится чужой LoggerManager. Отложить записи «до
        первого процесса» нельзя: именно эти записи объясняют, почему процесса
        может и не появиться.

        **Побочный эффект назван вслух:** ``LoggerManager.__init__`` ставит
        процессный синглтон, поэтому после этого вызова ``get_std_logger`` и
        ``FallbackLogger`` ГЛАВНОГО процесса (в частности ``spawner``) тоже
        начинают писать в ``launcher/system.log``. Это не побочный ущерб, а
        вторая половина той же находки: до Task 1.2 их записи уходили в
        stdlib-фолбэк без хендлеров, то есть в никуда.

        **Ровно одна попытка за жизнь лаунчера — и на успехе, и на отказе**
        (ревью Task 1.2, F2). Флагом идемпотентности был сам ``_logger_manager``,
        то есть результат УСПЕХА: пока подъём падал, каждая следующая запись
        пробовала заново. На неписуемом каталоге это 5 аварийных выходов на 5
        записей; на падающем ``ErrorManager`` — три живых ``LoggerManager``, каждый
        с открытыми файлами и потоком подметальщика, каждый перебивает процессный
        синглтон, и ни одного не закрывает ``_shutdown_observability``. Поэтому
        флаг ставится ДО попытки, а ``_logger_manager`` — сразу после успешного
        ``initialize()``, ещё до ``ErrorManager``: половина журнала, которая
        поднялась, обязана иметь владельца, который её закроет.

        Отказ подъёма журнала не имеет права сорвать запуск системы — он уходит в
        аварийный выход (stdlib напрямую). После ``stop()`` подъёма не будет
        вовсе: см. ``_observability_closed``.
        """
        if self._observability_attempted:
            return
        self._observability_attempted = True
        try:
            from pathlib import Path

            from ...error_module import ErrorManager
            from ...logger_module import LoggerManager
            from ...process_module.configs.managers_config import managers_from_log_dir
            from ...process_module.managers.observability_reload import resolve_base_log_dir

            launcher_dir = Path(resolve_base_log_dir()) / _LAUNCHER_LOG_DIR_NAME
            managers = managers_from_log_dir(str(launcher_dir), app_name=_LAUNCHER_LOG_DIR_NAME)
            logger = LoggerManager(manager_name="logger_launcher", config=managers.logger)
            logger.initialize()
            # Владелец ставится СРАЗУ (F2): дальше может упасть ErrorManager, и без
            # этой строки поднятый логгер осиротел бы — открытые файлы и поток
            # подметальщика без того, кто их закроет.
            self._logger_manager = logger
            # B3: имя ставится В КОНФИГ — у ErrorManager имя конфига сильнее
            # аргумента конструктора, и без этой строки плоскость ошибок
            # лаунчера звалась бы безадресным «ErrorManager». Воспроизведено
            # 2026-08-31: без ``model_copy`` ``ErrorManager(manager_name=
            # "error_launcher", config=managers.error).manager_name ==
            # "ErrorManager"`` (страж — ``TestErrorPlaneHasAnAddress``).
            error_config = managers.error.model_copy(update={"manager_name": "error_launcher"})
            error = ErrorManager(manager_name="error_launcher", config=error_config)
            error.initialize()
            self._error_manager = error
        except Exception as exc:  # noqa: BLE001 — журнал не имеет права сорвать запуск
            from ..._fallback import emergency_log

            emergency_log(
                __name__,
                "error",
                "[SystemLauncher] журнал лаунчера не поднялся (второй попытки не будет): %s",
                exc,
            )

    def _shutdown_observability(self) -> None:
        """Закрыть журнал лаунчера. Идемпотентно, падать не имеет права.

        **Закрытие терминально** (ревью Task 1.2, F3): после него журнал не
        поднимется снова. Прежде ``_log_*`` звали ``_ensure_observability``,
        та видела ``None`` и поднимала ВСЁ заново — три ``stop()`` давали три
        подъёма и три строки закрытия, а «журнал закрыт» переставало что-либо
        значить. Записи после закрытия уходят в аварийный выход и НЕ теряются
        молча — окно названо в README модуля.
        """
        self._observability_closed = True
        for attr in ("_error_manager", "_logger_manager"):
            manager = getattr(self, attr, None)
            if manager is None:
                continue
            setattr(self, attr, None)
            try:
                manager.shutdown()
            except Exception as exc:  # noqa: BLE001 — закрытие журнала best-effort
                from ..._fallback import emergency_log

                emergency_log(__name__, "warning", "[SystemLauncher] %s не закрылся: %s", attr, exc)

    def _after_close(self, level: str, message: str) -> bool:
        """Запись пришла после ``stop()`` — увести её в аварийный выход.

        Возвращает True, если запись уже обслужена здесь. Журнал закрыт и второй
        раз не поднимется (F3), но «закрыт» не значит «можно потерять»: строка
        уходит в stdlib напрямую с явной пометкой окна.
        """
        if not self._observability_closed:
            return False
        from ..._fallback import emergency_log

        emergency_log(__name__, level, "[SystemLauncher] (журнал закрыт) %s", message)
        return True

    def _log_info(self, message: str) -> None:
        if self._after_close("info", message):
            return
        self._ensure_observability()
        _logger.info("[SystemLauncher] %s", message)

    def _log_warning(self, message: str) -> None:
        if self._after_close("warning", message):
            return
        self._ensure_observability()
        _logger.warning("[SystemLauncher] %s", message)

    def _log_error(self, message: str, exc: BaseException) -> None:
        """Отказ подсистемы лаунчера → плоскость ошибок (``launcher/errors.log``) с трассой.

        Один разъём на точку: запись идёт ТОЛЬКО в плоскость ошибок, без
        параллельного ``_logger.error`` — иначе один инцидент дал бы две строки
        в двух файлах, и «сколько раз это случилось» перестало бы иметь ответ.

        Зовётся ИЗНУТРИ ``except``-блока: ``log_exception`` собирает трассу через
        ``traceback.format_exc()``, то есть из активного исключения.
        """
        if self._after_close("error", f"{message}: {exc!r}"):
            return
        self._ensure_observability()
        error = self._error_manager
        if error is None:
            from ..._fallback import emergency_log

            emergency_log(__name__, "error", "[SystemLauncher] %s: %r", message, exc)
            return
        error.log_exception(exc, f"[SystemLauncher] {message}", module="launcher", include_stacktrace=True)

    def add_process(
        self,
        name: str,
        proc_dict: Dict[str, Any],
    ) -> "SystemLauncher":
        """
        Добавить процесс. Только dict.

        proc_dict нормализуется через merge_with_defaults(DEFAULT_PROCESS_SCHEMA) —
        недостающие ключи (class, queues, priority, workers) заполняются.

        Args:
            name: имя процесса (ключ в processes_config)
            proc_dict: {"class": "...", "queues": {...}, "workers": {...}, ...}

        Returns:
            self для цепочки вызовов
        """
        normalized = merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA)
        self._processes.append((name, normalized))
        return self

    def _build_processes_config(self) -> Dict[str, Dict[str, Any]]:
        """Собрать processes_config из _processes. Каждый proc_dict уже нормализован."""
        return {name: proc_dict for name, proc_dict in self._processes}

    def _get_processes_config(self) -> Dict[str, Dict[str, Any]]:
        """processes_config для ProcessSpawner: _processes или _config, с нормализацией."""
        if self._processes:
            return self._build_processes_config()
        if self._config:
            return {k: merge_with_defaults(v, DEFAULT_PROCESS_SCHEMA) for k, v in self._config.items()}
        return {}

    def _create_spawner(self, processes_config: Dict[str, Any]) -> ProcessSpawner:
        """Создать ProcessSpawner с текущими настройками."""
        spawner_kwargs: Dict[str, Any] = dict(
            processes_config=processes_config,
            stop_timeout=self._stop_timeout,
            on_shutdown=self._on_shutdown,
            system_ready_event=self._system_ready_event,
            system_stop_event=self._system_stop_event,
        )
        if self._orchestrator_class_path is not None:
            spawner_kwargs["orchestrator_class_path"] = self._orchestrator_class_path
        if self._orchestrator_config:
            spawner_kwargs["orchestrator_config"] = self._orchestrator_config
        return ProcessSpawner(**spawner_kwargs)

    def _prepare_pid_registry(self) -> None:
        """Подготовить PID-реестр: зафиксировать путь в env (наследуется детьми через
        spawn) и реапнуть осиротевшие хвосты предыдущего запуска (если главный процесс
        был убит жёстко и finally→stop() не отработал).

        **Цена записи в env названа, а не забыта (Н-8, 2026-08-11).** Путь пишется в
        ОБЕ ручки пары и живёт в окружении процесса дольше самого лончера — снимать
        его тут некому: дети читают переменную всю свою жизнь. Значит ВТОРАЯ система,
        поднятая в том же процессе, унаследует чужой резолв, если сама не задаст ручки,
        и её реап убьёт живые процессы первой как «хвосты прошлого запуска». Ровно это
        стоило 11 красных тестов в `backend_ctl/tests`: сессионный стенд и стенд
        отдельного файла делили реестр, потому что задающий ставил лишь СЛАБУЮ ручку
        пары. Поднимаешь второй системный лончер в одном процессе — задай обе ручки
        (`MULTIPROCESS_PID_FILE` и `INSPECTOR_PID_FILE`) своим файлом; образец —
        `backend_ctl.harness.BackendHarness.start`.

        **Отказ реапа — громкий** (ревью Task 1.2, F8). Здесь стоял голый
        ``except: pass`` — тот же класс, что этот же коммит чинил строкой ниже, в
        уборке SHM, и на том же пути «до существования хоть одного процесса».
        Провалившийся реап означает выживших от прошлого запуска; проявится это
        позже, в другом месте и уже без причины. Отказ уходит в плоскость ошибок
        с трассой и растит ``pid_registry_failures`` (виден в
        ``get_stats()["startup"]``).
        """
        try:
            import os as _os

            from .pid_registry import pid_file_path, reap_and_reset

            # Фиксируем путь в env, чтобы все дочерние процессы писали в тот же файл.
            # Обе ручки пары: каноничная и легаси-алиас — дети могут читать любую.
            resolved = str(pid_file_path())
            _os.environ["MULTIPROCESS_PID_FILE"] = resolved
            _os.environ["INSPECTOR_PID_FILE"] = resolved
            reap_and_reset(log=self._log_info)
        except Exception as exc:  # noqa: BLE001 — реестр не критичен для запуска
            self._pid_registry_failures += 1
            self._log_error("реап PID-реестра не удался", exc)

    def _cleanup_shm_at_startup(self, processes_config: dict) -> None:
        """Очистка SHM перед стартом: config-объявленные имена + (Ф7 G.3c, за флагом)
        осиротевшие рантайм-слоты по префиксу (``output_frames`` выделяется лениво и
        в config-cleanup не попадает; после ``kill -9`` сегменты висят на POSIX).

        **Отказ уборки — громкий (Task 1.2, M14).** Раньше оба блока стояли под
        голым ``except: pass``: сегменты предыдущего запуска оставались висеть, и
        единственным следом этого был падающий позже старт с ``FileExistsError``
        в другом месте — то есть следствие без причины. Теперь отказ уходит в
        плоскость ошибок с трассой и растит ``shm_cleanup_failures``, а успех
        называет ЧИСЛО освобождённых сегментов (ноль тоже число: «висящих не
        было» — законный и полезный ответ).

        **Ноль бывает двух разных сортов, и вслух это говорит строка журнала**
        (ревью Task 1.2, F1). Там, где уборка возможна (POSIX), ноль означает
        «висящих не нашлось». На Windows висящих не бывает вовсе — ОС
        освобождает mapping при закрытии последнего handle, — и ноль там
        структурный, то есть про уборку не говорит НИЧЕГО. Строка дополняется
        пояснением (``_shm_platform_note``), иначе живой стенд читает свойство
        платформы как показание.

        **Число — про ПЕРВЫЙ блок** (config-объявленные имена). У второго,
        префиксного, своя строка и своё число; в ``shm_cleanup_segments`` оно не
        входит, потому что блоки отвечают на разные вопросы и складывать их
        значило бы получить величину, которую нельзя истолковать (F6).

        Уборка по-прежнему не имеет права сорвать запуск: исключение наружу не
        уходит ни из одного блока.
        """
        try:
            from ...shared_resources_module.memory.platform import cleanup_known_shm_at_startup

            cleaned = cleanup_known_shm_at_startup(processes_config)
            # isinstance, а не len() напрямую: функция подменяется заглушкой в
            # соседних тестах лаунчера, и заглушка возвращает не список. «Не
            # знаю сколько» честнее считать нулём, чем упасть на подсчёте.
            count = len(cleaned) if isinstance(cleaned, (list, tuple, set)) else 0
            self._shm_cleanup_segments = count
            self._log_info(f"cleanup_stale_shm: очищено {count} SHM-сегментов{_shm_platform_note()}")
        except Exception as exc:  # noqa: BLE001 — уборка не имеет права сорвать запуск
            self._shm_cleanup_failures += 1
            self._log_error("уборка объявленных SHM-сегментов не удалась", exc)
        try:
            from ...config_module.feature_flags import is_enabled

            if is_enabled("FW_SHM_PREFIX_CLEANUP"):
                from ...shared_resources_module.buffers import cleanup_orphaned_by_prefix

                # M8a: базовые имена config-объявленных memory-регионов ТОЖЕ годятся как
                # префиксы (owner_incarnation суффиксует их так же, как output_frames —
                # точный cleanup выше их не поймает). "output_frames" всегда в списке —
                # это лениво выделяемый слот пайплайна, в processes_config не объявлен
                # ни в каком виде (см. _DEFAULT_FRAME_SLOT_PREFIX).
                try:
                    from ...shared_resources_module.memory.platform import extract_memory_region_names

                    prefixes = extract_memory_region_names(processes_config)
                except Exception:
                    prefixes = []
                if _DEFAULT_FRAME_SLOT_PREFIX not in prefixes:
                    prefixes.append(_DEFAULT_FRAME_SLOT_PREFIX)
                orphaned = cleanup_orphaned_by_prefix(prefixes)
                self._log_info(
                    f"cleanup_orphaned_by_prefix: очищено {len(orphaned) if orphaned else 0} SHM-сегментов "
                    f"по префиксам {prefixes}"
                )
        except Exception as exc:  # noqa: BLE001 — уборка не имеет права сорвать запуск
            self._shm_cleanup_failures += 1
            self._log_error("уборка осиротевших SHM-сегментов по префиксу не удалась", exc)

    def run(self) -> None:
        """Запуск: launch_orchestrator + wait. Ctrl+C → stop."""
        self._prepare_pid_registry()
        processes_config = self._get_processes_config()
        self._cleanup_shm_at_startup(processes_config)
        self._spawner = self._create_spawner(processes_config)
        try:
            self._spawner.launch_orchestrator()
        except Exception:
            self.stop()
            raise
        self._log_info("ProcessManagerProcess started")
        self._log_info("System is running. Press Ctrl+C to stop.")
        try:
            # Цикл с коротким join — Windows не прерывает .join() по Ctrl+C.
            # Также наблюдаем ОБЩИЙ system_stop_event: любой процесс (GUI при
            # закрытии) взвёл его → выходим и зовём stop(), который force-terminate'ит
            # PM, даже если тот завис на non-daemon потоке (иначе is_running() остался
            # бы True вечно → подвисание при закрытии GUI).
            while self._spawner.is_running():
                if self._system_stop_event.is_set():
                    self._log_info("system_stop_event взведён — инициирую остановку системы")
                    break
                self._spawner.get_process().join(timeout=0.5)
        except KeyboardInterrupt:
            self._log_info("Ctrl+C received, stopping...")
        finally:
            self.stop()

    def start(self) -> None:
        """Запуск (если run() не используется)."""
        self._prepare_pid_registry()
        processes_config = self._get_processes_config()
        if not processes_config:
            raise RuntimeError("No processes. Use add_process() or pass config.")
        self._cleanup_shm_at_startup(processes_config)
        self._spawner = self._create_spawner(processes_config)
        self._spawner.launch_orchestrator()

    def wait_until_ready(self, timeout: float) -> bool:
        """
        Блокирующее ожидание полной готовности системы.

        Возвращает True, если ProcessManagerProcess завершил свой initialize()
        (все дочерние процессы spawned, запущены и ProcessMonitor стартовал)
        в течение timeout секунд.

        Возвращает False, если:
        - Истёк таймаут до получения сигнала готовности.
        - ProcessManagerProcess упал во время инициализации (spawner.is_running() == False).
        - start() не был вызван перед wait_until_ready().

        Уровень готовности: «minimum+» — все дочерние OS-процессы
        spawned и ProcessManager инициализирован. Дочерние процессы могут
        ещё выполнять свой initialize() на момент возврата True.

        Для гарантии «medium»-уровня (все дочерние прошли initialize())
        рекомендуется дождаться первого heartbeat от каждого — это вынесено
        в будущую задачу.

        Args:
            timeout: Максимальное время ожидания (секунды). Должен быть > 0.

        Returns:
            True если система готова, False если таймаут или ошибка.
        """
        if not self._spawner:
            self._log_warning("wait_until_ready: start() не был вызван")
            return False

        poll_interval = 0.05  # 50 мс — баланс между отзывчивостью и нагрузкой
        deadline = _time.monotonic() + timeout

        while _time.monotonic() < deadline:
            # Проверяем, не упал ли ProcessManagerProcess
            if not self._spawner.is_running():
                self._log_warning("wait_until_ready: ProcessManagerProcess завершился до сигнала готовности")
                return False

            # Проверяем event от ProcessManagerProcess
            if self._system_ready_event.is_set():
                self._log_info("Система готова (все процессы запущены)")
                return True

            # Ждём с коротким интервалом для быстрой реакции
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                break
            self._system_ready_event.wait(timeout=min(poll_interval, remaining))

        self._log_warning(f"wait_until_ready: таймаут {timeout}с истёк, система не готова")
        return False

    def stop(self) -> None:
        """Остановка системы."""
        if self._spawner:
            self._log_info("Stopping system...")
            self._spawner.stop()
            self._log_info("System stopped")
        # Штатная остановка отработала — чистим PID-реестр, чтобы следующий старт не
        # пытался реапнуть уже мёртвые PID.
        try:
            from .pid_registry import clear

            clear()
        except Exception as exc:  # noqa: BLE001 — чистка реестра не критична для остановки
            self._pid_registry_failures += 1
            self._log_error("чистка PID-реестра при остановке не удалась", exc)
        # Журнал лаунчера закрывается ПОСЛЕДНИМ: строки выше («Stopping system…»,
        # «System stopped») обязаны в него попасть. Страж — TestJournalClosesLast;
        # без него порядок держался лишь тем, что журнал воскресал (F3/F7).
        #
        # Названная граница: САМА ``clear()`` о своих отказах не рассказывает —
        # она глушит их внутри (``pid_registry.py``, ``except: pass`` вокруг
        # записи файла). Сюда долетают только отказы импорта и вызова, поэтому
        # «жалоб реестра» в этом журнале нет и обещать их нельзя.
        self._shutdown_observability()

    def wait(self) -> None:
        """Ожидание завершения."""
        if self._spawner:
            self._spawner.wait()

    def shutdown(self) -> None:
        """Алиас для stop()."""
        self.stop()

    def get_status(self) -> Dict[str, Any]:
        """Статус системы."""
        if not self._spawner:
            return {"spawner_running": False, "process": None}
        proc = self._spawner.get_process()
        status = {
            "spawner_running": self._spawner.is_running(),
            "process": {
                "name": proc.name if proc else None,
                "pid": proc.pid if proc and proc.is_alive() else None,
                "is_alive": proc.is_alive() if proc else False,
            }
            if proc
            else None,
        }
        if self._spawner.get_shared_resources():
            try:
                reg = self._spawner.get_shared_resources().process_state_registry
                status["registered_processes"] = reg.get_process_names()
            except Exception as e:
                self._log_warning(f"Failed to get process names: {e}")
        return status

    def _startup_stats(self) -> Dict[str, Any]:
        """Счётчики стартовой части лаунчера — ДО существования spawner'а (Task 1.2).

        Отдельной секцией и БЕЗУСЛОВНО: уборка SHM происходит раньше, чем
        появляется spawner, поэтому ранний выход ``if not self._spawner`` ниже
        сделал бы её счётчики недостижимыми ровно в тот момент, когда их и
        читают — сразу после отказа уборки.

        ``shm_cleanup_segments`` читается ПАРОЙ с ``shm_cleanup_failures``: три
        состояния, а не два (F6) — см. комментарий у поля в ``__init__``.
        """
        return {
            "shm_cleanup_failures": self._shm_cleanup_failures,
            "shm_cleanup_segments": self._shm_cleanup_segments,
            "pid_registry_failures": self._pid_registry_failures,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Статистика системы."""
        if not self._spawner:
            return {"spawner": {"is_running": False}, "startup": self._startup_stats()}
        return {
            "spawner": {
                "is_running": self._spawner.is_running(),
                "has_process": self._spawner.get_process() is not None,
            },
            "startup": self._startup_stats(),
            "shared_resources": (
                self._spawner.get_shared_resources().get_stats() if self._spawner.get_shared_resources() else {}
            ),
        }
