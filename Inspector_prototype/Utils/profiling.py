import tracemalloc

def start_profiling():
    print("Начало профилирования памяти")
    tracemalloc.start()

def stop_profiling():
    print("Остановка профилирования памяти")
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics('lineno')

    print("[ Top 10 memory consumers ]")
    for stat in top_stats[:10]:
        print(stat)


# if __name__ == '__main__':
#     start_profiling()

#     # Искусственная утечка памяти для проверки
#     leak = []
#     for i in range(1000):
#         leak.append([i] * 1000)

#     stop_profiling()
