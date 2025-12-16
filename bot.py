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
import json
import pathlib

TOKEN = os.getenv("TOKEN", "8560527789:AAF8r9Eo7MfIergU-OqhUW0hIi07hf1myAo")

# По умолчанию твой канал. Можно изменить через /setchannel
DEFAULT_CHANNEL_ID = "-1003452189598"

moscow_tz = ZoneInfo("Europe/Moscow")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Файл для сохранения очереди и настроек
QUEUE_FILE = "queue.json"

# Загружаем сохранённое состояние
if os.path.exists(QUEUE_FILE):
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    scheduled_tasks = saved_data.get("tasks", {})
    user_channels = saved_data.get("channels", {})
else:
    scheduled_tasks = {}
    user_channels = {}

# Словарь для текущего канала пользователя
def get_user_channel(user_id):
    return user_channels.get(user_id, DEFAULT_CHANNEL_ID)

class Form(StatesGroup):
    waiting_time = State()
    changing_time = State()

# Сохранение очереди в файл
async def save_queue():
    data = {
        "tasks": scheduled_tasks,
        "channels": user_channels
    }
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)

# Клавиатура с кнопками после планирования
def get_task_keyboard(task_index):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("Опубликовать сейчас", callback_data=f"publish_{task_index}"),
        types.InlineKeyboardButton("Отменить", callback_data=f"cancel_{task_index}")
    )
    keyboard.add(
        types.InlineKeyboardButton("Изменить время", callback_data=f"change_{task_index}")
    )
    return keyboard

@dp.message(CommandStart())
async def start(message: types.Message):
    now = datetime.now(moscow_tz)
    await message.answer(
        f"Привет! Время МСК: {now.strftime('%H:%M %d.%m.%Y')}\n\n"
        "Я твой личный планировщик постов в канал.\n\n"
        "Как использовать:\n"
        "• Напиши пост (текст, фото, видео, эмодзи)\n"
        "• Укажи время (примеры ниже)\n\n"
        "Поддерживаю повторения:\n"
        "• каждый день 09:00\n"
        "• каждую пятницу 18:00\n"
        "• 1-го числа 10:00\n\n"
        "Команды:\n"
        "/list — очередь постов\n"
        "/cancel <номер> — отменить\n"
        "/now — опубликовать сразу\n"
        "/setchannel — изменить канал\n"
        "/help — эта справка"
    )

@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    await start(message)

@dp.message(Command("status"))
async def status(message: types.Message):
    user_id = message.from_user.id
    tasks = scheduled_tasks.get(user_id, [])
    channel = get_user_channel(user_id)
    await message.answer(
        f"Статус:\n"
        f"Канал: {channel}\n"
        f"Постов в очереди: {len(tasks)}\n"
        f"Макс. очередь: 20"
    )

@dp.message(Command("setchannel"))
async def set_channel(message: types.Message):
    await message.answer("Перешли мне любое сообщение из нужного канала (или отправь ссылку на канал)")
    # Реализация простая — можно улучшить, если нужно

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    user_id = message.from_user.id
    tasks = scheduled_tasks.get(user_id, [])
    if not tasks:
        await message.answer("Очередь пуста")
        return
    text = "Твоя очередь постов:\n\n"
    for i, task in enumerate(tasks, 1):
        dt = task["time"]
        preview = task["preview"]
        repeat = " (повтор)" if task.get("repeat") else ""
        text += f"{i}. {dt.strftime('%d.%m %H:%M')}{repeat} — {preview}\n"
    await message.answer(text)

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message):
    try:
        num = int(message.text.split(maxsplit=1)[1]) - 1
        user_id = message.from_user.id
        tasks = scheduled_tasks.get(user_id, [])
        if 0 <= num < len(tasks):
            del tasks[num]
            await save_queue()
            await message.answer(f"Пост №{num + 1} отменён")
        else:
            await message.answer("Неверный номер")
    except:
        await message.answer("Использование: /cancel <номер из /list>")

