import time


class FrameFPS:
    def __init__(self, update_interval=1.0):
        self.frame_count = 0
        self.start_time = time.time()
        self.last_fps = 0.0
        self.update_interval = update_interval 


    def update(self):
        self.frame_count += 1
        
        current_time = time.time()
        elapsed = current_time - self.start_time
        
        if elapsed >= self.update_interval:
            self.last_fps = self.frame_count / elapsed
            self.frame_count = 0
            self.start_time = current_time

            return self.last_fps
        else:
            return 0
        
    
    def get_fps(self):
        return self.last_fps
            