# multiprocess_prototype\processes\database_process.py
"""
DatabaseProcess — процесс с SQLManager.

Регистрирует команды db.query, db.execute, db.insert для доступа к БД
через CommandManager и Router. Опциональный процесс — добавить в main.py
при необходимости.
"""
from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.sql_module import SQLManager, SQLManagerConfig


class DatabaseProcess(ProcessModule):
    """Процесс с SQLManager. Доступ к БД через команды db.query, db.execute, db.insert."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sql_manager = None

    def _init_custom_managers(self):
        """Создать SQLManager и зарегистрировать команды."""
        app_cfg = self.get_config("config") or {}
        db_url = app_cfg.get("db_url", "sqlite:///./inspector.db")
        db_dialect = app_cfg.get("db_dialect", "sqlite")

        sql_config = SQLManagerConfig(
            url=db_url,
            dialect=db_dialect,
            mode="sync",
            fork_safe=True,
        )
        managers = {}
        if self.logger_manager:
            managers["logger"] = self.logger_manager
        if getattr(self, "error_manager", None):
            managers["errors"] = self.error_manager
        if getattr(self, "stats_manager", None):
            managers["stats"] = self.stats_manager

        self.sql_manager = SQLManager(
            config=sql_config,
            managers=managers,
            process=self,
        )
        self.sql_manager.initialize()
        self.register_manager("sql", self.sql_manager, enabled=True)

        self.command_manager.register_command(
            "db.query",
            lambda msg: self.sql_manager.execute_command(msg),
        )
        self.command_manager.register_command(
            "db.execute",
            lambda msg: self.sql_manager.execute_command(msg),
        )
        self.command_manager.register_command(
            "db.insert",
            lambda msg: self.sql_manager.execute_command(msg),
        )

        self._log_info("DatabaseProcess: SQLManager ready, commands db.query/execute/insert registered")

    def shutdown(self) -> bool:
        """Завершение с освобождением SQLManager."""
        if self.sql_manager:
            try:
                self.sql_manager.shutdown()
            except Exception as e:
                self._log_error(f"SQLManager shutdown error: {e}")
        return super().shutdown()
