"""Проводка очереди наблюдаемости: она есть у каждого процесса и её дренируют (Ф7.3).

Механизм расщепления бесполезен, если очередь где-то не создалась (запись не
доедет вовсе) или её никто не опрашивает (доедет и умрёт в очереди). Оба конца
проверяются здесь: конфиг процесса и список опрашиваемых классов у приёмника.

Урок Ф6.2, из-за которого домердж вообще существует: кастомный ``queues`` без
обязательной очереди давал ТИХИЙ отказ — у отправителя «Queue not found», у
подписчика вечная тишина при живом процессе.
"""

from __future__ import annotations

from ..configs.process_launch_config import DEFAULT_QUEUES, ProcessLaunchConfig
from ....modules.shared_resources_module.state.process_data import ProcessDataKeys

OBS = ProcessDataKeys.QUEUE_OBSERVABILITY


class TestQueueExistsInEveryProcess:
    def test_default_layout_has_the_tail_queue(self):
        assert OBS in DEFAULT_QUEUES
        assert DEFAULT_QUEUES[OBS]["maxsize"] > 0

    def test_custom_queues_still_get_the_tail_queue(self):
        """Кастомная раскладка НЕ отменяет обязательную очередь, но и не трогает
        пользовательские глубины остальных."""
        cfg = ProcessLaunchConfig(
            process_name="camera_0",
            process_class="x.Y",
            queues={"system": {"maxsize": 7}, "data": {"maxsize": 3}},
        )

        _name, proc_dict = cfg.build()

        assert proc_dict["queues"][OBS] == DEFAULT_QUEUES[OBS]
        assert proc_dict["queues"]["system"]["maxsize"] == 7
        assert proc_dict["queues"]["data"]["maxsize"] == 3

    def test_custom_depth_of_the_tail_queue_is_respected(self):
        """Домердж — про наличие, а не про глубину: заданную глубину не перетираем."""
        cfg = ProcessLaunchConfig(
            process_name="camera_0",
            process_class="x.Y",
            queues={"system": {"maxsize": 7}, OBS: {"maxsize": 999}},
        )

        _name, proc_dict = cfg.build()

        assert proc_dict["queues"][OBS]["maxsize"] == 999

    def test_hub_registers_its_own_tail_queue(self):
        """У хаба (ProcessManager) очередь хвоста нужна по существу: через него идёт
        relay записей детей внешнему подписчику (Ф1.7).

        Читается та самая раскладка, которую хаб отдаёт в ``register_process``, —
        не текст метода: страж на исходник сторожил бы написание, а не состав.
        """
        from ....modules.process_manager_module.process.process_manager_process import HUB_QUEUES

        assert OBS in HUB_QUEUES
        assert HUB_QUEUES[OBS]["maxsize"] > 0


class TestReceiverDrainsTheTailQueue:
    def test_message_processor_polls_it(self):
        """Приёмный поток опрашивает класс хвоста наравне с system/state.

        Стенд поведенческий: фальшивый роутер записывает, с какими
        ``channel_types`` его позвали, и тут же взводит stop_event. Цикл крутится в
        daemon-потоке с дедлайном join — тест, способный заблокироваться, обязан
        падать по времени, а не висеть, унося с собой всю сюиту.
        """
        import threading

        from ..threads.system_threads import SystemThreads

        seen: list = []
        stop_event = threading.Event()

        class _Router:
            def receive(self, timeout=0.0, channel_types=None, **kwargs):
                seen.append(channel_types)
                stop_event.set()
                return []

        class _Process:
            router_manager = _Router()
            worker_manager = None

            def _log_error(self, *_a, **_kw):
                pass

        threads = SystemThreads(_Process())
        runner = threading.Thread(
            target=threads._message_processing_loop,
            args=(stop_event, threading.Event()),
            daemon=True,
        )
        runner.start()
        runner.join(timeout=5.0)

        assert not runner.is_alive(), "цикл приёма не завершился по stop_event"
        assert seen and OBS in seen[0]
        assert "system" in seen[0] and "state" in seen[0]
