import logging
import datetime

# Настройка логирования с явным указанием формата даты и времени
logging.basicConfig(filename='program_log.txt', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S', encoding='utf-8')

def log_start():
    logging.info('Программа запущена')

def log_stop():
    logging.info('Программа остановлена')

def log_action():
    logging.info(f'Робот принял действие')