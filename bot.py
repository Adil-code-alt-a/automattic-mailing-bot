from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from datetime import datetime, timedelta
import asyncio
import re
import os

TOKEN = os.getenv("TOKEN", "8560527789:AAF8r9Eo7MfIergU-OqhUW0hIi07hf1myAo")
CHANNEL_ID = "-1003452189598"   # ← если ID канала другой — поменяй здесь

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class Form(StatesGroup):
    waiting_time = State()

@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer("Привет! Перешли мне любой пост и напиши время:\n"
                         "10.12.2025 20:00\nзавтра 15:30\nчерез 10 минут")

@dp.message()
async def any_message(message: types.Message, state: FSMContext):
    # Если бот в состоянии ожидания времени — обрабатываем как время
    current_state = await state.get_state()
    if current_state == Form.waiting_time.state:
        await process_time(message, state)
        return

    # Иначе — это новый пост для планирования
    await state.set_state(Form.waiting_time)
    await state.update_data(original_message=message)   # сохраняем полностью всё сообщение
    await message.reply("Готово! Теперь напиши время публикации")

async def process_time(message: types.Message, state: FSMContext):
    text = message.text.strip().lower()
    now = datetime.now()
    dt = None

    if "через" in text:
        nums = re.findall(r"\d+", text)
        if nums:
            n = int(nums[0])
            if "час" in text:
                dt = now + timedelta(hours=n)
            else:
                dt = now + timedelta(minutes=n)
    elif "завтра" in text:
        dt = now + timedelta(days=1)
        if ":" in text:
            try:
                h, m = map(int, text.split()[-1].split(":"))
                dt = dt.replace(hour=h, minute=m)
            except:
                dt = dt.replace(hour=9, minute=0)
    else:
        try:
            dt = datetime.strptime(text, "%d.%m.%Y %H:%M")
        except:
            await message.reply("Не понял время. Примеры:\nчерез 2 минуты\nзавтра 15:30\n10.12.2025 20:00")
            return

    if not dt or dt <= now:
        await message.reply("Время в прошлом!")
        return

    delay = int((dt - now).total_seconds())
    await message.reply(f"Запланировано на {dt.strftime('%d.%m.%Y %H:%M')} (через {delay//60} мин)")

    await asyncio.sleep(delay)

    data = await state.get_data()
    orig_msg = data["original_message"]

    # Копируем именно пересланное/оригинальное сообщение
    await orig_msg.copy_to(chat_id=CHANNEL_ID)
    await bot.send_message(orig_msg.chat.id, "Пост опубликован в канал!")

    await state.clear()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
