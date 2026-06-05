"""Тесты TelemetrySinkPlugin (SQLManager-реализация, 0 тестов до Task 3.1).

Стратегия (по образцу Plugins/io/database/tests):
  - in-memory SQLManager (StaticPool — данные живут в одном соединении),
    БЕЗ fork_safe: NullPool пересоздавал бы `:memory:` на каждом запросе.
  - mock PluginContext (MagicMock) — без реального worker_manager/state_proxy.
  - SQLManager внедряется ПОСЛЕ configure (как в проде — после fork в start()).

Покрытие: configure/register, schema/DDL, агрегация кэша подписки → строки,
команды flush/get_stats/purge_old, fork-safe конфиг в start(), гонка flush/worker.
"""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock, patch

from Plugins.io.telemetry_sink.plugin import TelemetrySinkPlugin
from Plugins.io.telemetry_sink.schemas import TelemetrySnapshot

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta

from Services.sql import SQLManager, SQLManagerConfig

# ---------------------------------------------------------------------------
# Вспомогательные фикстуры
# ---------------------------------------------------------------------------


def make_ctx(config: dict | None = None, *, state_proxy: object | None = None) -> MagicMock:
    """Создать mock PluginContext с заданным config.

    state_proxy=None → передаём в start() ветку no-op (подписка невозможна).
    По умолчанию для unit-тестов кэш заполняем напрямую через _on_deltas,
    поэтому реальный proxy не нужен.
    """
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.registers = None  # → _init_register берёт локальный register с defaults
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.state_proxy = state_proxy
    ctx.worker_manager.create_worker = MagicMock()
    return ctx


def make_sql() -> SQLManager:
    """Создать инициализированный in-memory SQLManager с таблицей telemetry_snapshots.

    fork_safe НЕ задаём: для `:memory:` фабрика выбирает StaticPool (одно
    соединение), иначе NullPool пересоздавал бы БД на каждом запросе.
    """
    sql = SQLManager(
        config=SQLManagerConfig(url="sqlite:///:memory:", dialect="sqlite"),
        managers={},
        process=None,
    )
    sql.initialize()
    sql.create_tables([TelemetrySnapshot])
    return sql


def make_plugin(config: dict | None = None) -> TelemetrySinkPlugin:
    """Создать сконфигурированный плагин с in-memory SQLManager.

    db_path по умолчанию переопределяем на `:memory:`-эквивалент через config,
    но configure всё равно делает mkdir(parent) — для in-memory pass-config
    с tmp-путём не нужен, mkdir('data') безвреден. Здесь оставляем default.
    """
    plugin = TelemetrySinkPlugin()
    ctx = make_ctx(config)
    plugin.configure(ctx)
    # Внедряем настоящий SQLManager после configure, до start (start делает fork-конфиг).
    plugin._sql = make_sql()
    return plugin


def count_rows(plugin: TelemetrySinkPlugin) -> int:
    """Подсчитать строки в telemetry_snapshots через SQLManager."""
    return plugin._sql.query("SELECT COUNT(*) AS c FROM telemetry_snapshots")[0]["c"]


def make_delta(path: str, new_value: object, *, delete: bool = False) -> Delta:
    """Удобный конструктор Delta для наполнения кэша подписки."""
    return Delta(
        path=path,
        old_value=MISSING,
        new_value=MISSING if delete else new_value,
        source="test",
    )


# ---------------------------------------------------------------------------
# TestConfigure — register parsing + период семпла
# ---------------------------------------------------------------------------


class TestConfigure:
    def test_configure_defaults(self):
        """Параметры по умолчанию парсятся корректно; SQLManager НЕ создан (fork)."""
        plugin = TelemetrySinkPlugin()
        ctx = make_ctx({})
        plugin.configure(ctx)

        assert plugin._reg.db_path == "data/telemetry.db"
        assert plugin._reg.sample_interval_sec == 5.0
        assert plugin._reg.retention_days == 0
        assert plugin._total_written == 0
        # SQLManager создаётся только в start() (fork-safety).
        assert plugin._sql is None
        assert plugin._sub_id is None

    def test_configure_custom_sample_interval(self):
        """Пользовательский период семпла и путь к БД принимаются (YAML override)."""
        plugin = TelemetrySinkPlugin()
        ctx = make_ctx({"sample_interval_sec": 1.5, "db_path": "/tmp/tele.db", "retention_days": 7})
        plugin.configure(ctx)

        assert plugin._reg.sample_interval_sec == 1.5
        assert plugin._reg.db_path == "/tmp/tele.db"
        assert plugin._reg.retention_days == 7


