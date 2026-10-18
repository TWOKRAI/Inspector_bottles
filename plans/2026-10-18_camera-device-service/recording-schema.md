# Схема записи дерева узлов (`schema_version: 1`)

Часть плана [`plan.md`](plan.md). Фиксирует Task 0.4 (зонд MVS), принимает стадия 0 Task 1.5 (`from_recording`).
Источник — ревью плана р.2, `docs/reviews/2026-10-18_camera-plan-review.md` → «Раунд 2», раздел 3. Изменение — амендмент плюс правка зонда.

```json
{"schema_version": 1, "vendor": "mvs", "sdk_version": "0x04020003",
 "device": {"model": "<DeviceModelName>", "serial": "<DeviceSerialNumber>"},
 "states": ["idle", "grabbing"],
 "nodes": {
   "ExposureTime": {"type": "float", "min": 15.0, "max": 9999500.0, "inc": null, "entries": null,
                    "idle": {"value": 10000.0, "access": "RW", "rc": "0x00000000"},
                    "grabbing": {"value": 10000.0, "access": "RW", "rc": "0x00000000"}},
   "TriggerMode": {"type": "enum", "min": null, "max": null, "inc": null,
                   "entries": ["Off", "On"], "entry_values": [0, 1],
                   "idle": {"value": "Off", "access": "RW", "rc": "0x00000000"},
                   "grabbing": {"value": "Off", "access": "RW", "rc": "0x00000000"}}}}
```
- `type` ∈ `int|float|enum|bool|string|command` — по `MV_XML_GetNodeInterfaceType`; `access` ∈ `NI|NA|WO|RO|RW` — по `MV_XML_GetNodeAccessMode`, без префикса `AM_`.
- `min`/`max`/`inc` берутся в `idle`: int — из `MVCC_INTVALUE_EX` (`MV_CC_GetIntValueEx`; `GetIntValue` устаревший, `MvObsoleteInterfaces.h:502`); float — `min`/`max`, `inc: null`; остальные типы — `null`.
- `entries` — символьные имена (`MV_CC_GetEnumEntrySymbolic` по каждому `nSupportValue`), `entry_values` — параллельный список чисел; имя не получено -> `entries: null`, `entry_values` остаётся.
- `value`: enum — имя, bool — `true`/`false`; ошибка чтения -> `value: null` и код в `rc`; узла нет -> `access: "NI"`.
- `StartGrabbing` не прошёл -> `states: ["idle"]`, ключей `grabbing` нет.
- `--orig` — та же схема, `states: ["idle"]`, только узлы, которые опыт будет писать; `--restore` читает его тем же загрузчиком.
- Загрузчик 1.5 на неизвестный `schema_version` -> `ValueError`; текст называет ключ, значения в тексте нет.
