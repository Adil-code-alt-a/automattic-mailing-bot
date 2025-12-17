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

TOKEN = os.getenv("TOKEN", "8560527789:AAF8r9Eo7MfIergU-OqhUW0hIi07hf1myAo")
DEFAULT_CHANNEL_ID = "-1003452189598"

moscow_tz = ZoneInfo("Europe/Moscow")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

QUEUE_FILE = "queue.json"

# Загрузка состояния
if os.path.exists(QUEUE_FILE):
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        scheduled_tasks = {int(k): [task for task in v if task] for k, v in saved.get("tasks", {}).items()}
        user_channels = {int(k): v for k, v in saved.get("channels", {}).items()}
    except Exception:
        scheduled_tasks = {}
        user_channels = {}
else:
    scheduled_tasks = {}
    user_channels = {}

def get_user_channel(user_id: int) -> str:
    return user_channels.get(user_id, DEFAULT_CHANNEL_ID)

async def save_state():
    try:
        data = {
            "tasks": {str(k): v for k, v in scheduled_tasks.items()},
            "channels": {str(k): v for k, v in user_channels.items()}
        }
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, default=str)
    except Exception:
        pass  # если не удалось сохранить — продолжаем работать

class Form(StatesGroup):
    waiting_time = State()
    setting_channel = State()

def get_task_keyboard(user_id: int, task_index: int):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton("Опубликовать сейчас", callback_data=f"pub_{user_id}_{task_index}"),
            types.InlineKeyboardButton("Отменить", callback_data=f"can_{user_id}_{task_index}")
        ],
        [
            types.InlineKeyboardButton("Изменить время", callback_data=f"chg_{user_id}_{task_index}")
        ]
    ])
    return keyboard

@dp.message(CommandStart())
async def start(message: types.Message):
    now = datetime.now(moscow_tz)
    await message.answer(
        f"Привет! Время МСК: {now.strftime('%H:%M %d.%m.%Y')}\n\n"
        "Я твой планировщик постов в канал.\n\n"
        "Как использовать:\n"
        "• Напиши пост (текст, фото, видео, эмодзи)\n"
        "• Напиши время\n\n"
        "Поддерживаю повторения:\n"
        "• каждый день 09:00\n"
        "• каждую пятницу 18:00\n"
        "• 1-го числа 10:00\n\n"
        "Команды:\n"
        "/list — очередь\n"
        "/status — статус\n"
        "/setchannel — сменить канал\n"
        "/cancel <номер>\n"
        "/now — сразу\n"
        "/help — справка"
    )

@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    await start(message)

@dp.message(Command("status"))
async def status(message: types.Message):
    user_id = message.from_user.id
    tasks_count = len(scheduled_tasks.get(user_id, []))
    channel = get_user_channel(user_id)
    await message.answer(
        f"Статус:\n"
        f"Канал: {channel}\n"
        f"Постов в очереди: {tasks_count}\n"
        f"Максимум: 20"
    )

@dp.message(Command("setchannel"))
async def set_channel(message: types.Message, state: FSMContext):
    await state.set_state(Form.setting_channel)
    await message.answer("Перешли мне любое сообщение из нужного канала")