# ---------------------------------------------------------------------------
# TestSchema / DDL
# ---------------------------------------------------------------------------


class TestSchema:
    def test_create_tables_builds_telemetry_snapshots(self):
        """create_tables([TelemetrySnapshot]) создаёт таблицу telemetry_snapshots (auto-DDL)."""
        sql = make_sql()
        # Если таблицы нет — запрос упадёт; считаем успехом наличие 0 строк.
        rows = sql.query("SELECT COUNT(*) AS c FROM telemetry_snapshots")
        assert rows[0]["c"] == 0
        sql.shutdown()


# ---------------------------------------------------------------------------
# TestOnDeltas — кэш подписки (callback кладёт листья, delete убирает)
# ---------------------------------------------------------------------------


class TestOnDeltas:
    def test_deltas_fill_cache(self):
        """_on_deltas кладёт листья в кэш по path."""
        plugin = make_plugin()
        plugin._on_deltas(
            [
                make_delta("processes.cam.state.fps", 30.0),
                make_delta("processes.cam.state.status", "running"),
            ]
        )

        assert plugin._cache["processes.cam.state.fps"] == 30.0
        assert plugin._cache["processes.cam.state.status"] == "running"

    def test_delta_delete_removes_from_cache(self):
        """Дельта-удаление (new_value=MISSING) убирает лист из кэша."""
        plugin = make_plugin()
        plugin._on_deltas([make_delta("processes.cam.state.fps", 30.0)])
        plugin._on_deltas([make_delta("processes.cam.state.fps", None, delete=True)])

        assert "processes.cam.state.fps" not in plugin._cache

    def test_delta_update_overwrites(self):
        """Повторная дельта по тому же path перезаписывает значение."""
        plugin = make_plugin()
        plugin._on_deltas([make_delta("processes.cam.state.fps", 30.0)])
        plugin._on_deltas([make_delta("processes.cam.state.fps", 25.0)])

        assert plugin._cache["processes.cam.state.fps"] == 25.0


# ---------------------------------------------------------------------------
# TestSampleOnce — агрегация кэша → строки TelemetrySnapshot
# ---------------------------------------------------------------------------


class TestSampleOnce:
    def test_empty_cache_writes_nothing(self):
        """Пустой кэш → 0 строк, без пустых вставок."""
        plugin = make_plugin()
        written = plugin._sample_once()

        assert written == 0
        assert count_rows(plugin) == 0
        assert plugin._total_written == 0

    def test_proc_state_cols_to_columns(self):
        """Стандартные processes.<P>.state.<metric> → колонки строки процесса."""
        plugin = make_plugin()
        plugin._on_deltas(
            [
                make_delta("processes.cam.state.fps", 30.0),
                make_delta("processes.cam.state.latency_ms", 12.5),
                make_delta("processes.cam.state.uptime", 100.0),
                make_delta("processes.cam.state.status", "running"),
            ]
        )
        written = plugin._sample_once()

        assert written == 1
        assert plugin._total_written == 1
        row = plugin._sql.query("SELECT * FROM telemetry_snapshots WHERE process_name='cam'")[0]
        assert row["fps"] == 30.0
        assert row["latency_ms"] == 12.5
        assert row["uptime_s"] == 100.0  # uptime → колонка uptime_s
        assert row["status"] == "running"
        assert row["extra"] is None  # все листья стандартные → extra пуст

    def test_worker_leaves_go_to_extra_json(self):
        """Нестандартные листья (workers.*, неизвестный state) → extra JSON, не теряются."""
        plugin = make_plugin()
        plugin._on_deltas(
            [
                make_delta("processes.cam.state.fps", 30.0),
                make_delta("processes.cam.workers.w0.hz", 60.0),
                make_delta("processes.cam.state.custom_metric", 7),  # неизвестная state-метрика
            ]
        )
        plugin._sample_once()

        row = plugin._sql.query("SELECT * FROM telemetry_snapshots WHERE process_name='cam'")[0]
        assert row["fps"] == 30.0
        extra = json.loads(row["extra"])
        assert extra["workers.w0.hz"] == 60.0
        assert extra["state.custom_metric"] == 7

    def test_system_health_summary_row(self):
        """system.health.* → отдельная строка process_name='system' (fps←avg_fps)."""
        plugin = make_plugin()
        plugin._on_deltas(
            [
                make_delta("system.health.avg_fps", 28.0),
                make_delta("system.health.active", 6),
                make_delta("system.health.broken_wires", 0),
            ]
        )
        plugin._sample_once()

        row = plugin._sql.query("SELECT * FROM telemetry_snapshots WHERE process_name='system'")[0]
        assert row["fps"] == 28.0  # avg_fps → колонка fps
        extra = json.loads(row["extra"])
        assert extra["active"] == 6
        assert extra["broken_wires"] == 0
        assert "avg_fps" not in extra  # avg_fps ушёл в колонку, не дублируется в extra

    def test_one_row_per_process(self):
        """Несколько процессов + system → строка на каждого."""
        plugin = make_plugin()
        plugin._on_deltas(
            [
                make_delta("processes.cam.state.fps", 30.0),
                make_delta("processes.proc2.state.fps", 15.0),
                make_delta("system.health.avg_fps", 22.0),
            ]
        )
        written = plugin._sample_once()

        assert written == 3
        assert count_rows(plugin) == 3
        names = {r["process_name"] for r in plugin._sql.query("SELECT process_name FROM telemetry_snapshots")}
        assert names == {"cam", "proc2", "system"}

    def test_non_numeric_metric_becomes_null(self):
        """Нечисловое значение fps → колонка NULL (через _as_float)."""
        plugin = make_plugin()
        plugin._on_deltas(
            [
                make_delta("processes.cam.state.fps", "N/A"),
                make_delta("processes.cam.state.status", "running"),
            ]
        )
        plugin._sample_once()

        row = plugin._sql.query("SELECT * FROM telemetry_snapshots WHERE process_name='cam'")[0]
        assert row["fps"] is None
        assert row["status"] == "running"

    def test_static_sections_ignored(self):
        """config.* и нетелеметрийные system.* листья не дают строк."""
        plugin = make_plugin()
        plugin._on_deltas(
            [
                make_delta("processes.cam.config.db_path", "x.db"),
                make_delta("system.stop_timeout", 5.0),
                make_delta("system.log_dir", "/logs"),
            ]
        )
        written = plugin._sample_once()

        assert written == 0
        assert count_rows(plugin) == 0

    def test_sample_updates_last_ts(self):
        """Успешный семпл обновляет _last_ts (для get_stats)."""
        plugin = make_plugin()
        plugin._on_deltas([make_delta("processes.cam.state.fps", 30.0)])
        before = time.time()
        plugin._sample_once()
        after = time.time()

        assert before <= plugin._last_ts <= after


