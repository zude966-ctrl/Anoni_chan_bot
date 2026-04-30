import asyncio
import time
import os
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters.command import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= CONFIG =================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("Нет BOT_TOKEN в переменных окружения")

RATE_LIMIT_SECONDS = 1
SEARCH_TIMEOUT = 60

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ================= WEB SERVER (ANTI-SLEEP) =================

async def handle(request):
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# ================= STATE =================

class Registration(StatesGroup):
    age = State()
    gender = State()

# ================= MEMORY =================

users = {}
search_queue = []
last_action_time = {}

# ================= AGE RANGE =================

AGE_RANGES = {i: (13, 70) for i in range(13, 71)}

# ================= KEYBOARDS =================

def main_kb():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="Найти парня"), types.KeyboardButton(text="Найти девушку")],
            [types.KeyboardButton(text="Мои данные")]
        ],
        resize_keyboard=True
    )

def gender_kb():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="Парень"), types.KeyboardButton(text="Девушка")]
        ],
        resize_keyboard=True
    )

def cancel_kb():
    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="Отменить поиск")]],
        resize_keyboard=True
    )

chat_kb = types.ReplyKeyboardMarkup(
    keyboard=[[types.KeyboardButton(text="Завершить диалог")]],
    resize_keyboard=True
)

# ================= HELPERS =================

def is_rate_limited(user_id):
    now = time.time()
    last = last_action_time.get(user_id, 0)
    if now - last < RATE_LIMIT_SECONDS:
        return True
    last_action_time[user_id] = now
    return False

def in_chat(user_id):
    return users.get(user_id, {}).get("partner") is not None

def in_search(user_id):
    return user_id in search_queue

# ================= START =================

@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await message.answer("Сколько тебе лет?")
    await state.set_state(Registration.age)

# ================= REGISTRATION =================

@dp.message(Registration.age)
async def reg_age(message: types.Message, state: FSMContext):
    try:
        age = int(message.text)
    except:
        return await message.answer("Напиши возраст числом")

    if age < 13 or age > 70:
        return await message.answer("Возраст от 13 до 70")

    await state.update_data(age=age)
    await message.answer("Выбери пол:", reply_markup=gender_kb())
    await state.set_state(Registration.gender)

@dp.message(Registration.gender)
async def reg_gender(message: types.Message, state: FSMContext):
    if message.text not in ["Парень", "Девушка"]:
        return

    data = await state.get_data()

    users[message.from_user.id] = {
        "age": data["age"],
        "gender": message.text,
        "partner": None,
        "search_for": None
    }

    await message.answer("Кого ищем?", reply_markup=main_kb())
    await state.clear()

# ================= SEARCH =================

async def start_search(user_id, message, target):
    if in_chat(user_id) or in_search(user_id):
        return await message.answer("Сначала заверши текущее действие")

    users[user_id]["search_for"] = target
    search_queue.append(user_id)

    await message.answer("Ищу собеседника...", reply_markup=cancel_kb())

    await asyncio.sleep(2)

    for other_id in search_queue:
        if other_id == user_id:
            continue

        other = users.get(other_id)
        if not other:
            continue

        if other["search_for"] == users[user_id]["gender"] and users[user_id]["search_for"] == other["gender"]:
            if user_id in search_queue:
                search_queue.remove(user_id)
            if other_id in search_queue:
                search_queue.remove(other_id)

            users[user_id]["partner"] = other_id
            users[other_id]["partner"] = user_id

            await message.answer("Собеседник найден!", reply_markup=chat_kb)
            await bot.send_message(other_id, "Собеседник найден!", reply_markup=chat_kb)
            return

@dp.message(F.text == "Найти парня")
async def find_male(message: types.Message):
    await start_search(message.from_user.id, message, "Парень")

@dp.message(F.text == "Найти девушку")
async def find_female(message: types.Message):
    await start_search(message.from_user.id, message, "Девушка")

@dp.message(F.text == "Отменить поиск")
async def cancel_search(message: types.Message):
    uid = message.from_user.id
    if uid in search_queue:
        search_queue.remove(uid)
        users[uid]["search_for"] = None
        await message.answer("Поиск отменён", reply_markup=main_kb())

# ================= CHAT =================

@dp.message(F.text == "Завершить диалог")
async def end_chat(message: types.Message):
    uid = message.from_user.id
    pid = users.get(uid, {}).get("partner")

    if pid:
        users[uid]["partner"] = None
        users[pid]["partner"] = None

        await message.answer("Диалог завершён", reply_markup=main_kb())
        await bot.send_message(pid, "Диалог завершён", reply_markup=main_kb())

@dp.message(F.text)
async def relay(message: types.Message):
    uid = message.from_user.id

    if is_rate_limited(uid):
        return

    pid = users.get(uid, {}).get("partner")

    if pid:
        try:
            await bot.send_message(pid, message.text)
        except Exception as e:
            print("Ошибка:", e)

# ================= START =================

async def main():
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())