@dp.message(Form.setting_channel)
async def process_channel(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.forward_from_chat and message.forward_from_chat.type in ["channel", "supergroup"]:
        new_channel = str(message.forward_from_chat.id)
        user_channels[user_id] = new_channel
        await save_state()
        await message.answer(f"Канал изменён на {new_channel}")
    else:
        await message.answer("Не распознал канал. Перешли сообщение из канала")
    await state.clear()

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
        repeat = " (повтор)" if task.get("repeat") else ""
        preview = task["preview"]
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
            await save_state()
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
    if current == Form.waiting_time.state:
        await process_time(message, state)
        return

    user_id = message.from_user.id
    if len(scheduled_tasks.get(user_id, [])) >= 20:
        await message.answer("Очередь полная (максимум 20 постов)")
        return

    await state.set_state(Form.waiting_time)
    await state.update_data(post=message)

    preview = message.text or message.caption or "[медиа]"
    if len(preview) > 40:
        preview = preview[:40] + "..."

    await message.reply(f"Пост принят: \"{preview}\"\nТеперь напиши время публикации")

async def process_time(message: types.Message, state: FSMContext):
    text = message.text.strip().lower()
    now = datetime.now(moscow_tz)
    dt = None
    repeat = None

    # Повторяющиеся
    if "каждый день" in text or "ежедневно" in text:
        repeat = "daily"
        m = re.search(r"(\d{1,2}):(\d{2})", text)
        if m:
            h, m = int(m.group(1)), int(m.group(2))
            dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if dt <= now:
                dt += timedelta(days=1)
    elif "каждую пятницу" in text:
        repeat = "friday"
        m = re.search(r"(\d{1,2}):(\d{2})", text)
        h, m = 18, 0
        if m:
            h, m = int(m.group(1)), int(m.group(2))
        days_ahead = (4 - now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        dt = (now + timedelta(days=days_ahead)).replace(hour=h, minute=m, second=0, microsecond=0)
    elif "1-го числа" in text or "первого числа" in text:
        repeat = "monthly"
        m = re.search(r"(\d{1,2}):(\d{2})", text)
        h, m = 10, 0
        if m:
            h, m = int(m.group(1)), int(m.group(2))
        next_month = now.replace(day=28) + timedelta(days=4)
        dt = next_month.replace(day=1, hour=h, minute=m, second=0, microsecond=0)

    # Обычное время
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
            m = re.search(r"(\d{1,2}):(\d{2})", text)
            if m:
                h, m = int(m.group(1)), int(m.group(2))
                dt = dt.replace(hour=h, minute=m)
            else:
                dt = dt.replace(hour=9, minute=0)
        else:
            try:
                naive_dt = datetime.strptime(text, "%d.%m.%Y %H:%M")
                dt = naive_dt.replace(tzinfo=moscow_tz)
            except ValueError:
                await message.reply("Не понял время. Примеры:\nчерез 15 мин\nзавтра 7:00\n18.12.2025 14:30\nкаждый день 09:00")
                return

    if dt <= now and not repeat:
        await message.reply("Время уже прошло!")
        return

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
    task_index = len(scheduled_tasks[user_id]) - 1

    keyboard = get_task_keyboard(user_id, task_index)

    hours_left = 0
    mins_left = 0
    if not repeat:
        delay = int((dt - now).total_seconds())
        hours_left = delay // 3600
        mins_left = (delay % 3600) // 60

    repeat_text = " (повторяющийся)" if repeat else ""

    await message.reply(
        f"Принято в работу! ✅\n"
        f"Запланировано на {dt.strftime('%d.%m %H:%M')} (МСК){repeat_text}\n"
        f"Осталось: {hours_left} ч {mins_left} мин\n"
        f"Позиция в очереди: {len(scheduled_tasks[user_id])}",
        reply_markup=keyboard
    )

    await save_state()

    if not repeat:
        await asyncio.sleep(int((dt - now).total_seconds()))

        channel = get_user_channel(user_id)
        sent = await orig_post.copy_to(channel)
        link = f"https://t.me/c/{str(channel)[4:]}/{sent.message_id}"

        await bot.send_message(user_id, f"Пост опубликован!\n{link}\nВремя: {dt.strftime('%H:%M %d.%m.%Y')} МСК")

        scheduled_tasks[user_id].remove(task)
        await save_state()

@dp.callback_query(lambda c: c.data and c.data.startswith(('pub_', 'can_', 'chg_')))
async def callback_buttons(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    data = callback.data.split('_')
    action = data[0]
    task_user = int(data[1])
    task_index = int(data[2])

    if task_user != user_id:
        await callback.answer("Это не твой пост")
        return

    tasks = scheduled_tasks.get(user_id, [])
    if task_index >= len(tasks):
        await callback.answer("Пост уже обработан")
        return

    task = tasks[task_index]
    channel = get_user_channel(user_id)

    if action == "pub":
        sent = await task["post"].copy_to(channel)
        link = f"https://t.me/c/{str(channel)[4:]}/{sent.message_id}"
        await callback.message.edit_text(callback.message.text + f"\n\nПост опубликован сейчас!\n{link}")
        if not task.get("repeat"):
            del tasks[task_index]
            await save_state()
    elif action == "can":
        del tasks[task_index]
        await save_state()
        await callback.message.edit_text(callback.message.text + "\n\nПост отменён")
    elif action == "chg":
        await callback.message.edit_text(callback.message.text + "\n\nНапиши новое время для этого поста")
        # Можно добавить полноценное редактирование позже

    await callback.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