# ---------------------------------------------------------------------------
# TestCommands — flush / get_stats / purge_old
# ---------------------------------------------------------------------------


class TestCommands:
    def test_cmd_flush(self):
        """Команда flush семплит прямо сейчас и возвращает счётчики."""
        plugin = make_plugin()
        plugin._on_deltas([make_delta("processes.cam.state.fps", 30.0)])
        result = plugin._cmd_flush({})

        assert result["status"] == "ok"
        assert result["written"] == 1
        assert result["total_written"] == 1
        assert count_rows(plugin) == 1

    def test_cmd_get_stats(self):
        """get_stats отдаёт total_written, pending_leaves, db_path, last_ts."""
        plugin = make_plugin()
        plugin._on_deltas(
            [
                make_delta("processes.cam.state.fps", 30.0),
                make_delta("processes.cam.state.status", "running"),
            ]
        )
        result = plugin._cmd_get_stats({})

        assert result["status"] == "ok"
        assert result["total_written"] == 0  # ещё не семплили
        assert result["pending_leaves"] == 2  # два листа в кэше
        assert result["db_path"] == plugin._reg.db_path
        assert result["last_ts"] == 0.0

    def test_cmd_purge_old_disabled_by_default(self):
        """retention_days=0 → purge_old no-op (ретенция выключена)."""
        plugin = make_plugin()
        result = plugin._cmd_purge_old({})

        assert result["status"] == "ok"
        assert result["purged"] == 0

    def test_cmd_purge_old_invalid_arg(self):
        """Нечисловой retention_days → status=error."""
        plugin = make_plugin()
        result = plugin._cmd_purge_old({"retention_days": "abc"})

        assert result["status"] == "error"
        assert "retention_days" in result["error"]

    def test_cmd_purge_old_deletes_stale_rows(self):
        """purge_old с retention_days удаляет строки старше cutoff, свежие оставляет."""
        plugin = make_plugin()
        now = time.time()
        repo = plugin._sql.get_repository(TelemetrySnapshot)
        repo.insert_many(
            [
                TelemetrySnapshot(ts=now - 10 * 86400, process_name="old"),  # 10 дней назад
                TelemetrySnapshot(ts=now, process_name="fresh"),  # сейчас
            ]
        )

        result = plugin._cmd_purge_old({"retention_days": 7})

        assert result["status"] == "ok"
        assert result["purged"] == 1
        remaining = {r["process_name"] for r in plugin._sql.query("SELECT process_name FROM telemetry_snapshots")}
        assert remaining == {"fresh"}


