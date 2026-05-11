# channel_map

AST-сканер IPC-каналов и адресации сообщений в проекте.

## Что находит

- **Декларации каналов** — вызовы конструкторов из `detect.channel_constructors` (по умолчанию `FieldRouting`) с kwarg `channel="..."`.
- **Отправки** — вызовы методов из `detect.send_methods` (по умолчанию `send_message`); извлекает первый positional или kwarg `target=`/`targets=`.
- **Подписки** — вызовы методов из `detect.subscribe_methods` (по умолчанию пусто; добавь свои, например `subscribe`, `on_channel`, `register_handler`).

Литералы извлекаются точно. Динамические строки (переменные, выражения) попадают как `?` — это сигнал «здесь канал/таргет не виден статически».

## Запуск

```bash
python scripts/channel_map/channel_map.py
python scripts/channel_map/channel_map.py --group-by file --format json
python scripts/channel_map/channel_map.py --root multiprocess_framework --limit 10
```

## Колонки

- `group` — модуль / файл / роль (зависит от `group_by`)
- `files` — сколько файлов в группе содержат находки
- `decl` — уникальных каналов задекларировано
- `sends` — уникальных таргетов в `send_message`
- `subs` — уникальных каналов в подписчиках
- `channels` — превью имён (первые 6, дальше `(+N)`)

## Когда полезно

- Перед рефакторингом роутинга: проверить, что переименование канала не разорвёт пары declaration↔send.
- Аудит после правок: `--format json` + diff между ветками.
- Поиск «висящих» отправок (`send` без соответствующей `declaration`).

## Ограничения

- Только статический AST — не видит `getattr`, `**kwargs`, channels-как-переменные.
- Не отслеживает поток управления (кто кому фактически отправляет в рантайме).
- Для динамических кейсов всегда смотри `?` в выводе и проверяй вручную.
