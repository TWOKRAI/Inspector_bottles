from multiprocessing import Process
import psutil

from Multiproccesing.Queue_Manager import QueueManager


class MultiProcessManager:
    def __init__(self):
        self.queue_manager = QueueManager()

        self.processes = []
        

    def set_process_priority(self, process, priority):
        p = psutil.Process(process.pid)
        p.nice(priority)


    def import_modules(self):
        self.modules = {
            'app_processing': 'Multiproccesing.Processes.processes_app',
            'camera_process': 'Multiproccesing.Processes.processes_camera',
            'camera_process_out': 'Multiproccesing.Processes.processes_camera_out',
            'process_frames': 'Multiproccesing.Processes.processes_frame',
            'neural_processing': 'Multiproccesing.Processes.processes_neuroun',
            'communicate_with_robot': 'Multiproccesing.Processes.robot_new_processes',
            'frame_draw_processing': 'Multiproccesing.Processes.process_draw_frame',
            'process_bot': 'Multiproccesing.Processes.process_bot',
        }

        self.modules_enable = {
            'backend': True, 
            'app_processing': True,
            'camera_process': True,
            'camera_process_out': True,
            'process_frames': True,
            'neural_processing': True,
            'communicate_with_robot': True,
            'frame_draw_processing': True,
            'process_bot': True,
        }
        
        coll = 0
        if self.modules_enable['backend']:
            for _, value in self.modules_enable.items():
                if value:
                    coll += 1
        
        self.queue_manager.total_modules = coll - 3

        imported_modules = {}
        for name, path in self.modules.items():
            imported_modules[name] = getattr(__import__(path, fromlist=[name]), name)

        return imported_modules


    def initialize_processes(self):
        modules = self.import_modules()

        if self.modules_enable['app_processing']:
            self.app_process = Process(target=modules['app_processing'], args=(self.queue_manager, 'app_processing'))
            self.set_process_priority(self.app_process, psutil.HIGH_PRIORITY_CLASS)
            self.app_process.start()

        if self.modules_enable['backend']:
            if self.modules_enable['neural_processing']:
                neural_process = Process(target=modules['neural_processing'], args=(self.queue_manager, 'neuroun_process'))
                self.set_process_priority(neural_process, psutil.HIGH_PRIORITY_CLASS)
                self.processes.append(neural_process)

            if self.modules_enable['process_frames']:
                frame_process = Process(target=modules['process_frames'], args=(self.queue_manager, 'process_frames'))
                self.set_process_priority(frame_process, psutil.HIGH_PRIORITY_CLASS)
                self.processes.append(frame_process)

            if self.modules_enable['frame_draw_processing']:
                frame_draw_process = Process(target=modules['frame_draw_processing'], args=(self.queue_manager, 'draw_process'))
                self.set_process_priority(frame_draw_process, psutil.HIGH_PRIORITY_CLASS)
                self.processes.append(frame_draw_process)

            if self.modules_enable['camera_process']:
                camera_process = Process(target=modules['camera_process'], args=(self.queue_manager, 'camera_process'))
                self.set_process_priority(camera_process, psutil.HIGH_PRIORITY_CLASS)
                self.processes.append(camera_process)

            if self.modules_enable['camera_process_out']:
                camera_process_out = Process(target=modules['camera_process_out'], args=(self.queue_manager, 'camera_process_out'))
                self.processes.append(camera_process_out)
            
            if self.modules_enable['communicate_with_robot']:
                communicator_process = Process(target=modules['communicate_with_robot'], args=(self.queue_manager, 'communicate_with_robot'))
                #self.set_process_priority(communicator_process, psutil.HIGH_PRIORITY_CLASS)
                self.processes.append(communicator_process)

            if self.modules_enable['process_bot']:
                bot_process = Process(target=modules['process_bot'], args=(self.queue_manager, 'process_bot'))
                self.set_process_priority(bot_process, psutil.BELOW_NORMAL_PRIORITY_CLASS)
                self.processes.append(bot_process)


    def start_processes(self):
        for process in self.processes:
            process.start()


    def join_processes(self):
        for process in self.processes:
            process.join()


    def stop_processes(self):
        self.queue_manager.stop_event.set()
        self.join_processes()
        
