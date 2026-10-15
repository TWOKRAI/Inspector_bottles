---
name: reference_idmvs_gev_reader_needs_encryption_key
description: "IDMVS не показывает считыватель ID3000/ID5000 с Manufacturer=GEV при живой сети: пустой vplicense/encryption.key; CheckEnabledSerial NG, CheckDeviceRegion filtered; ForceIp без перезапуска питания зависает"
module: code_reader
mechanism: [live-stand, sdk]
metadata:
  type: reference
---

**Симптом:** IDMVS (5.1.0, `IDMVSSTD`) показывает пустой `GigE`, хотя камера на линке, пингуется, а MvCodeReader SDK её находит и отдаёт кадры (`Services/code_reader/tools/mvcr_probe.py`). Общий MVS-SDK (`id3000_discover.py`, `MV_CC_EnumDevices`) на таком приборе даёт 0 устройств — это не признак поломки.

**Причина (подтверждено 2026-10-15):** у прибора `Manufacturer = GEV` (не `Hikrobot`), прошивка `V4.0.2.R`. IDMVS для таких проверяет серийник по `C:\Program Files (x86)\IDMVSSTD\Applications\common\vplicense\encryption.key`; файл был 0 байт. В `C:\Users\<user>\IDMVSSTD\Log\Client.log` — `CheckEnabledSerial: Check NG: <serial>`, затем `CheckDeviceRegion ... filtered 2`. У приборов с `Hikrobot` этих строк нет. Лечение — положить рабочий `encryption.key` от поставщика/производителя (7568 байт), перезапустить IDMVS. Прежний файл — в `encryption.key.bak`. Для прошивки `V3.2.2.R` производитель советует другое: IDMVS 4.2 (ставить его поверх опасно — перезапишет `MvCodeReaderCtrl.dll`, который грузит `Services/code_reader`).

**Ловушки по дороге:**
- Advanced IP Scanner показал ложный `169.254.13.255`; настоящий адрес — из `arp -a` по MAC прибора или `mvcr_probe.py`. Адрес LLA `169.254.x.x` меняется на каждом старте.
- `MV_CODEREADER_GIGE_ForceIp` вернул `0x80020204`, обнаружение показало новый IP, но ARP/пинг/`OpenDevice` (`0x80020206`) молчали, пока не выключили питание прибора. После `ForceIp` сразу перезапускать питание.
- Диагностика IDMVS — по логу `Client.log`, не по гаданию про подсети.

**How to apply:** «IDMVS не видит» при живом линке → сначала `mvcr_probe.py`; нашёл — смотреть `Client.log` на `CheckEnabledSerial` / `filtered`, не трогать сеть.
