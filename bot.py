import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import web

# ---------------- CONFIG ----------------

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

DEFAULT_CHANNEL_ID = "-1003452189598"
QUEUE_FILE = "/data/queue.json"
moscow_tz = ZoneInfo("Europe/Moscow")

bot = Bot(TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ---------------- STORAGE ----------------

scheduled_tasks: dict[int, list] = {}
user_channels: dict[int, str] = {}

if os.path.exists(QUEUE_FILE):
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        scheduled_tasks = {int(k): v for k, v in data.get("tasks", {}).items()}
        user_channels = {int(k): v for k, v in data.get("channels", {}).items()}
        logging.info("Очередь загружена")
    except Exception as e:
        logging.error(f"Ошибка загрузки: {e}")

async def save_state():
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"tasks": scheduled_tasks, "channels": user_channels},
            f,
            ensure_ascii=False
        )

def get_channel(user_id: int) -> str:
    return user_channels.get(user_id, DEFAULT_CHANNEL_ID)

# ---------------- COMMANDS ----------------

@dp.message(CommandStart())
@dp.message(Command("help"))
async def start(message: types.Message):
    await message.answer(
        "Напишите пост → затем время.\n\n"
        "Примеры:\n"
        "через 15 мин\n"
        "завтра 12:00\n"
        "31.12.2025 23:59\n\n"
        "/list — очередь\n"
        "/cancel <номер>"
    )

@dp.message(Command("list"))
async def list_cmd(message: types.Message):
    tasks = scheduled_tasks.get(message.from_user.id, [])
    if not tasks:
        await message.answer("Очередь пуста")
        return

    text = "Очередь:\n\n"
    for i, t in enumerate(tasks, 1):
        dt = datetime.fromisoformat(t["time"])
        text += f"{i}. {dt:%d.%m %H:%M} — {t['preview']}\n"

    await message.answer(text)

@dp.message(Command("cancel"))
async def cancel_cmd(message: types.Message):
    try:
        idx = int(message.text.split()[1]) - 1
        scheduled_tasks[message.from_user.id].pop(idx)
        await save_state()
        await message.answer("Пост отменён")
    except Exception:
        await message.answer("Использование: /cancel <номер>")

# ---------------- POST FLOW ----------------

@dp.message()
async def handle_message(message: types.Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        return

    data = await state.get_data()

    # Ввод времени
    if "post" in data:
        await process_time(message, data["post"])
        await state.clear()
        return

    # Новый пост
    preview = message.text or message.caption or "[медиа]"
    preview = preview[:40] + "..." if len(preview) > 40 else preview

    await state.update_data(post={
        "chat_id": message.chat.id,
        "message_id": message.message_id,
        "preview": preview
    })

    await message.answer("Пост принят. Укажите время публикации")

# ---------------- TIME PARSER ----------------

async def process_time(message: types.Message, post: dict):
    text = message.text.lower()
    now = datetime.now(moscow_tz)
    dt = None

    if "через" in text:
        if m := re.search(r"(\d+)\s*мин", text):
            dt = now + timedelta(minutes=int(m.group(1)))
        elif h := re.search(r"(\d+)\s*час", text):
            dt = now + timedelta(hours=int(h.group(1)))

    elif "завтра" in text:
        if t := re.search(r"(\d{1,2}):(\d{2})", text):
            dt = (now + timedelta(days=1)).replace(
                hour=int(t.group(1)),
                minute=int(t.group(2)),
                second=0,
                microsecond=0
            )

    else:
        try:
            dt = datetime.strptime(text, "%d.%m.%Y %H:%M").replace(tzinfo=moscow_tz)
        except:
            if t := re.search(r"(\d{1,2}):(\d{2})", text):
                dt = now.replace(
                    hour=int(t.group(1)),
                    minute=int(t.group(2)),
                    second=0,
                    microsecond=0
                )
                if dt < now:
                    dt += timedelta(days=1)

    if not dt or dt < now:
        await message.answer("Не понял время")
        return

    task = {
        "time": dt.isoformat(),
        "chat_id": post["chat_id"],
        "message_id": post["message_id"],
        "preview": post["preview"]
    }

    scheduled_tasks.setdefault(message.from_user.id, []).append(task)
    await save_state()

    asyncio.create_task(publish_task(message.from_user.id, task))
    await message.answer(f"Запланировано на {dt:%d.%m %H:%M}")

# ---------------- PUBLISHER ----------------

async def publish_task(user_id: int, task: dict):
    dt = datetime.fromisoformat(task["time"])
    while (delay := (dt - datetime.now(moscow_tz)).total_seconds()) > 0:
        await asyncio.sleep(min(delay, 60))

    await bot.copy_message(
        chat_id=get_channel(user_id),
        from_chat_id=task["chat_id"],
        message_id=task["message_id"]
    )

    scheduled_tasks[user_id].remove(task)
    await save_state()
    await bot.send_message(user_id, "Пост опубликован")

# ---------------- WEBHOOK ----------------

async def on_startup(app):
    for user_id, tasks in scheduled_tasks.items():
        for task in tasks:
            asyncio.create_task(publish_task(user_id, task))

    await bot.set_webhook(WEBHOOK_URL)
    logging.info("Webhook установлен")

app = web.Application()
SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
app.on_startup.append(on_startup)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
