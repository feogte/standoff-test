import asyncio
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.exceptions import TelegramBadRequest

# Токен твоего бота (вставь сюда токен от BotFather или оставь переменную для окружения)
TOKEN = "ТОКЕН_ТВОЕГО_БОТА"
OWNER_ID = 8872934046

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
router = Router()

DB_NAME = "database.db"

# Состояния для админки (добавление канала)
class AdminStates(StatesGroup):
    waiting_for_channel_id = State()

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Таблица пользователей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY
            )
        """)
        # Таблица обязательных каналов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id TEXT PRIMARY KEY
            )
        """)
        await db.commit()

# Проверка, подписан ли юзер на конкретный канал
async def check_user_subscription(user_id: int, channel_id: str) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        # Статусы, при которых считается, что пользователь подписан
        if member.status in ["member", "administrator", "creator"]:
            return True
        return False
    except TelegramBadRequest:
        # Если бот не админ в канале или канал указан неверно
        return False
    except Exception:
        return False
# Добавление пользователя в базу при /start
async def add_user(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.commit()

@router.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    await add_user(user_id)
    
    # Получаем список каналов из базы
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT channel_id FROM channels") as cursor:
            rows = await cursor.fetchall()
            
    channels = [row[0] for row in rows]
    
    if not channels:
        await message.answer(
            "Привет! Администратор еще не добавил обязательные каналы для подписки.\n"
            "Чтобы получить чит, пиши: @losozi"
        )
        return

    # Формируем клавиатуру с каналами и кнопкой проверки
    keyboard_buttons = []
    
    for i, ch in enumerate(channels, 1):
        # Попытка получить ссылку канала, если в базе username или пригласительная ссылка
        chat_link = f"https://t.me/{ch.replace('@', '')}" if not ch.startswith("-100") else f"https://t.me/c/{str(ch)[4:]}"
        keyboard_buttons.append([InlineKeyboardButton(text=f"📢 Канал {i}", url=chat_link)])
        
    keyboard_buttons.append([InlineKeyboardButton(text="✅ Проверить", callback_data="check_subs")])
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await message.answer(
        "Привет! Что бы получить чит для Standoff 2 подпишись на эти каналы:",
        reply_markup=markup
    )

@router.callback_query(F.data == "check_subs")
async def process_check_subscription(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT channel_id FROM channels") as cursor:
            rows = await cursor.fetchall()
            
    channels = [row[0] for row in rows]
    
    if not channels:
        await callback.answer("Каналы не настроены!", show_alert=True)
        return

    # Проверяем подписку на каждый канал
    not_subscribed = []
    for ch in channels:
        is_sub = await check_user_subscription(user_id, ch)
        if not is_sub:
            not_subscribed.append(ch)

    if not_subscribed:
        await callback.answer(
            "❌ Ты подписался не на все каналы! Проверь подписки.",
            show_alert=True
        )
        return

    # Если подписался на все
    await callback.message.edit_text(
        "✅ Успешно! Подписка подтверждена.\n\n"
        "Чтобы получить чит пиши: @losozi"
    )
    await callback.answer()
@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    
    # Считаем статистику
    async with aiosqlite.connect(DB_NAME) as db:
        # Всего пользователей
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users = (await cursor.fetchone())[0]
            
        # Сколько человек подписались на ВСЕ каналы
        async with db.execute("SELECT user_id FROM users") as cursor:
            all_users = await cursor.fetchall()
            
        async with db.execute("SELECT channel_id FROM channels") as cursor:
            channels_rows = await cursor.fetchall()
            
    channels = [row[0] for row in channels_rows]
    
    fully_subscribed_count = 0
    if channels:
        for (u_id,) in all_users:
            subscribed_to_all = True
            for ch in channels:
                if not await check_user_subscription(u_id, ch):
                    subscribed_to_all = False
                    break
            if subscribed_to_all:
                fully_subscribed_count += 1

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить канал", callback_data="add_channel")],
        [InlineKeyboardButton(text="📋 Список каналов", callback_data="list_channels")]
    ])

    text = (
        f"⚙️ **Админ-панель**\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"✅ Подписались на все каналы: {fully_subscribed_count}\n"
        f"📢 Обязательных каналов: {len(channels)}"
    )
    
    await message.answer(text, reply_markup=markup, parse_mode="Markdown")

@router.callback_query(F.data == "add_channel")
async def callback_add_channel(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        return
    
    await callback.message.answer(
        "Отправь ID канала (например: `-1001234567890`) или его юзернейм (например: `@my_channel`).\n"
        "⚠️ *Важно:* Бот обязательно должен быть администратором в этом канале!"
    )
    await state.set_state(AdminStates.waiting_for_channel_id)
    await callback.answer()

@router.message(AdminStates.waiting_for_channel_id, F.from_user.id == OWNER_ID)
async def save_new_channel(message: Message, state: FSMContext):
    channel_id = message.text.strip()
    
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute("INSERT INTO channels (channel_id) VALUES (?)", (channel_id,))
            await db.commit()
            await message.answer(f"✅ Канал `{channel_id}` успешно добавлен в обязательные!")
        except aiosqlite.IntegrityError:
            await message.answer("⚠️ Этот канал уже есть в списке обязательных.")
            
    await state.clear()

@router.callback_query(F.data == "list_channels")
async def callback_list_channels(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        return
        
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT channel_id FROM channels") as cursor:
            rows = await cursor.fetchall()
            
    if not rows:
        await callback.answer("Список каналов пуст.", show_alert=True)
        return
        
    text = "📋 **Список обязательных каналов:**\n\n"
    for i, row in enumerate(rows, 1):
        text += f"{i}. `{row[0]}`\n"
        
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

async def main():
    await init_db()
    dp.include_router(router)
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncIO = asyncio.run(main())
