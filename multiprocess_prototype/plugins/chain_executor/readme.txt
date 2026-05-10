ChainExecutorPlugin — последовательное/параллельное выполнение цепочки плагинов

Category: processing
Inputs:   frame (image/bgr) — входные данные
Outputs:  frame (image/bgr) — обработанные данные

Описание:
  Управляет цепочкой sub-plugins. Каждый шаг = экземпляр другого плагина.
  Последовательный режим: items прогоняются через каждый шаг по порядку.
  Параллельный режим: каждый шаг получает копию items, результаты мержатся.

  НЕ использует @for_each — работает с batch list[dict].

Команды:
  - add_step        — добавить шаг (plugin_class + plugin_name + config)
  - remove_step     — удалить шаг по имени
  - reorder_steps   — переупорядочить шаги (order: list[str])
  - get_steps       — получить список шагов

Config:
  - steps (list[dict], []) — начальные шаги
      каждый шаг: {"plugin_class": "full.path.Plugin", "plugin_name": "step_name", "config": {...}}
  - parallel (bool, False) — параллельный режим
  - max_workers (int, 4) — потоков для параллельного режима
  - on_error (str, "skip") — реакция на ошибку в шаге
      "skip" — продолжить с текущими items
      "fail" — остановить цепочку

Зависимости: нет (только stdlib: importlib, concurrent.futures, copy)
Справочник v1: multiprocess_prototype/services/processor/service.py (chain runnables)
