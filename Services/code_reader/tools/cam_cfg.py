"""Одноразовая настройка собственного триггера камер ID3013 (SelfTrigger + период). НЕ часть продукта.

  cam_cfg.py selftrigger <ip>     TriggerMode=On, TriggerSource=SelfTrigger; печатает узел периода (cur/min/max/inc)
  cam_cfg.py period <ip> <N>      TriggerSelfTriggerPeriod = N
  cam_cfg.py show <ip>            только читает
  cam_cfg.py revert <ip>          вернуть исходные значения из cam_orig.json (период -> источник -> режим)

Исходные значения пишутся в cam_orig.json ДО каждой записи; при сбое шага уже сделанное откатывается.
Запись в прибор — только при закрытом захвате (стенд остановлен, IDMVS закрыт).
"""

import json
import pathlib
import sys

from Services.code_reader.sdk.api import MvCodeReaderApi

ORIG = pathlib.Path(__file__).with_name("cam_orig.json")


def load() -> dict:
    return json.loads(ORIG.read_text(encoding="utf-8")) if ORIG.exists() else {}


def save(data: dict) -> None:
    ORIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def open_cam(api: MvCodeReaderApi, ip: str):
    dev = next((d for d in api.enum_devices() if d.ip == ip), None)
    if dev is None:
        raise SystemExit(f"прибор {ip} не найден")
    print("открыт", dev.ip, dev.model, flush=True)
    return api.open(dev)


def state(api, h) -> dict:
    out = {}
    for name, getter in (
        ("TriggerMode", api.get_enum),
        ("TriggerSource", api.get_enum),
        ("TriggerSelfTriggerPeriod", api.get_int),
    ):
        try:
            out[name] = getter(h, name)
        except Exception as exc:  # noqa: BLE001 — показать, что закрыто
            out[name] = f"недоступен: {exc}"
    return out


def revert(api, h, ip: str, data: dict) -> None:
    orig = data.get(ip, {})
    # порядок важен: зависимые узлы возвращаются первыми, пока TriggerMode ещё On
    for name, setter in (
        ("TriggerSelfTriggerPeriod", api.set_int),
        ("TriggerSource", api.set_enum),
        ("TriggerMode", api.set_enum),
    ):
        if name in orig:
            try:
                setter(h, name, orig[name])
                print("возвращён", name, "=", orig[name], flush=True)
            except Exception as exc:  # noqa: BLE001
                print("НЕ ВОЗВРАЩЁН", name, "orig=", orig[name], exc, flush=True)


def main() -> int:
    cmd, ip = sys.argv[1], sys.argv[2]
    api = MvCodeReaderApi()
    h = open_cam(api, ip)
    data = load()
    try:
        if cmd == "show":
            print(json.dumps(state(api, h), ensure_ascii=False, indent=1))
        elif cmd == "revert":
            revert(api, h, ip, data)
            print(json.dumps(state(api, h), ensure_ascii=False, indent=1))
        elif cmd == "selftrigger":
            orig = data.setdefault(ip, {})
            try:
                orig.setdefault("TriggerMode", api.get_enum(h, "TriggerMode")["cur"])
                save(data)
                print("ORIG TriggerMode =", orig["TriggerMode"], flush=True)
                if orig["TriggerMode"] != 1:
                    api.set_enum(h, "TriggerMode", 1)
                orig.setdefault("TriggerSource", api.get_enum(h, "TriggerSource")["cur"])
                save(data)
                print("ORIG TriggerSource =", orig["TriggerSource"], flush=True)
                api.set_enum_str(h, "TriggerSource", "SelfTrigger")
                try:
                    orig.setdefault("TriggerSelfTriggerPeriod", api.get_int(h, "TriggerSelfTriggerPeriod")["cur"])
                    save(data)
                except Exception as exc:  # noqa: BLE001
                    print("период не прочитан:", exc, flush=True)
            except BaseException:
                print("СБОЙ — откат", flush=True)
                revert(api, h, ip, data)
                raise
            print(json.dumps(state(api, h), ensure_ascii=False, indent=1))
        elif cmd == "period":
            value = int(sys.argv[3])
            orig = data.setdefault(ip, {})
            orig.setdefault("TriggerSelfTriggerPeriod", api.get_int(h, "TriggerSelfTriggerPeriod")["cur"])
            save(data)
            api.set_int(h, "TriggerSelfTriggerPeriod", value)
            print(json.dumps(state(api, h), ensure_ascii=False, indent=1))
        else:
            raise SystemExit("неизвестная команда")
    finally:
        api.close(h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
