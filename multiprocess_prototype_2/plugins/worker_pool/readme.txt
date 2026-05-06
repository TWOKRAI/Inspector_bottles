WorkerPoolPlugin — параллельная обработка items через пул потоков

Category: processing
Inputs:   frame (image/bgr) — входные данные
Outputs:  frame (image/bgr) — обработанные данные

Описание:
  Распределяет items по пулу потоков для параллельной обработки.
  Каждый worker = экземпляр sub-plugin (указывается в config).
  Изоляция по потокам: каждый worker имеет свой экземпляр — thread safety.
  Порядок results соответствует порядку входных items.
  При ошибке в worker — fallback на оригинальный item.
  Стратегии: round-robin (default), shortest-queue (fallback к positional).

Команды:
  - resize_pool    — изменить размер пула (pool_size: int, 1..32)
  - get_stats      — статистика обработки (processed, errors, workers_count)

Config:
  - pool_size (int, 4)          — количество worker потоков
  - queue_timeout (float, 5.0)  — timeout ожидания результата (секунды)
  - balancing (str, "round_robin") — стратегия распределения items
  - worker_plugin_class (str)   — полный путь к классу sub-plugin
  - worker_plugin_config (dict) — конфиг sub-plugin (передаётся как ctx.config)

Зависимости: нет (только stdlib: concurrent.futures, threading, importlib)

Пример конфига:
  worker_plugin_class: "multiprocess_prototype_2.plugins.grayscale.plugin.GrayscalePlugin"
  worker_plugin_config: {}
  pool_size: 4
  balancing: "round_robin"

Справочник v1: multiprocess_prototype/plugins/services/processor_worker/
