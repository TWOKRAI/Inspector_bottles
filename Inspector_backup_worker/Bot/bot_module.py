import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
import re

from Bot.config import TELEGRAM_BOT_TOKEN

class TelegramBot:
    def __init__(self, queue_manager, api_token: str):
        # logging.basicConfig(level=logging.INFO)

        self.queue_manager = queue_manager

        self.bot = Bot(token=api_token)
        self.dp = Dispatcher(storage=MemoryStorage())

        self.chat_id = None

        self.register_handlers()

        self.keyboard = self.create_keyboard()

    def register_handlers(self):
        self.dp.message.register(self.handle_message)
        self.dp.message.register(self.send_last_message, Command(commands=['last_message']))
        self.dp.message.register(self.send_welcome, Command(commands=['start']))

    def create_keyboard(self):
        return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="/last_message")]], resize_keyboard=True)

    async def handle_message(self, message: types.Message):
        self.chat_id = message.chat.id

        if message.photo:
            # Если сообщение содержит фото, сохраняем его вместе с текстом
            photo = message.photo[-1]  # Берем самое большое изображение
            file_info = await self.bot.get_file(photo.file_id)
            file = await self.bot.download_file(file_info.file_path)
            self.save_message_to_file(message, file)
        else:
            self.save_message_to_file(message)

        await message.reply("Ваше сообщение отправлено!")


    async def send_last_message(self, message: types.Message):
        last_message = self.get_last_message()
        await message.reply(f"Последнее сообщение: {last_message}")

    async def send_welcome(self, message: types.Message):
        await message.reply("Привет! Используйте кнопку ниже, чтобы получить последнее сообщение.", reply_markup=self.keyboard)

    def save_message_to_file(self, message: types.Message, file=None):
        if file:
            text, buttons = self.extract_between_symbols(message.caption, '(', ')')
            send = (text, file, buttons)
        else:
            text, buttons = self.extract_between_symbols(message.text, '(', ')')
            send = (text, None, buttons)
            
        self.queue_manager.bot_message.put(send)


    def get_last_message(self):
        try:
            with open('messages.txt', 'r', encoding='utf-8') as file:
                lines = file.readlines()
                if lines:
                    # Найти последнее сообщение
                    for i in range(len(lines)-1, -1, -1):
                        if lines[i].startswith("Message: "):
                            return lines[i].replace("Message: ", "").strip()
        except FileNotFoundError:
            return "Файл с сообщениями не найден."
        

    async def check_queue_and_forward(self):
        while True:
            if not self.queue_manager.bot_message_send.empty():
                text = self.queue_manager.bot_message_send.get()
                await self.bot.send_message(chat_id=self.chat_id, text=text)
            
            await asyncio.sleep(0.5) 


    async def start_polling(self):
        asyncio.create_task(self.check_queue_and_forward())
        await self.dp.start_polling(self.bot)


    def extract_between_symbols(self, message, start_symbol, end_symbol):
        pattern = re.compile(f'{re.escape(start_symbol)}(.*?){re.escape(end_symbol)}')
        matches = pattern.findall(message)

        # Находим индекс первого вхождения начального символа
        first_match_index = message.find(start_symbol)

        # Если символ найден, обрезаем строку до этого символа
        if first_match_index != -1:
            clean_message = message[:first_match_index].strip()
        else:
            clean_message = message.strip()

        return clean_message, matches


if __name__ == '__main__':
    bot = TelegramBot(api_token=TELEGRAM_BOT_TOKEN)
    asyncio.run(bot.start_polling())