# ---------------------------------------------------------------------------
# TestStartForkSafe — конфиг SQLManager в start() (fork_safe → NullPool)
# ---------------------------------------------------------------------------


class TestStartForkSafe:
    def test_start_builds_fork_safe_config(self):
        """start() создаёт SQLManager с fork_safe=True + check_same_thread=False (после fork)."""
        plugin = TelemetrySinkPlugin()
        ctx = make_ctx({"db_path": "data/telemetry.db"}, state_proxy=MagicMock())
        plugin.configure(ctx)

        with patch("Plugins.io.telemetry_sink.plugin.SQLManager") as sql_cls:
            plugin.start(ctx)

        # SQLManager создан с fork-safe конфигом.
        _, kwargs = sql_cls.call_args
        config = kwargs["config"]
        assert config.fork_safe is True  # NullPool после fork — обязательно
        assert config.dialect == "sqlite"
        assert config.connect_args == {"check_same_thread": False}
        assert "data/telemetry.db" in config.url
        # initialize + create_tables вызваны на инстансе.
        sql_cls.return_value.initialize.assert_called_once()
        sql_cls.return_value.create_tables.assert_called_once_with([TelemetrySnapshot])

    def test_start_subscribes_processes_and_system(self):
        """start() подписывается на processes.** и system.** + создаёт sample-worker."""
        plugin = TelemetrySinkPlugin()
        proxy = MagicMock()
        proxy.subscribe.side_effect = ["sub-proc", "sub-sys"]
        ctx = make_ctx({}, state_proxy=proxy)
        plugin.configure(ctx)

        with patch("Plugins.io.telemetry_sink.plugin.SQLManager"):
            plugin.start(ctx)

        subscribed = {c.args[0] for c in proxy.subscribe.call_args_list}
        assert subscribed == {"processes.**", "system.**"}
        assert plugin._sub_id == "sub-proc"
        assert plugin._sub_id_system == "sub-sys"
        ctx.worker_manager.create_worker.assert_called_once()
        assert ctx.worker_manager.create_worker.call_args.args[0] == "telemetry_sample_worker"

    def test_start_without_state_proxy_is_no_op(self):
        """state_proxy=None → ошибка логируется, подписки нет, но плагин не падает."""
        plugin = TelemetrySinkPlugin()
        ctx = make_ctx({}, state_proxy=None)
        plugin.configure(ctx)

        with patch("Plugins.io.telemetry_sink.plugin.SQLManager"):
            plugin.start(ctx)

        assert plugin._sub_id is None
        ctx.log_error.assert_called_once()
        # Worker всё равно создаётся (БД создана, просто кэш пуст).
        ctx.worker_manager.create_worker.assert_called_once()


# ---------------------------------------------------------------------------
# TestWriteRace — _write_lock сериализует семплы (worker vs flush)
# ---------------------------------------------------------------------------


class TestWriteRace:
    def test_concurrent_samples_do_not_lose_increment(self, tmp_path):
        """N потоков _sample_once → total_written и число строк согласованы (без потерь).

        _write_lock защищает read-modify-write счётчика _total_written: без него
        параллельные семплы теряли бы инкременты. Кэш = 1 процесс → 1 строка/семпл,
        значит после N семплов ровно N строк и total_written==N.

        БД файловая (не `:memory:`): несколько потоков = несколько соединений,
        которым нужна общая видимая таблица; StaticPool `:memory:` делит одно
        соединение и под потоками теряет схему.
        """
        plugin = TelemetrySinkPlugin()
        plugin.configure(make_ctx({}))
        db_file = tmp_path / "race.db"
        sql = SQLManager(
            config=SQLManagerConfig(
                url=f"sqlite:///{db_file}",
                dialect="sqlite",
                connect_args={"check_same_thread": False},
            ),
            managers={},
            process=None,
        )
        sql.initialize()
        sql.create_tables([TelemetrySnapshot])
        plugin._sql = sql
        plugin._on_deltas([make_delta("processes.cam.state.fps", 30.0)])

        n = 20
        barrier = threading.Barrier(n)

        def worker():
            barrier.wait()  # максимизируем шанс гонки — стартуем одновременно
            plugin._sample_once()

        threads = [threading.Thread(target=worker) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert plugin._total_written == n
        assert count_rows(plugin) == n
