# Ревью волны W1a (Tasks 0.2, 0.3, 0.4) — camera-device-service

- **Ревьюер:** `reviewer` (opus), 182k токенов, 29 вызовов. Только чтение.
- **SHA:** `34cd203b1`, дифф `5538a617d..34cd203b1`, ветка `feat/camera-device-service`.
- **Скрипты ревьюера:** scratchpad сессии `inspector-bottles-53`, `w1a/layout_conv.py`, `cfake.py` (фейк на уровне C: настоящие ctypes-функции за настоящими обёртками), `misc.py`, `nullcb.py`.

## Раунд 1 — CHANGES REQUESTED (итерация 1 из 2)

### Подтверждено запуском

- `pytest Services/hikvision_camera/tests -q` -> `212 passed`.
- Раскладки: `MVCC_ENUMENTRY` 84 Б (смещения 0/4/68), `MVCC_INTVALUE_EX` 96 Б (0/8/16/24/32); старые `MVCC_ENUMVALUE` 280, `MVCC_INTVALUE` 32, `MVCC_FLOATVALUE` 28 (float32), `MVCC_STRINGVALUE` 272 — совпадают с `CameraParams.h`, `#pragma pack` нет.
- `cfake.py`: `read_node` enum/float/bool/string/int/отсутствующий узел, `--dump`, h1, h5, h2 split через настоящие ctypes -> `bad handles: []`; dump -> `sets []`; h1 -> `SetEnum TriggerMode 1`, затем `0`, exit 0; h5 -> `node=Width rc=0x80000106 read=2448`, exit 0.
- `--orig` до первого `Set`, возврат после `StopGrabbing`, `RESTORE MISMATCH` -> exit 2; `lifecycle_guards check` — новых по `mvs_probe.py` нет; `ruff` чисто; `secrets_audit` -> 0; сигнатура `open` не менялась (`camera.py:99`).

### Находки

| № | Тяжесть | Где | Вход -> наблюдение | Решение лидера |
|---|---|---|---|---|
| 1 | blocker | `mvs_probe.py:714`, `:588-591` | камера в `On`, `o.json` = `Off`; повтор `h1 --write --orig o.json` -> `rerun exit 0 orig now On final On` — исходное потеряно | исправить: `--orig` существует -> отказ, код 1 |
| 2 | blocker | `mvs_probe.py:683-688`, `:594-601`, `:827-836` | `--restore d.json` (файл `--dump`) -> `exit 2 n_sets 13` — записаны 13 узлов без `--write`; серийник не сверяется | исправить: `--restore` требует `--write`; отказ (код 1, ни одного `Set`), если `states != ["idle"]`, узлы вне набора опытов или `device.serial` ≠ серийника камеры |
| 3 | blocker | `bindings.py:571-574` | `register(cb)`, `register(None)` -> `ArgumentError … expected WinFunctionType`, ссылка уже снята -> колбэк в SDK на освобождённой памяти | исправить: `None` -> `EXCEPTION_CALLBACK()` (NULL); прежнюю ссылку снимать только после `rc == 0` |
| 4 | major | `mvs_probe.py:638-654`, `:66`, `:756-765` | `--seconds 30 --delay 31` > `THREAD_JOIN_S = 60`; в масштабе -> `поток B-capture не завершился`, `finish()` при живом потоке; гонка `finish()` без lock — подозрение | исправить: потолок `join` из `seconds + delay` + запас; lock в `finish()`; флаг отмены перед каждым вызовом SDK в фазах |
| 5 | minor | `camera.py:354` | `Mono12Packed` 4×2 12 Б -> `(2, 4)` мусор; `Mono12` 16 Б -> `None` | отложено: путь кадра заменяется в 4.2a (биты из `(pixel_type >> 16) & 0xFF`) |
| 6 | minor, совет | `mvs_probe.py:543-549` | точное сравнение float при возврате | снимается правкой 2 (возврат только узлов опытов: int/enum) |
| 7 | minor, совет | `mvs_probe.py:756-765` | `KeyboardInterrupt` в `restore_nodes` пропускает `close_camera` | исправить: `try/finally` в `finish()` |
| 8 | minor | `mvs_probe.py:465` | `IRegister/ICategory/IValue/IBase` -> `type: null` | внесено в `recording-schema.md` (лидер) |
| 9 | minor, совет | `plugin.py:241`, `:244` | `float()` нечислового значения рецепта -> исключение из `_do_start_capture` | исправить: `{"status": "error"}` с текстом |

### Вне волны

- `Services/device_hub/drivers/hikvision_driver.py:77`: `open(self._serial)` — строка вместо индекса, результат не проверяется (4.6b).
- `bindings.py:583-585`: `GetOptimalPacketSize` с `restype c_uint` делает отрицательный код большим положительным; `camera.py:171` пропускает его в `SetIntValue` (теперь виден в `param_errors`).
- Старые обёртки: опечатка `.argtype` (`bindings.py:175` и далее).
- G6 `thread_split_probe.py:210` — C-8 координатора.

### Открыто (ревьюер)

Ничего на приборе; фейк уровня C доказывает только слой ctypes. Реальная DLL с NULL-хендлом не вызывалась. Ctrl+C в split не воспроизводился. `sentrux check .` не запускался. Инъекции по 0.2/0.3 не повторялись.
