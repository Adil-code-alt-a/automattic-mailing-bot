from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from datetime import datetime, timedelta
import asyncio
import re
import os
from zoneinfo import ZoneInfo

TOKEN = os.getenv("TOKEN", "8560527789:AAF8r9Eo7MfIergU-OqhUW0hIi07hf1myAo")
CHANNEL_ID = "-1003452189598"  # ← если канал другой — поменяй здесь

moscow_tz = ZoneInfo("Europe/Moscow")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class Form(StatesGroup):
    waiting_time = State()

@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer("Привет! Просто напиши мне любой текст, фото, видео, стикер или эмодзи (включая большие ABC).\n"
                         "Я сохраню и попрошу указать время.\n\n"
                         "Примеры времени:\n"
                         "• через 15 мин\n"
                         "• завтра 10:00\n"
                         "• 17.12.2025 14:30")

@dp.message()
async def any_message(message: types.Message, state: FSMContext):
    current = await state.get_state()
    
    # Если ждём время — обрабатываем как время
    if current == Form.waiting_time.state:
        await process_time(message, state)
        return
    
    # Иначе — это сам пост (принимаем ВСЁ: текст, фото, видео, стикеры, эмодзи и т.д.)
    await state.set_state(Form.waiting_time)
    await state.update_data(post=message)  # сохраняем полностью всё сообщение
    await message.reply("Отлично! Теперь напиши, когда выложить в канал")

async def process_time(message: types.Message, state: FSMContext):
    text = message.text.strip().lower() if message.text else ""
    now = datetime.now(moscow_tz)
    dt = None

    if "через" in text:
        mins_match = re.search(r"(\d+)\s*мин", text)
        hours_match = re.search(r"(\d+)\s*час", text)
        if mins_match:
            dt = now + timedelta(minutes=int(mins_match.group(1)))
        elif hours_match:
            dt = now + timedelta(hours=int(hours_match.group(1)))
        else:
            await message.reply("Напиши сколько: например «через 15 мин»")
            return
    elif "завтра" in text:
        dt = now + timedelta(days=1)
        time_match = re.search(r"(\d{1,2}):(\d{2})", text)
        if time_match:
            h, m = int(time_match.group(1)), int(time_match.group(2))
            dt = dt.replace(hour=h, minute=m, second=0, microsecond=0)
        else:
            dt = dt.replace(hour=9, minute=0, second=0, microsecond=0)
    else:
        try:
            dt = datetime.strptime(text, "%d.%m.%Y %H:%M")
            dt = dt.replace(tzinfo=moscow_tz)
        except:
            await message.reply("Не понял время.\nПримеры:\nчерез 15 мин\nзавтра 10:00\n17.12.2025 14:30")
            return

    if dt <= now:
        await message.reply("Время уже прошло или сейчас!")
        return

    delay = int((dt - now).total_seconds())
    minutes_left = delay // 60
    await message.reply(f"Запланировано на {dt.strftime('%d.%m.%Y %H:%M')} (МСК)\n"
                        f"Осталось ≈ {minutes_left} минут")

    await asyncio.sleep(delay)

    data = await state.get_data()
    post_msg = data["post"]

    # Копируем всё как есть: текст, фото, видео, стикеры, большие эмодзи ABC
    await post_msg.copy_to(chat_id=CHANNEL_ID)
    await bot.send_message(post_msg.chat.id, f"Пост выложен в канал!\n"
                                             f"Время: {datetime.now(moscow_tz).strftime('%H:%M %d.%m.%Y')} МСК")

    await state.clear()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
