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
CHANNEL_ID = "-1003452189598"

# Московское время всегда!
moscow_tz = ZoneInfo("Europe/Moscow")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class Form(StatesGroup):
    waiting_time = State()

@dp.message(CommandStart())
async def start(message: types.Message):
    now_msk = datetime.now(moscow_tz)
    await message.answer(f"Привет! Текущее время (МСК): {now_msk.strftime('%H:%M %d.%m.%Y')}\n\n"
                         "Напиши пост (текст, фото, видео, эмодзи — всё сразу).\n"
                         "Потом напиши время:\n"
                         "• через 15 мин\n"
                         "• завтра 10:00\n"
                         "• 17.12.2025 14:30")

@dp.message()
async def receive_post(message: types.Message, state: FSMContext):
    current = await state.get_state()
    if current == Form.waiting_time.state:
        await process_time(message, state)
        return

    await state.set_state(Form.waiting_time)
    await state.update_data(post=message)
    await message.reply("Пост принят! Теперь напиши время публикации")

async def process_time(message: types.Message, state: FSMContext):
    text = message.text.strip().lower()
    now = datetime.now(moscow_tz)  # всегда МСК
    dt = None

    if "через" in text:
        mins_match = re.search(r"(\d+)\s*(мин|минут|м)", text)
        hours_match = re.search(r"(\d+)\s*(час|часа|ч)", text)
        if mins_match:
            dt = now + timedelta(minutes=int(mins_match.group(1)))
        elif hours_match:
            dt = now + timedelta(hours=int(hours_match.group(1)))
        else:
            await message.reply("Не понял сколько минут/часов")
            return
    elif "завтра" in text:
        tomorrow = now + timedelta(days=1)
        dt = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)
        time_match = re.search(r"(\d{1,2}):(\d{2})", text)
        if time_match:
            h, m = int(time_match.group(1)), int(time_match.group(2))
            dt = dt.replace(hour=h, minute=m)
    else:
        try:
            # Формат дд.мм.гггг чч:мм
            naive_dt = datetime.strptime(text, "%d.%m.%Y %H:%M")
            dt = naive_dt.replace(tzinfo=moscow_tz)
        except ValueError:
            await message.reply("Не понял время. Примеры:\nчерез 15 мин\nзавтра 10:00\n17.12.2025 14:30")
            return

    if dt <= now:
        await message.reply("Время уже прошло или равно текущему!")
        return

    delay = int((dt - now).total_seconds())
    minutes_left = delay // 60
    hours_left = minutes_left // 60
    mins_left = minutes_left % 60

    await message.reply(f"Запланировано на {dt.strftime('%d.%m.%Y %H:%M')} (МСК)\n"
                        f"Осталось: {hours_left} ч {mins_left} мин")

    await asyncio.sleep(delay)

    data = await state.get_data()
    orig_post = data["post"]

    await orig_post.copy_to(chat_id=CHANNEL_ID)
    await bot.send_message(orig_post.chat.id, f"Пост опубликован в канал!\n"
                                              f"Время публикации: {dt.strftime('%H:%M %d.%m.%Y')} МСК")

    await state.clear()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
