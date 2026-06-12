# devices_common — GUI-компоненты управления устройствами

Переиспользуемые виджеты вкладки «Сервисы» для работы с устройствами реестра
(робот, ПЧ, камеры). Реестр живёт в always-on процессе `devices` (DeviceHubPlugin);
эти компоненты — UI поверх него.

## Источник истины — активный рецепт

Решение владельца (план `device-tree-recipe`): набор зарегистрированных устройств
хранится в top-level секции `devices:` YAML **активного рецепта**. Процесс `devices`
(hub) — runtime-отражение рецепта.

```
рецепт (devices:) ──истина──►  GUI (RecipeDevicesStore)
       ▲                              │ CRUD
       │ device_sync_set              ▼
   активация ◄──── hub (runtime, conn/телеметрия) ────► device_connect/...
```

- **`RecipeDevicesStore`** (`recipe_devices.py`) — чистый (без Qt) CRUD устройств в
  секции `devices:` через `read_raw`/`save_raw` (ruamel round-trip, комментарии
  сохраняются). Нет активного рецепта → `list()` пуст, `upsert/remove` →
  `RecipeDevicesError`.
- Активация рецепта зовёт hub-команду `device_sync_set` (идемпотентно: upsert набора
  + удаление чужих `recipe:*`-устройств; manual-устройства не трогаются).

## Master-detail (две колонки внутри страницы сервиса)

Навигация первой колонки («Сервисы») не меняется. Внутри страницы сервиса —
master-detail:

- **`DeviceListPanel`** (master) — список устройств данного `kind` из рецепта +
  conn-индикатор (`●/◌/○/✕` по `devices.state.<id>.conn`); последняя строка всегда
  **«+ Добавить устройство»**. Сигналы `device_selected(id)` / `add_requested()`.
- **`DeviceMasterDetail`** — слева `DeviceListPanel`, справа `QStackedWidget`:
  заглушка → lazy-страницы устройств (`DeviceDetailPage`) → страница добавления
  (`AddDevicePage`).
- **`DeviceDetailPage`** — шапка (имя + conn + Подключить/Отключить/Изменить/Удалить)
  над существующими контролами устройства; `controller.set_device(id)`.

Секции `robot/` и `vfd/` собирают страницу через `DeviceMasterDetail`
(device_page_factory строит контролы per device_id). Камеры (`hikvision/`) — пока на
старом комбо (миграция отложена: нужен `set_device` по serial/index).

## CRUD-поток (рецепт → hub → refresh)

`DeviceCrudActions` (`crud_actions.py`) — add/edit/remove:
1. персист в рецепт (`RecipeDevicesStore`, истина);
2. отражение в hub (`device_upsert/remove`, origin `recipe:<slug>`);
3. `refresh()` списка. Ошибка hub НЕ откатывает рецепт (hub догонит при активации).

## Добавление с пробным подключением

`AddDevicePage` (`add_page.py`) — решение владельца «подключиться → статус → добавить»:

1. ввод параметров (общая `DeviceFormWidget`, она же в `DeviceEditorDialog`);
2. **«Проверить связь»** — пробный `device_upsert(origin=probe)` + `connect` в hub
   (НЕ в рецепт) → live-статус conn;
3. **«Добавить»** — персист в рецепт + re-tag `origin=recipe:<slug>` (устройство уже
   подключено);
4. **«Отмена»/уход** — пробное устройство удаляется из hub.

Нет активного рецепта → форма заблокирована с подсказкой.

> **ПЧ через робота (bridge):** «Проверить связь» для ПЧ резолвит транспорт
> робота-носителя — робот должен быть подключён первым; иначе ПЧ покажет `error` и
> сам поднимется, когда робот появится (НР-2 авто-reconnect).

## Файлы

| Файл | Назначение |
|------|-----------|
| `recipe_devices.py` | RecipeDevicesStore — устройства в рецепте (без Qt) |
| `device_list_panel.py` | DeviceListPanel — список устройств + «+ Добавить» |
| `master_detail.py` | DeviceMasterDetail + DeviceDetailPage |
| `add_page.py` | AddDevicePage — добавление с пробным подключением |
| `device_form.py` | DeviceFormWidget — общая форма полей (dialog + add-page) |
| `editor_dialog.py` | DeviceEditorDialog — модальный диалог (Изменить) |
| `crud_actions.py` | DeviceCrudActions — CRUD-поток рецепт→hub |
| `presenter.py` | DevicesPresenter — IPC к процессу `devices` |
| `combo.py` | DeviceComboController — legacy комбо (только hikvision, до миграции) |

Refs: `plans/device-tree-recipe.md`
