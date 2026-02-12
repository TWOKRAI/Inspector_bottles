import asyncio

from Bot.bot_module import TelegramBot
from Bot.config import TELEGRAM_BOT_TOKEN


class BotProcess:
    def __init__(self, queue_manager, name) -> None:
        self.name_process = str(name)
        self.queue_manager = queue_manager

        self.bot = TelegramBot(api_token=TELEGRAM_BOT_TOKEN, queue_manager=self.queue_manager)


    async def start_polling_with_retries(self):
        while not self.queue_manager.stop_event.is_set():
            try:
                await self.bot.start_polling()
                print('Запустил бота')
            except Exception as e:
                print(f"Ошибка: {e}. Повторная попытка через 10 секунд...")
                await asyncio.sleep(10)


    def start(self):
        asyncio.run(self.start_polling_with_retries())


def process_bot(queue_manager, stop_event):
    bot = BotProcess(queue_manager, stop_event)
    bot.start()
