# framework_minimal_prototype\backend\processes\counter_process.py
"""Один простой процесс: счёт 1..10 с интервалом 1 с (отладка жизненного цикла фреймворка)."""

from __future__ import annotations

import time

from multiprocess_framework.modules.process_module import ProcessModule


class CounterProcess(ProcessModule):
    """После initialize() раннер вызывает run(); по завершении — stop_process для выхода из цикла."""

    def run(self) -> None:
        super().run()
        for i in range(1, 11):
            if self.should_stop():
                break
            print(f"[{self.name}] {i}", flush=True)
            time.sleep(1)
        self.stop_process = True
