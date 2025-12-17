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

# Очередь постов: user_id → список задач
scheduled_tasks = {}

class Form(StatesGroup):
    waiting_time = State()

# Кнопки для поста
def get_task_keyboard(task_index: int):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton("Опубликовать сейчас", callback_data=f"pub_{task_index}"),
            types.InlineKeyboardButton("Отменить", callback_data=f"can_{task_index}")
        ],
        [
            types.InlineKeyboardButton("Изменить время", callback_data=f"chg_{task_index}")
        ]
    ])
    return keyboard

@dp.message(CommandStart())
async def start(message: types.Message):
    now = datetime.now(moscow_tz)
    await message.answer(
        f"Привет! Время МСК: {now.strftime('%H:%M %d.%m.%Y')}\n\n"
        "Как использовать:\n"
        "1. Напиши пост (текст, фото, видео, эмодзи)\n"
        "2. Напиши время публикации\n\n"
        "Примеры:\n"
        "• через 15 мин\n"
        "• завтра 7:00\n"
        "• завтра 14:30\n"
        "• завтра в 23:59\n"
        "• 18.12.2025 10:15\n\n"
        "Команды:\n"
        "/list — очередь постов\n"
        "/cancel <номер> — отменить\n"
        "/now — опубликовать сразу"
    )

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
    await post.copy_to(CHANNEL_ID)
    await message.answer("Пост опубликован сразу в канал!")
    await state.clear()

@dp.message()
async def receive_post(message: types.Message, state: FSMContext):
    current = await state.get_state()
    if current == Form.waiting_time.state:
        await process_time(message, state)
        return

    # Новый пост
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

    # "через X"
    if "через" in text:
        mins = re.search(r"(\d+)\s*(мин|минут|м)", text)
        hours = re.search(r"(\d+)\s*(час|часа|ч)", text)
        if mins:
            dt = now + timedelta(minutes=int(mins.group(1)))
        elif hours:
            dt = now + timedelta(hours=int(hours.group(1)))
        else:
            await message.reply("Не понял количество минут или часов")
            return

    # "завтра" + время (любое)
    elif "завтра" in text:
        tomorrow = now + timedelta(days=1)
        time_match = re.search(r"(\d{1,2}):(\d{2})", text)
        if time_match:
            h = int(time_match.group(1))
            m = int(time_match.group(2))
            dt = tomorrow.replace(hour=h, minute=m, second=0, microsecond=0)
        else:
            await message.reply("Укажи время после 'завтра', например: завтра 7:00")
            return

    # Полная дата
    else:
        try:
            naive_dt = datetime.strptime(text, "%d.%m.%Y %H:%M")
            dt = naive_dt.replace(tzinfo=moscow_tz)
        except ValueError:
            await message.reply(
                "Не понял время.\n"
                "Примеры:\n"
                "через 15 мин\n"
                "завтра 7:00\n"
                "завтра 14:30\n"
                "18.12.2025 10:15"
            )
            return

    if dt <= now:
        await message.reply("Время уже прошло или равно текущему!")
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

    keyboard = get_task_keyboard(task_index)

    await message.reply(
        f"Принято в работу! ✅\n"
        f"Запланировано на {dt.strftime('%d.%m.%Y %H:%M')} (МСК)\n"
        f"Осталось: {hours_left} ч {mins_left} мин\n"
        f"Позиция в очереди: {len(scheduled_tasks[user_id])}",
        reply_markup=keyboard
    )

    await asyncio.sleep(delay)

    await orig_post.copy_to(CHANNEL_ID)
    await bot.send_message(user_id, f"Пост опубликован в канал!\nВремя: {dt.strftime('%H:%M %d.%m.%Y')} МСК")

    scheduled_tasks[user_id].remove(task)
    await state.clear()

@dp.callback_query(lambda c: c.data and c.data.startswith(('pub_', 'can_', 'chg_')))
async def process_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    action, index_str = callback.data.split('_')
    index = int(index_str)

    tasks = scheduled_tasks.get(user_id, [])
    if index >= len(tasks):
        await callback.answer("Пост уже обработан")
        return

    task = tasks[index]

    if action == "pub":
        await task["post"].copy_to(CHANNEL_ID)
        await callback.message.edit_text(callback.message.text + "\n\nПост опубликован сейчас!")
        tasks.remove(task)
    elif action == "can":
        tasks.remove(task)
        await callback.message.edit_text(callback.message.text + "\n\nПост отменён")
    elif action == "chg":
        await callback.message.edit_text(callback.message.text + "\n\nНапиши новое время для этого поста")

    await callback.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
