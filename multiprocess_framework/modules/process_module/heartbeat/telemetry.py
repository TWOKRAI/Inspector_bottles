"""Сборка телеметрии процесса в один merge-payload (E6/Task 5.7).

Раньше ``ProcessHeartbeat._publish_metrics_to_tree`` слал **3W+2** отдельных
``proxy.set`` (по 3 на воркер + 2 агрегатных) — каждый ``set`` = отдельное
IPC-сообщение в StateStoreManager. Этот helper собирает те же листья в один
вложенный dict под общим префиксом ``processes.<name>`` → публикатор шлёт **один**
``proxy.merge`` (глубокий merge сохраняет сиблинги ``health.*`` и пр.), снижая
число телеметрийных сообщений ~в W раз.

Чистая функция (helper, не mixin — сегодня единственный потребитель heartbeat):
тестируется без Qt/IPC, публикатор остаётся тонким.
"""

from __future__ import annotations


def build_worker_telemetry(workers: dict, name: str) -> tuple[str, dict] | None:
    """Собрать (path, merge_data) телеметрии процесса из снимка воркеров.

    Формирует те же листья, что раньше писались россыпью ``proxy.set``, но как
    один вложенный dict для ``proxy.merge(path, data)``:

        path = f"processes.{name}"
        data = {
            "workers": {wname: {"status", "effective_hz"?, "cycle_duration_ms"?}, ...},
            "state":   {"fps", "latency_ms"?},   # агрегат, только при наличии hz>0
        }

    Правила (паритет с прежней логикой):
      - per-worker: ``status`` — всегда (если не None); ``effective_hz`` — при hz>0;
        ``cycle_duration_ms`` — при lat>0; воркер без единого поля не попадает в payload;
      - агрегат ``state``: ``fps`` = max(hz) по running-воркерам с hz>0;
        ``latency_ms`` = max(cycle_duration_ms) среди них (если есть); нет hz>0 → без агрегата;
      - округление до 1 знака сохранено (fps/hz/latency).

    Args:
        workers: снимок ``get_all_workers_status()`` (dict wname -> статус-dict).
        name:    имя процесса-владельца (префикс пути в дереве).

    Returns:
        ``(path, data)`` для ``proxy.merge`` — ЛИБО ``None``, если публиковать нечего
        (пустой снимок / ни одного воркера с полями и без агрегата).

    Pre:
        - ``workers`` — mapping; нестандартные значения (не dict) пропускаются.
    Post:
        - чистая функция: ``workers`` не мутируется;
        - если результат не None — ``data`` непустой (нет пустого merge-сообщения);
        - листья идентичны прежнему набору ``set``-путей (паритет).
    """
    raise NotImplementedError


__all__ = ["build_worker_telemetry"]
