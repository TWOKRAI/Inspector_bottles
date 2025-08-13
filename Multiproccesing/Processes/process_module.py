import threading


class Process_module:
    def __init__(self, queue_manager):
        self.queue_manager = queue_manager

        self.stop_proccess = False

        self.local_controls_parametrs = {}

        self._init_threading()


    def _init_threading(self):
        self.control_thread = threading.Thread(target=self._control_threading)
        self.main_thread = threading.Thread(target=self._main_threading)


    def start_thread(self):
        self.main_thread.start()
        self.control_thread.start()


    def stop_thread(self):
        self.main_thread.join()
        self.control_thread.join()


    def _control_threading(self):
        while not self.queue_manager.stop_event.is_set() and not self.stop_proccess:
            controls_parametrs = self.queue_manager.control_capture.get()

            self._update_parametrs(controls_parametrs)


    def _update_parametrs(self, incoming_parametrs):
        for key in incoming_parametrs:
            if key in self.local_controls_parametrs:
                self.local_controls_parametrs[key] = incoming_parametrs[key]

        self.get_parametrs()
    

    def get_parametrs(self):
        pass


    def _main_threading(self):
        while not self.queue_manager.stop_event.is_set() and not self.stop_proccess:
            self.main()
    

    def main(self):
        pass

