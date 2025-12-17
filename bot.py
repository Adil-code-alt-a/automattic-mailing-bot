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
        scheduled_tasks = {int(k): v for k, v in saved.get("tasks", {}).items()}
        user_channels = {int(k): v for k, v in saved.get("channels", {}).items()}
    except Exception as e:
        print(f"Ошибка загрузки queue.json: {e}")
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
    except Exception as e:
        print(f"Ошибка сохранения queue.json: {e}")

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
        "Напиши пост (текст, фото, видео, эмодзи) — я приму.\n"
        "Потом напиши время публикации.\n\n"
        "Примеры времени:\n"
        "• через 15 мин\n"
        "• через 2 часа\n"
        "• сегодня 8:00\n"
        "• в 15:30\n"
        "• 8:00 (сегодня или завтра)\n"
        "• завтра 7:00\n"
        "• завтра 23:59\n"
        "• 18.12.2025 14:30\n\n"
        "Команды:\n"
        "/list — очередь постов\n"
        "/status — статус и канал\n"
        "/setchannel — сменить канал\n"
        "/cancel <номер> — отменить пост\n"
        "/now — опубликовать текущий пост сразу\n"
        "/help — эта справка"
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
        preview = task["preview"]
        text += f"{i}. {dt.strftime('%d.%m %H:%M')} — {preview}\n"
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
    text = message.text.strip()
    lower_text = text.lower()
    now = datetime.now(moscow_tz)
    dt = None

    # "через X"
    if "через" in lower_text:
        mins = re.search(r"(\d+)\s*(мин|минут|м)", lower_text)
        hours = re.search(r"(\d+)\s*(час|часа|ч)", lower_text)
        if mins:
            dt = now + timedelta(minutes=int(mins.group(1)))
        elif hours:
            dt = now + timedelta(hours=int(hours.group(1)))
        else:
            await message.reply("Не понял количество минут или часов")
            return

    # "завтра" + время
    elif "завтра" in lower_text:
        tomorrow = now + timedelta(days=1)
        time_match = re.search(r"(\d{1,2}):(\d{2})", text)
        if time_match:
            h = int(time_match.group(1))
            m = int(time_match.group(2))
            dt = tomorrow.replace(hour=h, minute=m, second=0, microsecond=0)
        else:
            await message.reply("Укажи время после 'завтра', например: завтра 7:00")
            return

    # "сегодня" + время или "в " + время или просто время "8:07"
    elif "сегодня" in lower_text or "в " in lower_text or re.match(r"^\d{1,2}:\d{2}$", text.strip()):
        time_match = re.search(r"(\d{1,2}):(\d{2})", text)
        if time_match:
            h = int(time_match.group(1))
            m = int(time_match.group(2))
            dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if dt < now - timedelta(minutes=1):  # если время уже сильно прошло — на завтра
                dt += timedelta(days=1)
        else:
            await message.reply("Укажи время, например: сегодня 8:07 или 8:07")
            return

    # Полная дата + время
    else:
        try:
            naive_dt = datetime.strptime(text, "%d.%m.%Y %H:%M")
            dt = naive_dt.replace(tzinfo=moscow_tz)
        except ValueError:
            await message.reply(
                "Не понял время.\n"
                "Примеры:\n"
                "через 15 мин\n"
                "сегодня 8:07\n"
                "в 8:07\n"
                "8:07\n"
                "завтра 7:00\n"
                "18.12.2025 14:30"
            )
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

    await asyncio.sleep(delay)

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
        del tasks[task_index]
        await save_state()
    elif action == "can":
        del tasks[task_index]
        await save_state()
        await callback.message.edit_text(callback.message.text + "\n\nПост отменён")
    elif action == "chg":
        await callback.message.edit_text(callback.message.text + "\n\nНапиши новое время для этого поста")

    await callback.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
