import time
import cv2


def main(queue_manager):
    print(f'render_module: RUN')

    while True:
        data_frame = queue_manager.input_render.get()
        
        id_memory = data_frame['id_memory']
        #print(f'processing_module: {id_memory}')

        frames = queue_manager.memory_manager.read_images("process_data", id_memory)
        timer_start = data_frame['time']

        elapsed = time.time() - timer_start
        #print(f"Таймер  {elapsed * 1000} мс")

        if len(frames) > 0:
            # Отображаем изображение
            cv2.imshow('Image', frames[0])
            cv2.waitKey(1)  # Ждем нажатия любой клавиши
        else:
            print("Не удалось загрузить изображение.")
        
        queue_manager.input_capture.put(id_memory)
            
        #time.sleep(1)
        
        #queue_manager.input_render.put(id_memory)
    
    cv2.destroyAllWindows()  # Закрываем все окна OpenCV
    print(f'processing_module: STOP')