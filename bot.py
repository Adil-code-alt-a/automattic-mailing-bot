from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import web
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import asyncio
import re
import os
import json
import logging

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TOKEN", "YOUR_TOKEN_HERE")
DEFAULT_CHANNEL_ID = "-100YOUR_CHANNEL_ID"

WEBHOOK_HOST = "https://your-project.up.railway.app"
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

moscow_tz = ZoneInfo("Europe/Moscow")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

QUEUE_FILE = "/data/queue.json"

if os.path.exists(QUEUE_FILE):
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        scheduled_tasks = {int(k): v for k, v in saved.get("tasks", {}).items()}
        user_channels = {int(k): v for k, v in saved.get("channels", {}).items()}
    except:
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
    except:
        pass

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
@dp.message(Command("help"))
async def start(message: types.Message):
    now = datetime.now(moscow_tz)
    await message.answer(
        f"Привет! Текущее время МСК: {now.strftime('%H:%M %d.%m.%Y')}\n\n"
        "Я — ваш личный планировщик постов в Telegram-канал.\n\n"
        "Как использовать:\n"
        "1. Напишите пост (текст, фото, видео, эмодзи — всё сразу)\n"
        "2. Укажите время публикации\n\n"
        "Поддерживаемые форматы времени:\n"
        "• через 15 мин\n"
        "• через 2 часа\n"
        "• сегодня 8:00\n"
        "• в 15:30\n"
        "• 8:00 (сегодня или завтра)\n"
        "• завтра 7:00\n"
        "• завтра 23:59\n"
        "• 31.12.2025 23:59\n"
        "• 01.01.2026 00:01\n\n"
        "Команды:\n"
        "/list — посмотреть очередь постов\n"
        "/status — статус и текущий канал\n"
        "/setchannel — сменить канал публикации\n"
        "/cancel <номер> — отменить пост\n"
        "/now — опубликовать текущий пост сразу\n"
        "/help — эта справка"
    )

# (Остальные команды /status, /setchannel, /list, /cancel, /now — как в вашем коде)

# Приём поста
@dp.message()
async def receive_post(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if "post" in data:
        await process_time(message, state)
        return

    if message.text and message.text.startswith('/'):
        return

    user_id = message.from_user.id
    if len(scheduled_tasks.get(user_id, [])) >= 20:
        await message.answer("Очередь полная (максимум 20 постов)")
        return

    await state.update_data(post=message)

    preview = message.text or message.caption or "[медиа]"
    if len(preview) > 40:
        preview = preview[:40] + "..."

    await message.reply(f"Пост принят: \"{preview}\"\nТеперь укажите время публикации")

# Обработка времени
async def process_time(message: types.Message, state: FSMContext):
    text = message.text.strip()
    lower_text = text.lower()
    now = datetime.now(moscow_tz)
    dt = None

    if "через" in lower_text:
        mins_match = re.search(r"(\d+)\s*(мин|минут|минуту|минуты|м)", lower_text)
        hours_match = re.search(r"(\d+)\s*(час|часа|часов|ч)", lower_text)
        if mins_match:
            dt = now + timedelta(minutes=int(mins_match.group(1)))
        elif hours_match:
            dt = now + timedelta(hours=int(hours_match.group(1)))
        else:
            await message.reply("Не понял количество")
            return

    elif "завтра" in lower_text:
        tomorrow = now + timedelta(days=1)
        time_match = re.search(r"(\d{1,2}):(\d{2})", text)
        if time_match:
            h = int(time_match.group(1))
            m = int(time_match.group(2))
            dt = tomorrow.replace(hour=h, minute=m, second=0, microsecond=0)
        else:
            await message.reply("Укажите время после 'завтра'")
            return

    elif "сегодня" in lower_text or "в " in lower_text or re.match(r"^\d{1,2}:\d{2}$", text.strip()):
        time_match = re.search(r"(\d{1,2}):(\d{2})", text)
        if time_match:
            h = int(time_match.group(1))
            m = int(time_match.group(2))
            dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if dt < now - timedelta(minutes=1):
                dt += timedelta(days=1)
        else:
            await message.reply("Укажите время")
            return

    else:
        try:
            naive_dt = datetime.strptime(text, "%d.%m.%Y %H:%M")
            dt = naive_dt.replace(tzinfo=moscow_tz)
        except ValueError:
            await message.reply("Не понял время")
            return

    if dt < now - timedelta(minutes=1):
        await message.reply("Время уже прошло!")
        return

    delay = int((dt - now).total_seconds())
    hours_left = delay // 3600
    mins_left = (delay % 3600) // 60

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
        "preview": preview
    }
    scheduled_tasks[user_id].append(task)
    task_index = len(scheduled_tasks[user_id]) - 1

    keyboard = get_task_keyboard(user_id, task_index)

    await message.reply(
        f"Принято в работу! ✅\n"
        f"Запланировано на {dt.strftime('%d.%m.%Y %H:%M')} (МСК)\n"
        f"Осталось: {hours_left} ч {mins_left} мин\n"
        f"Позиция в очереди: {len(scheduled_tasks[user_id])}",
        reply_markup=keyboard
    )

    await save_state()

    asyncio.create_task(publish_task(task, user_id))

    await state.clear()

# Остальные функции (publish_task, callback_buttons, webhook) — как в вашем последнем коде

# Webhook сервер
app = web.Application()
SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)

async def on_startup(app):
    try:
        await bot.set_webhook(WEBHOOK_URL)
        logging.info(f"Webhook установлен: {WEBHOOK_URL}")
    except Exception as e:
        logging.error(f"Ошибка установки webhook: {e}")

async def on_shutdown(app):
    try:
        await bot.delete_webhook()
        logging.info("Webhook удалён")
    except Exception as e:
        logging.error(f"Ошибка удаления webhook: {e}")

app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
