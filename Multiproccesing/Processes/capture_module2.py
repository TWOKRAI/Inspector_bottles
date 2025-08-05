import cv2
import time

from Multiproccesing.Memory_Manager import ImageMemoryManager
from Camera_module.socket_image import ImageStreamer
from Camera_module.frame_fps import FrameFPS
from Utils.timer import Timer


# Настройки
PI_IP = '192.168.1.100' 
PORT = 6000


RESOLUTION = (1920, 1080)
#RESOLUTION = (1280, 720)
#RESOLUTION = (640, 480)
QUALITY = 95
PORT = 6000


streamer = ImageStreamer(host='0.0.0.0', port=5000)

streamer.connect_client(PI_IP, PORT)

#     # Чтение изображения
#     frame = cv2.imread(image_path)
#     frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


timer = Timer('camera_tcp')


def main(queue_manager:ImageMemoryManager):
    print(f'capture_module: RUN')

    data = (3,
            RESOLUTION[0],
            RESOLUTION[1],
            QUALITY,
            100,
            )

    streamer.send_data(data)

    try:
        fps_counter = FrameFPS(update_interval=1.0)
        
        while True:
            #timer.start()
            frame = streamer.read_frame()
            #timer.elapsed_time(print_log=True)

            if frame is not None:
                #print(f"Отображен кадр размером {frame.shape}")

                fps = fps_counter.update()
                if fps > 0:
                    print(f"FPS: {fps:.2f}")

                frames = [frame]

                id_memory = 0
                queue_manager.memory_manager.write_images(frames, "camera_data", id_memory)

                data_frame = {
                    'id_memory': id_memory,
                    'time': time.time()
                }

                queue_manager.input_processing.put(data_frame)
                queue_manager.input_capture.get()

            # # Проверка нажатия клавиши
            # if cv2.waitKey(1) == ord('q'):
            #     break
        
    except Exception as e:
        print(f"Критическая ошибка: {str(e)}")
    finally:
        streamer.stop()
        cv2.destroyAllWindows()
        print("Соединение закрыто")