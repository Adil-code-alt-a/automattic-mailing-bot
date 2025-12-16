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

# Токен и ID канала
TOKEN = os.getenv("TOKEN", "8560527789:AAF8r9Eo7MfIergU-OqhUW0hIi07hf1myAo")
CHANNEL_ID = "-1003452189598"  # Если нужно изменить — меняй здесь

# Московское время — всегда точно
moscow_tz = ZoneInfo("Europe/Moscow")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Очередь запланированных постов: user_id → список задач
scheduled_tasks = {}

class Form(StatesGroup):
    waiting_time = State()

@dp.message(CommandStart())
async def start(message: types.Message):
    now = datetime.now(moscow_tz)
    await message.answer(
        f"Привет! Текущее время МСК: {now.strftime('%H:%M %d.%m.%Y')}\n\n"
        "Как пользоваться:\n"
        "1. Напиши мне пост (текст, фото, видео, эмодзи — всё сразу)\n"
        "2. Напиши время публикации\n\n"
        "Примеры времени:\n"
        "• через 15 мин\n"
        "• через 2 часа\n"
        "• завтра 10:00\n"
        "• 17.12.2025 14:30\n\n"
        "Команды:\n"
        "/list — посмотреть очередь постов\n"
        "/cancel <номер> — отменить пост\n"
        "/now — опубликовать текущий пост сразу"
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
    await message.answer("Пост опубликован в канал сразу!")
    await state.clear()

@dp.message()
async def receive_post(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == Form.waiting_time.state:
        await process_time(message, state)
        return

    # Принимаем новый пост (текст, фото, видео, эмодзи — всё)
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

    # "через X мин/час"
    if "через" in text:
        mins_match = re.search(r"(\d+)\s*(мин|минут|м)", text)
        hours_match = re.search(r"(\d+)\s*(час|часа|ч)", text)
        if mins_match:
            dt = now + timedelta(minutes=int(mins_match.group(1)))
        elif hours_match:
            dt = now + timedelta(hours=int(hours_match.group(1)))
        else:
            await message.reply("Не понял количество минут или часов")
            return

    # "завтра [время]"
    elif "завтра" in text:
        tomorrow = now + timedelta(days=1)
        dt = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)  # по умолчанию 09:00
        time_match = re.search(r"(\d{1,2}):(\d{2})", text)
        if time_match:
            h, m = int(time_match.group(1)), int(time_match.group(2))
            dt = dt.replace(hour=h, minute=m)

    # Полная дата "дд.мм.гггг чч:мм"
    else:
        try:
            naive_dt = datetime.strptime(text, "%d.%m.%Y %H:%M")
            dt = naive_dt.replace(tzinfo=moscow_tz)
        except ValueError:
            await message.reply(
                "Не понял время.\n"
                "Примеры:\n"
                "через 15 мин\n"
                "через 2 часа\n"
                "завтра 10:00\n"
                "17.12.2025 14:30"
            )
            return

    if dt <= now:
        await message.reply("Время уже прошло или равно текущему")
        return

    delay = int((dt - now).total_seconds())
    hours_left = delay // 3600
    mins_left = (delay % 3600) // 60

    # Добавляем в очередь
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
    position = len(scheduled_tasks[user_id])

    await message.reply(
        f"Запланировано на {dt.strftime('%d.%m.%Y %H:%M')} (МСК)\n"
        f"Осталось: {hours_left} ч {mins_left} мин\n"
        f"Позиция в очереди: {position}"
    )

    # Ждём и публикуем
    await asyncio.sleep(delay)

    await orig_post.copy_to(CHANNEL_ID)
    await bot.send_message(user_id, f"Пост опубликован в канал!\nВремя: {dt.strftime('%H:%M %d.%m.%Y')} МСК")

    # Удаляем из очереди
    scheduled_tasks[user_id].remove(task)
    await state.clear()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