@dp.message(Command("now"))
async def cmd_now(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if "post" not in data:
        await message.answer("Сначала отправь пост")
        return
    post = data["post"]
    channel = get_user_channel(message.from_user.id)
    sent = await post.copy_to(channel)
    link = f"https://t.me/c/{str(channel)[4:]}/{sent.message_id}"
    await message.answer(f"Пост опубликован сразу!\n{link}")
    await state.clear()

@dp.message()
async def receive_post(message: types.Message, state: FSMContext):
    current = await state.get_state()
    if current == Form.waiting_time.state or current == Form.changing_time.state:
        await process_time(message, state)
        return

    # Новый пост
    if len(scheduled_tasks.get(message.from_user.id, [])) >= 20:
        await message.answer("Очередь полная (макс. 20 постов)")
        return

    await state.set_state(Form.waiting_time)
    await state.update_data(post=message)

    preview = message.text or message.caption or "[медиа]"
    if len(preview) > 40:
        preview = preview[:40] + "..."

    await message.reply(f"Пост принят: \"{preview}\"\nТеперь напиши время (или 'каждый день 09:00' для повтора)")

async def process_time(message: types.Message, state: FSMContext):
    text = message.text.strip().lower()
    now = datetime.now(moscow_tz)
    dt = None
    repeat = None

    # Повторяющиеся
    if "каждый день" in text or "ежедневно" in text:
        repeat = "daily"
        time_match = re.search(r"(\d{1,2}):(\d{2})", text)
        if time_match:
            h, m = int(time_match.group(1)), int(time_match.group(2))
            dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if dt <= now:
                dt += timedelta(days=1)
    elif "каждую" in text and "пятницу" in text:
        repeat = "friday"
        time_match = re.search(r"(\d{1,2}):(\d{2})", text)
        h, m = 18, 0
        if time_match:
            h, m = int(time_match.group(1)), int(time_match.group(2))
        weekday = now.weekday()
        days_ahead = (4 - weekday) % 7
        if days_ahead == 0:
            days_ahead = 7
        dt = (now + timedelta(days=days_ahead)).replace(hour=h, minute=m, second=0, microsecond=0)
    elif "1-го числа" in text or "первого числа" in text:
        repeat = "monthly"
        time_match = re.search(r"(\d{1,2}):(\d{2})", text)
        h, m = 10, 0
        if time_match:
            h, m = int(time_match.group(1)), int(time_match.group(2))
        next_month = now.replace(day=1) + timedelta(days=32)
        dt = next_month.replace(day=1, hour=h, minute=m, second=0, microsecond=0)

    # Обычные
    if not dt:
        if "через" in text:
            mins = re.search(r"(\d+)\s*(мин|минут|м)", text)
            hours = re.search(r"(\d+)\s*(час|часа|ч)", text)
            if mins:
                dt = now + timedelta(minutes=int(mins.group(1)))
            elif hours:
                dt = now + timedelta(hours=int(hours.group(1)))
        elif "завтра" in text:
            dt = now + timedelta(days=1)
            time_match = re.search(r"(\d{1,2}):(\d{2})", text)
            if time_match:
                h, m = int(time_match.group(1)), int(time_match.group(2))
                dt = dt.replace(hour=h, minute=m)
            else:
                dt = dt.replace(hour=9, minute=0)
        else:
            try:
                naive_dt = datetime.strptime(text, "%d.%m.%Y %H:%M")
                dt = naive_dt.replace(tzinfo=moscow_tz)
            except:
                await message.reply("Не понял время. Примеры:\nчерез 15 мин\nзавтра 10:00\n17.12.2025 14:30\nкаждый день 09:00")
                return

    if dt <= now and not repeat:
        await message.reply("Время уже прошло!")
        return

    delay = int((dt - now).total_seconds()) if not repeat else None

    user_id = message.from_user.id
    if user_id not in scheduled_tasks:
        scheduled_tasks[user_id] = []

    data = await state.get_data()
    orig_post = data["post"]

    preview = orig_post.text or orig_post.caption or "[медиа]"
    if len(preview) > 40:
        preview = preview[:40] + "..."

    task = {
        "time": dt,
        "post": orig_post,
        "preview": preview,
        "repeat": repeat
    }
    scheduled_tasks[user_id].append(task)
    position = len(scheduled_tasks[user_id])

    keyboard = get_task_keyboard(position - 1)

    hours_left = delay // 3600 if delay else 0
    mins_left = (delay % 3600) // 60 if delay else 0

    repeat_text = " (с повторением)" if repeat else ""

    await message.reply(
        f"Запланировано на {dt.strftime('%d.%m.%Y %H:%M')} (МСК){repeat_text}\n"
        f"Осталось: {hours_left} ч {mins_left} мин\n"
        f"Позиция: {position}",
        reply_markup=keyboard
    )

    await save_queue()

    if delay:
        await asyncio.sleep(delay)

        channel = get_user_channel(user_id)
        sent = await orig_post.copy_to(channel)
        link = f"https://t.me/c/{str(channel)[4:]}/{sent.message_id}"

        await bot.send_message(user_id, f"Пост опубликован!\n{link}\nВремя: {dt.strftime('%H:%M %d.%m.%Y')} МСК")

        if repeat:
            # Создаём новый пост на следующий период
            new_dt = dt + timedelta(days=1 if repeat == "daily" else 7 if repeat == "friday" else 31 if repeat == "monthly" else 0)
            new_task = task.copy()
            new_task["time"] = new_dt
            scheduled_tasks[user_id].append(new_task)
            await save_queue()
        else:
            scheduled_tasks[user_id].remove(task)
            await save_queue()

    await state.clear()

# Обработка кнопок
@dp.callback_query(lambda c: c.data.startswith("publish_") or c.data.startswith("cancel_") or c.data.startswith("change_"))
async def callback_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    tasks = scheduled_tasks.get(user_id, [])
    action, index = callback.data.split("_")
    index = int(index)

    if index >= len(tasks):
        await callback.answer("Пост уже обработан")
        return

    task = tasks[index]
    channel = get_user_channel(user_id)

    if action == "publish":
        sent = await task["post"].copy_to(channel)
        link = f"https://t.me/c/{str(channel)[4:]}/{sent.message_id}"
        await callback.message.edit_text(f"Пост опубликован сразу!\n{link}")
        if not task.get("repeat"):
            del tasks[index]
            await save_queue()
    elif action == "cancel":
        del tasks[index]
        await save_queue()
        await callback.message.edit_text("Пост отменён")
    elif action == "change":
        await callback.message.edit_text("Напиши новое время для этого поста")
        # Здесь можно добавить состояние, но для простоты просто удалим и попросим заново

    await callback.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
