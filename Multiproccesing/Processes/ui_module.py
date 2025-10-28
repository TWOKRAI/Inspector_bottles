from App.main_app import WindowManager


def main(queue_manager=None, control_queue=None):
    window_manager = WindowManager(name='Capture_process', 
                              queue_manager=queue_manager, 
                              control_queue=control_queue)
    
    window_manager.run()
    
