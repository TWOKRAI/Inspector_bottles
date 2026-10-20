"""``robot_driver_v2.params`` (T5.3f f2).

Purpose:
    Параметры драйвера робота Delta v2: синхронизация, ``param_set`` / ``param_apply``, откат значения.

Stability: lite
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from Services.device_hub.drivers.base import logger
from Services.device_hub.drivers.robot_driver_v2.args import (
    _STORE_ERRORS,
    _BadArgs,
    _StoreIOError,
    _base_rev_arg,
    _name_arg,
    _number_arg,
    _store_refusal,
)
from Services.device_hub.drivers.robot_driver_v2.texts import (
    TEXT_BAD_RANGE,
    TEXT_EPOCH_NOT_WRITTEN,
    TEXT_NO_STORE,
    TEXT_PARAM_DIVERGED,
    TEXT_PARAM_NO_REPLY,
    TEXT_SYNCING,
    TEXT_UNKNOWN_PARAM,
    _NOT_CONNECTED,
    _RECONNECT_THROTTLE_SEC,
)
from Services.device_hub.drivers.robot_driver_v2.tlm import _w
from Services.device_hub.robot_data_ops import TEXT_BAD_ARGS, TEXT_STORE_ERROR
from Services.robot_comm.core.client_v2 import RobotClientV2, SyncCancelled
from Services.robot_comm.core.params_v2 import PARAM_ID, to_eng, to_raw
from Services.robot_comm.errors import RevisionConflict, RobotNak
from Services.robot_comm.robot_data import load_params, param_bounds, save_params
from Services.robot_comm.store import RobotDataStore

__all__ = ["ParamMixin"]


class ParamMixin:
    """Миксин ``RobotDriverV2``: синхронизация параметров, ``param_set`` / ``param_apply``.

    Без ``__init__`` и полей: читает атрибуты драйвера ``RobotDriverV2``.
    Поля и атрибуты базы: ``_client``, ``_clock``, ``_epoch``, ``_last_resync``, ``_param_lock``, ``_pub``,
        ``_state``, ``_store``, ``_values``, ``entry``.
    Методы соседей: ``_load_params``, ``_publish_error``, ``_read_tlm``, ``_record_err``, ``is_connected``.
    """

    def _end_sync(self) -> None:
        self._state.end_sync()

    def _sync_cancelled(self) -> bool:
        """Отмена синхронизации: остановка (``stopping`` / ``shutdown``) — после стопа параметры не пишутся."""
        return self._state.sync_cancelled()

    def _sync_on_connect(self, client: RobotClientV2) -> bool:
        """``_connect_locked``: ``_load_params()`` + ``sync_params`` под флагом ``syncing``; ``_param_lock`` уже держит
        вызывающий (``connect`` / ``_ensure_connected``). Порядок замков: ``_param_lock`` -> замок состояния.

        False — синхронизации не было: активность появилась после ранней проверки ``connect``.
        """
        if not self._state.begin_sync():
            return False
        old = self._values, self._epoch
        try:
            self._values, self._epoch = self._load_params_io()
            client.sync_params(self._values, self._epoch, cancelled=self._sync_cancelled)
        except SyncCancelled:  # остановка посреди синхронизации: не синхронизировано, метка прежняя, не ошибка
            self._values, self._epoch = old
            return False
        finally:
            self._end_sync()
        return True

    def _load_params_io(self) -> tuple[dict[str, int], int]:
        """``_load_params`` с диском: ``OSError`` хранилища -> лог с полным текстом и ``_StoreIOError``."""
        try:
            return self._load_params()
        except OSError as exc:
            logger.warning(f"робот {self.entry.id!r}: ошибка хранилища данных: {type(exc).__name__}: {exc}")
            raise _StoreIOError from None

    def _resync_maybe(self, client: RobotClientV2) -> None:
        """Метка робота не равна метке ПК -> sync_params снова (§11.4 п.4), только когда робот свободен.

        ``_param_lock`` берётся не блокируя (идёт ``param_set`` / ``param_apply`` — тик не стоит на замке, пульс
        сторожа не пропадает; метку обновит сам ``param_set``). Под замком метка и ``TLM_ACTIVITY`` читаются заново:
        ``param_set`` мог записать метку между чтением тика и захватом замка (равны — выхода без sync достаточно),
        а ``jog_step`` отвечает после ACK без флага — при ``TLM_ACTIVITY != 0`` ``PARAM_SET`` получил бы ``E_BUSY``.
        ``_last_resync`` ставится только после того, как проверка активности прошла.
        """
        if not self._param_lock.acquire(blocking=False):
            return
        try:
            try:
                tlm = self._read_tlm()
            except Exception as exc:  # связь разберёт тик по своему чтению
                self._record_err()
                logger.warning(f"робот {self.entry.id!r}: метка не перечитана: {type(exc).__name__}: {exc}")
                return
            if _w(tlm, "TLM_CFG_EPOCH") == self._epoch or _w(tlm, "TLM_ACTIVITY") != 0:
                return
            now = self._clock()
            if now - self._last_resync < _RECONNECT_THROTTLE_SEC and self._last_resync:
                return
            started = self._state.begin_sync()
            if not started:
                return
            self._last_resync = now
            old = self._values, self._epoch
            try:
                self._values, self._epoch = self._load_params_io()
                client.sync_params(self._values, self._epoch, cancelled=self._sync_cancelled)
            except SyncCancelled:  # остановка посреди синхронизации: метка прежняя, не ошибка
                self._values, self._epoch = old
            except _StoreIOError:
                self._record_err()
                self._publish_error(TEXT_STORE_ERROR)
            except Exception as exc:
                self._record_err()
                self._publish_error(f"синхронизация параметров не удалась: {type(exc).__name__}: {exc}")
            finally:
                self._end_sync()
        finally:
            self._param_lock.release()

    def _store_call[T](self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Вызов хранилища: ``OSError`` (диск) -> лог с полным текстом и ``_StoreIOError`` (ответ — константа)."""
        try:
            return fn(*args, **kwargs)
        except OSError as exc:
            logger.warning(f"робот {self.entry.id!r}: ошибка хранилища данных: {type(exc).__name__}: {exc}")
            raise _StoreIOError from None

    def _param_gate(self) -> dict | None:
        """Взять ``_param_lock`` без блокировки. Отказ (замок занят, останов или ``syncing``) — ответ; успех — None,
        замок взят, вызывающий отпускает его в ``finally``. Блокирующий захват стоял бы всю синхронизацию на
        командном потоке."""
        if not self._param_lock.acquire(blocking=False):
            return {"status": "error", "message": TEXT_SYNCING}
        refusal = self._state.param_refusal()
        if refusal is not None:
            self._param_lock.release()
            return {"status": "error", "message": refusal}
        return None

    def _op_param_set(self, args: dict) -> dict:
        """PARAM_SET {name, value, base_rev}: границы -> робот -> метка -> файл -> ``self._values`` / ``self._epoch``.

        Порядок (§11.4 «файл — правда»): значение в робота ДО файла; сбой записи значения без NAK (таймаут, обрыв) или
        сбой метки после ACK значения — откат значения роботу, ответ-ошибка, файл и ``self._epoch`` не тронуты; сбой
        записи файла — ``self._epoch`` прежний, следующий тик видит расхождение меток и возвращает роботу значения
        файла."""
        try:
            name, base_rev = _name_arg(args, "name"), _base_rev_arg(args)
            value = _number_arg(args, "value")
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_ARGS}
        store = self._store
        if store is None:
            return {"status": "error", "message": TEXT_NO_STORE}
        if name not in PARAM_ID or name == "P_CONFIG_EPOCH":
            return {"status": "error", "message": TEXT_UNKNOWN_PARAM}
        try:
            raw = to_raw(name, value)
        except OverflowError:  # 1.7e308 * scale -> inf
            return {"status": "error", "message": TEXT_BAD_ARGS}
        low, high = param_bounds(name)  # имя проверено выше: PARAM_ID без P_CONFIG_EPOCH
        if not low <= raw <= high:
            return {"status": "error", "message": TEXT_BAD_RANGE}
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        refusal = self._param_gate()
        if refusal is not None:
            return refusal
        try:
            return self._param_set_locked(store, name, raw, base_rev)
        except _STORE_ERRORS as exc:
            return _store_refusal(exc)
        finally:
            self._param_lock.release()

    def _param_set_locked(self, store: RobotDataStore, name: str, raw: int, base_rev: str | None) -> dict:
        """Тело ``param_set`` под ``_param_lock``."""
        old_values, old_epoch = dict(self._values), self._epoch  # владелец — _param_lock (T5.3f Q6)
        current_rev = self._store_call(load_params, store, self.entry.id).rev
        if current_rev != base_rev:
            raise RevisionConflict(current_rev)  # робот не тронут
        client = self._client
        old_raw = old_values[name]
        try:
            client.param_set(name, raw)
        except RobotNak:
            raise  # робот ответил отказом: значение не принято, файл не тронут
        except Exception as exc:
            # Исход записи неизвестен (таймаут, обрыв: робот мог применить, ответ потерян) — как сбой метки: значение
            # файла возвращается роботу, метка и файл не тронуты
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: запись параметра без ответа: {type(exc).__name__}: {exc}")
            self._roll_back_param(client, name, old_raw, TEXT_PARAM_NO_REPLY)
            return {"status": "error", "message": TEXT_PARAM_NO_REPLY}
        new_epoch = old_epoch % 65535 + 1
        try:
            client.param_set("P_CONFIG_EPOCH", new_epoch)
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: метка параметров не записана: {type(exc).__name__}: {exc}")
            self._roll_back_param(client, name, old_raw, TEXT_EPOCH_NOT_WRITTEN)
            return {"status": "error", "message": TEXT_EPOCH_NOT_WRITTEN}
        new_values = {**old_values, name: raw}
        # Запись файла упала -> исключение наружу, self._epoch прежний: тик увидит расхождение меток (§11.4 п.4)
        rev = self._store_call(save_params, store, self.entry.id, new_values, new_epoch, base_rev=base_rev)
        self._values, self._epoch = new_values, new_epoch  # владелец — _param_lock (T5.3f Q6)
        self._pub(
            f"devices.state.{self.entry.id}.params",
            {
                "epoch": new_epoch,
                "rev": rev,
                "values": {key: {"raw": r, "value": float(to_eng(key, r))} for key, r in new_values.items()},
            },
        )
        return {
            "status": "ok",
            "name": name,
            "raw": raw,
            "value": float(to_eng(name, raw)),
            "epoch": new_epoch,
            "rev": rev,
        }

    def _roll_back_param(self, client: RobotClientV2, name: str, old_raw: int, failed_text: str) -> None:
        """Одна попытка вернуть роботу значение файла; итог — в ``last_error``: ``failed_text`` (откат прошёл) или
        ``TEXT_PARAM_DIVERGED`` (не прошёл: робот и файл расходятся)."""
        try:
            client.param_set(name, old_raw)
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: откат параметра не прошёл: {type(exc).__name__}: {exc}")
            self._publish_error(TEXT_PARAM_DIVERGED)
        else:
            self._publish_error(failed_text)

    def _op_param_apply(self, _args: dict) -> dict:
        """PARAM_APPLY: параметры класса ``reinit`` вступают в силу; под ``_param_lock`` (не при синхронизации)."""
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        refusal = self._param_gate()
        if refusal is not None:
            return refusal
        try:
            self._client.param_apply()
        finally:
            self._param_lock.release()
        return {"status": "ok"}
