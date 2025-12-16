from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import asyncio
import re
import os

TOKEN = os.getenv("TOKEN", "8560527789:AAF8r9Eo7MfIergU-OqhUW0hIi07hf1myAo")
CHANNEL_ID = "-1003452189598"

moscow_tz = ZoneInfo("Europe/Moscow")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Очередь задач: user_id -> list of dicts
scheduled_tasks = {}

class Form(StatesGroup):
    waiting_time = State()

@dp.message(CommandStart())
async def start(message: types.Message):
    now = datetime.now(moscow_tz)
    await message.answer(f"Привет! Время МСК: {now.strftime('%H:%M %d.%m.%Y')}\n\n"
                         "Напиши пост → укажи время → я опубликую в канал.\n"
                         "Команды:\n/list — посмотреть очередь\n/now — опубликовать сразу\n/cancel <номер> — отменить")

@dp.message(Command("list"))
async def list_tasks(message: types.Message):
    user_id = message.from_user.id
    tasks = scheduled_tasks.get(user_id, [])
    if not tasks:
        await message.answer("Очередь пуста")
        return
    text = "Запланированные посты:\n\n"
    for i, task in enumerate(tasks, 1):
        dt = task["time"]
        text += f"{i}. {dt.strftime('%d.%m %H:%M')} — {task['preview']}\n"
    await message.answer(text)

@dp.message(Command("now"))
async def publish_now(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if "post" not in data:
        await message.answer("Сначала отправь пост")
        return
    post = data["post"]
    await post.copy_to(CHANNEL_ID)
    await message.answer("Пост опубликован сразу!")
    await state.clear()

@dp.message(Command("cancel"))
async def cancel_task(message: types.Message):
    try:
        num = int(message.text.split()[1]) - 1
        user_id = message.from_user.id
        tasks = scheduled_tasks.get(user_id, [])
        if 0 <= num < len(tasks):
            del tasks[num]
            await message.answer(f"Пост №{num+1} отменён")
        else:
            await message.answer("Неверный номер")
    except:
        await message.answer("Использование: /cancel <номер из /list>")

@dp.message()
async def receive_post(message: types.Message, state: FSMContext):
    current = await state.get_state()
    if current == Form.waiting_time.state:
        await process_time(message, state)
        return

    await state.set_state(Form.waiting_time)
    await state.update_data(post=message)

    preview = message.text or message.caption or "[медиа]"
    if len(preview) > 30:
        preview = preview[:30] + "..."

    await message.reply(f"Пост принят: \"{preview}\"\nТеперь напиши время")

async def process_time(message: types.Message, state: FSMContext):
    # ... (парсинг времени как в предыдущей версии — оставляю тот же)

    # После парсинга dt и delay:
    user_id = message.from_user.id
    if user_id not in scheduled_tasks:
        scheduled_tasks[user_id] = []

    data = await state.get_data()
    orig_post = data["post"]

    preview = orig_post.text or orig_post.caption or "[медиа]"
    if len(preview) > 30:
        preview = preview[:30] + "..."

    task = {
        "time": dt,
        "post": orig_post,
        "preview": preview
    }
    scheduled_tasks[user_id].append(task)

    await message.answer(f"Запланировано на {dt.strftime('%d.%m %H:%M')} (МСК)\n"
                         f"Позиция в очереди: {len(scheduled_tasks[user_id])}")

    await asyncio.sleep(delay)

    # Публикация
    await orig_post.copy_to(CHANNEL_ID)
    await bot.send_message(user_id, f"Пост опубликован!\nВремя: {dt.strftime('%H:%M %d.%m.%Y')} МСК")

    # Удаляем из очереди
    scheduled_tasks[user_id].remove(task)

    await state.clear()

# (остальной код парсинга времени — вставь из предыдущей версии, чтобы не повторять)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
