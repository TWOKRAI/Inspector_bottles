import time


def main(queue_manager):
    print(f'render_module: RUN')

    i = 0 

    while True:
        data = queue_manager.input_render.get()

        #i += 1
        #print(f'render_module: {data}')

        #time.sleep(0.01)

        queue_manager.input_capture.put(data)

    print(f'render_module: STOP')