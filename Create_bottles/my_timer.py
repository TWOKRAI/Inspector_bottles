import time


class Timer:
    def __init__(self, name):
        self.name = name
        self.start_time = None
        self.real_time = None
        self.elapsed = None
        self.result = None


    def start(self):
        """Начинает отсчет времени и сохраняет текущее время в атрибут start_time."""
        self.start_time = time.time()
        #print(f"Таймер {self.name} запущен")


    def elapsed_time(self, print_log=False):
        """Возвращает количество секунд, прошедших с момента запуска таймера."""
        if self.start_time is None:
            #print(f"Таймер {self.name} не был запущен.")
            return 0
        
        self.real_time = time.time()
        self.elapsed = self.real_time - self.start_time

        if print_log:
            print(f"Таймер {self.name} {self.elapsed * 1000} мс")
        
        return self.elapsed
    

    def get_data(self):
        self.real_time = time.time()
        self.elapsed = (self.real_time - self.start_time) * 1000

        self.result = [self.real_time, self.elapsed]

        return self.result
