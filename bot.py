from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from datetime import datetime, timedelta
import asyncio
import re
import os

TOKEN = os.getenv("TOKEN")
CHANNEL_ID = "-1003452189598"  # Твой канал — если ID неверный, замени

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class Scheduling(StatesGroup):
    waiting_time = State()

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await message.answer("Привет! Перешли мне любой пост (текст, фото, видео) и напиши под ним время:\n"
                         "• 10.12.2025 20:00\n"
                         "• завтра 14:30\n"
                         "• через 2 часа\n"
                         "• каждый день 09:00\n\n"
                         "Я запланирую и выложу в канал!")

@dp.message(F.content_type.in_({types.ContentType.TEXT, types.ContentType.PHOTO, types.ContentType.VIDEO, types.ContentType.DOCUMENT, types.ContentType.POLL}))
async def receive_post(message: types.Message, state: FSMContext):
    await state.update_data(post=message)
    await state.set_state(Scheduling.waiting_time)
    await message.answer("Теперь напиши время публикации (примеры выше).")

@dp.message(Scheduling.waiting_time)
async def receive_time(message: types.Message, state: FSMContext):
    data = await state.get_data()
    post = data["post"]
    
    text = message.text.lower().strip()
    now = datetime.now()
    dt = None
    
    # Парсинг времени (простой, но работает)
    if "каждый день" in text:
        match = re.search(r"(\d{1,2}):(\d{2})", text)
        if match:
            h, m = int(match.group(1)), int(match.group(2))
            dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if dt <= now:
                dt += timedelta(days=1)
    elif "завтра" in text:
        dt = now + timedelta(days=1)
        match = re.search(r"(\d{1,2}):(\d{2})", text)
        if match:
            h, m = int(match.group(1)), int(match.group(2))
            dt = dt.replace(hour=h, minute=m)
    elif "через" in text:
        num_match = re.search(r"(\d+)", text)
        if num_match:
            num = int(num_match.group(1))
            if "час" in text:
                dt = now + timedelta(hours=num)
            elif "минут" in text or "мин" in text:
                dt = now + timedelta(minutes=num)
    else:
        try:
            dt = datetime.strptime(text, "%d.%m.%Y %H:%M")
        except ValueError:
            await message.answer("Не понял время. Примеры:\n10.12.2025 20:00\nзавтра 14:30\nчерез 10 минут")
            return
    
    if not dt or dt <= now:
        await message.answer("Время неверное или уже прошло. Попробуй снова.")
        return
    
    delay = (dt - now).total_seconds()
    await message.answer(f"✅ Запланировано на {dt.strftime('%d.%m.%Y %H:%M')}!\n(Через {int(delay/60)} мин)")
    
    # Отложенная отправка
    await asyncio.sleep(delay)
    await bot.copy_message(CHANNEL_ID, post.chat.id, post.message_id)
    await bot.send_message(post.chat.id, "📤 Пост опубликован в канал!")
    
    await state.clear()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
