import modbus_tk.modbus_rtu as modbus_rtu
import modbus_tk.defines as defines
import serial


class Conveyor:
    def __init__(self, port, baudrate):
        self.master = modbus_rtu.RtuMaster(serial.Serial(port=port, baudrate=baudrate))
        self.master.set_timeout(5.0)
        self.master.set_verbose(True)
        self.is_running = False
        self.freq = 30
        self.speed = 30

        self.k = 7.1


    def start(self):
        self.master.execute(1, defines.WRITE_SINGLE_REGISTER, 8192, output_value=1)
        self.is_running = True
        print('Transport on')


    def stop(self):
        self.master.execute(1, defines.WRITE_SINGLE_REGISTER, 8192, output_value=5)
        self.is_running = False
        print('Transport off')


    def change_freq(self, value):
        if value < 10:
            value = 10

        #value = 30
        
        self.master.execute(1, defines.WRITE_SINGLE_REGISTER, 8193, output_value=value * 100)
        self.freq = value
        #print(f'Speed changed to {self.freq}')


    def get_freq(self):
        response = self.master.execute(1, defines.READ_HOLDING_REGISTERS,  8193, 1)
        self.freq = response[0] / 100

        return self.freq
    

    def get_state(self):
        response = self.master.execute(1, defines.READ_HOLDING_REGISTERS,  8192, 1)

        return response


    def close(self):
        self.master.close()


    def hertz_to_mm_per_sec(self, frequency_hz: float, per_cycle = 7.27) -> float:
        """
        Переводит частоту в герцах в скорость в миллиметрах в секунду.

        :param frequency_hz: Частота в герцах.
        :param per_cycle: коэффициент соотношения.
        :return: Скорость в миллиметрах в секунду.
        """
        speed_mm_per_sec = frequency_hz * per_cycle
        self.speed = speed_mm_per_sec * 1.01
        
        return speed_mm_per_sec


if __name__ == '__main__':
    # Пример использования
    conveyor = Conveyor(port='COM7', baudrate=9600)

    # Изменение частоты
    conveyor.change_freq(30)

    # Получение текущего состояния
    freq = conveyor.get_freq()
    print('frea', freq)

    state = conveyor.get_state()
    print('state', state)

    conveyor.close()