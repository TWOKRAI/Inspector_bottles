# -*- coding: utf-8 -*-
"""Headless-воплощение процесса презентации (план D8, Р-6=(б)).

`gui` — такой же процесс топологии, как `devices`: он есть ВСЕГДА, а
презентационный overlay лишь подменяет ему класс. Два воплощения одного
процесса:

    headless : :class:`HeadlessGuiProcess` — принимает data-трафик и выбрасывает
    с Qt     : ``frontend.process.GuiProcess`` — принимает и рисует

Зачем так. Прежде headless означал «процесса `gui` нет вовсе», а продюсеры
продолжали адресовать его в ``chain_targets``. Адрес без приёмника даёт отказ
доставки на КАЖДЫЙ кадр — воспроизведено на стенде ``webcam_sketch``
(окно 30 с, до правки)::

    ProcessManager: errors_delivery_failed +1418 за 30.0 с (47/с),
                    sent_ok 21 из 1439 попыток
    журнал: send [delivery_failed] ни один из 1 адресатов не принял:
            channel=None command=None type='data' targets=['gui']

Причём копилось это НЕ у продюсера (дельта у camera_0/seg/points/lines — 0), а
у оркестратора: у продюсера имени `gui` нет ни очередью, ни каналом, поэтому
билет уходит хабу relay'ем (``_relay_via_hub``) и считается доставленным, а
провал случается уже на хабе. Диагноз указывал не на того, кто отправил.

**Кадры НЕ читаются из SHM намеренно.** Стаб не ставит ``FrameShmMiddleware``:
читать пиксели, чтобы их выбросить, — цена без потребителя. Следствие названо
вслух: при включённом ``FW_SHM_LOAN_PROTOCOL`` (дефолт — выключен, см.
``config_module/feature_flags.py``) потребитель обязан вернуть заём слота, а
этот его не возвращает; под тем флагом headless-воплощение нужно дополнять
release-путём.

Наблюдаемость дренажа — штатным счётчиком роутера ``received``
(``introspect.router_stats``), а не собственным числом: своё пришлось бы
доказывать отдельно, а этот уже читают все потребители.
"""

from __future__ import annotations

import time

from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import ThreadConfig, ThreadPriority

#: Имя воркера-дренажа. Видно в ``introspect.status``/state-дереве как обычный воркер.
DRAIN_WORKER = "data_drain"

#: Пауза опроса data-очереди — та же, что у ``GuiProcess.data_receiver``:
#: headless-воплощение не должно быть медленнее того, кого заменяет.
_POLL_TIMEOUT = 0.1


class HeadlessGuiProcess(ProcessModule):
    """Процесс презентации без презентации: принимает data-трафик и выбрасывает.

    Стандартный ``message_processor`` (system/state/observability) не
    переопределяется — команды ``introspect.*`` отвечают как у любого процесса.
    Добавляется ровно один поток: дренаж data-очереди, которую базовый
    ``ProcessModule`` не читает (её читают воркеры, а у стаба их нет).
    """

    def _init_application_threads(self) -> None:
        super()._init_application_threads()

        if not self.worker_manager:
            # Без worker_manager дренировать некому — молчать нельзя: снаружи это
            # выглядело бы как работающий приёмник при заполняющейся очереди.
            self._log_error(
                f"HeadlessGuiProcess '{self.name}': нет worker_manager — data-очередь "
                "никто не дренирует, отправители получат отказ доставки",
                module="headless_gui",
            )
            return

        self.worker_manager.create_worker(
            DRAIN_WORKER,
            self._drain_loop,
            ThreadConfig(priority=ThreadPriority.NORMAL),
            auto_start=True,
        )
        self._log_info(
            f"HeadlessGuiProcess '{self.name}': headless-воплощение презентации, data-трафик дренируется",
            module="headless_gui",
        )

    def _drain_loop(self, stop_event, pause_event) -> None:
        """Вычерпывать data-очередь и выбрасывать содержимое.

        Отказ ``receive`` не тушится молча: он уходит в плоскость ошибок тем же
        путём, что у настоящего приёмника, иначе «дренирует» и «умер» выглядели
        бы снаружи одинаково — очередь в обоих случаях наполняется.
        """
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue
            try:
                self.router_manager.receive(
                    timeout=_POLL_TIMEOUT,
                    channel_types=["data"],
                    return_messages=False,
                )
            except Exception as exc:  # noqa: BLE001 — дренаж обязан пережить одиночный сбой
                self._track_error(exc, context={"loop": DRAIN_WORKER})
                time.sleep(_POLL_TIMEOUT)
