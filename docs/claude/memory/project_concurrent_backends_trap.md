---
name: concurrent-backends-shared-resources-trap
description: "Два бэкенда в одном тест-прогоне конфликтуют через глобальные ресурсы — PID-реестр (исправлено в harness, Ф1.9) и SHM-cleanup при старте (латентно)"
metadata: 
  node_type: memory
  type: project
  originSessionId: b684f924-d860-4625-928f-7923c5c9b43f
---

`SystemLauncher.start()` рассчитан на «одна система на машину»: (1) `reap_and_reset` PID-реестра
(`inspector_system_pids.jsonl` в temp) убивает все живые PID из общего файла — второй бэкенд при
старте прибивал процессы живого первого; (2) `cleanup_known_shm_at_startup` чистит SHM-сегменты
по именам из конфига — при одинаковой топологии второй старт может снести SHM живого первого.

**Исправлено (Ф1.9, cb77ed26):** BackendHarness ставит свой `INSPECTOR_PID_FILE` на инстанс
(pid+port) и удаляет его в stop(). Ловушка вскрылась порядком тестов: session-фикстура
`headless_backend` создаётся ПЕРВЫМ файлом, который её просит — новый тест-файл алфавитно
раньше `test_harness` меняет порядок, и `test_harness` поднимал свои бэкенды при живом session.

**Латентно:** SHM-конфликт не исправлен (сейчас live-тесты только интроспектируют — не ловят).
Если появятся frame/SHM live-тесты при двух бэкендах — вернуться сюда.

**Третье проявление (Ф1.7, e4f787a0):** `BackendHarness.start()` мутирует общий
`os.environ["BACKEND_CTL_PORT"]` — после `test_harness` (порты 8766/8767) env указывает на
погашенный бэкенд. Live-тест MCP-сервера (subprocess читает env) падал только в полном прогоне.
Фикс: порт для subprocess/подключений брать ЯВНО из объекта фикстуры (`driver._port`), не из env.

**How to apply:** новый live-тест с собственным harness при живой session-фикстуре — проверять
уникальность порта И что не появилось новых глобальных ресурсов (PID-файл, SHM, лог-пути,
env: BACKEND_CTL_PORT/INSPECTOR_PID_FILE мутируются каждым harness.start()).
Связь: [[feedback-backend-ctl-for-agents]].
