import time


def main(queue_manager):
    print(f'ui_module: RUN')

    i = 0

    while True:
        print(f'ui_module: {i}')
        i += 1

        time.sleep(1)
    
    print(f'ui_module: STOP')