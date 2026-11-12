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
    InlineKeyboardButton,
    BotCommand,
    BotCommandScopeDefault
)
from aiogram.exceptions import TelegramBadRequest

TOKEN = "ТОКЕН_ТВОЕГО_БОТА"
OWNER_ID = 8872934046

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
router = Router()

DB_NAME = "database.db"

class AdminStates(StatesGroup):
    waiting_for_channel_id = State()
    waiting_for_broadcast_text = State()

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY
            )
        """)
        # Храним ID канала и ссылку для перехода
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id TEXT PRIMARY KEY,
                invite_link TEXT
            )
        """)
        await db.commit()

async def set_bot_commands():
    # Быстрые команды для обычных пользователей
    user_commands = [
        BotCommand(command="start", description="Получить чит 🔥")
    ]
    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    
    # Для админа можно зарезервировать /admin в описании
    # (сама кнопка /admin работает по префиксу)

async def check_user_subscription(user_id: int, channel_id: str) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
        return False
    except TelegramBadRequest:
        return False
    except Exception:
        return False
async def add_user(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.commit()

@router.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    await add_user(user_id)
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT channel_id, invite_link FROM channels") as cursor:
            rows = await cursor.fetchall()
            
    if not rows:
        await message.answer(
            "Администратор еще не добавил обязательные каналы.\n"
            "Чтобы получить чит пиши: @losozi"
        )
        return

    keyboard_buttons = []
    for i, (ch_id, invite_link) in enumerate(rows, 1):
        link = invite_link if invite_link else f"https://t.me/{ch_id.replace('@', '')}"
        keyboard_buttons.append([InlineKeyboardButton(text=f"Канал {i}", url=link)])
        
    keyboard_buttons.append([InlineKeyboardButton(text="Проверить ✅", callback_data="check_subs")])
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await message.answer(
        "Что бы получить чит для standoff 2 подпишись на эти каналы:",
        reply_markup=markup
    )

@router.callback_query(F.data == "check_subs")
async def process_check_subscription(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT channel_id FROM channels") as cursor:
            rows = await cursor.fetchall()
            
    if not rows:
        await callback.answer("Каналы не настроены!", show_alert=True)
        return

    channels = [row[0] for row in rows]
    not_subscribed = []
    
    for ch in channels:
        is_sub = await check_user_subscription(user_id, ch)
        if not is_sub:
            not_subscribed.append(ch)

    if not_subscribed:
        await callback.answer(
            "Ты подписался не на все каналы!",
            show_alert=True
        )
        return

    await callback.message.edit_text(
        "Чтобы получить чит пиши : @losozi"
    )
    await callback.answer()
@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users = (await cursor.fetchone())[0]
            
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
        [InlineKeyboardButton(text="Добавить канал", callback_data="add_channel")],
        [InlineKeyboardButton(text="Список каналов", callback_data="list_channels")],
        [InlineKeyboardButton(text="Сделать рассылку", callback_data="start_broadcast")]
    ])

    text = (
        f"Админ панель\n\n"
        f"Кол-во пользователей: {total_users}\n"
        f"Сколько подписались на все каналы: {fully_subscribed_count}\n"
        f"Всего обязательных каналов: {len(channels)}"
    )
    
    await message.answer(text, reply_markup=markup)

@router.callback_query(F.data == "add_channel")
async def callback_add_channel(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        return
    
    await callback.message.answer(
        "Отправь айди канала (например: -1001234567890 или @channel):\n"
        "Бот автоматически попытается достать ссылку."
    )
    await state.set_state(AdminStates.waiting_for_channel_id)
    await callback.answer()

@router.message(AdminStates.waiting_for_channel_id, F.from_user.id == OWNER_ID)
async def save_new_channel(message: Message, state: FSMContext):
    channel_input = message.text.strip()
    
    try:
        chat = await bot.get_chat(channel_input)
        real_id = str(chat.id)
        
        # Получаем ссылку на чат ( username или инвайт-ссылка )
        if chat.username:
            invite_link = f"https://t.me/{chat.username}"
        else:
            invite_link = chat.invite_link
            if not invite_link:
                try:
                    invite_link = await bot.export_chat_invite_link(real_id)
                except Exception:
                    invite_link = None

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT OR REPLACE INTO channels (channel_id, invite_link) VALUES (?, ?)",
                (real_id, invite_link)
            )
            await db.commit()
            
        await message.answer(f"Канал успешно добавлен!\nID: {real_id}\nСсылка: {invite_link}")
    except Exception as e:
        await message.answer(f"Ошибка при добавлении канала. Убедись, что бот админ в канале.\nДетали: {e}")
            
    await state.clear()

@router.callback_query(F.data == "list_channels")
async def callback_list_channels(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        return
        
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT channel_id, invite_link FROM channels") as cursor:
            rows = await cursor.fetchall()
            
    if not rows:
        await callback.answer("Список каналов пуст.", show_alert=True)
        return
        
    text = "Список обязательных каналов:\n\n"
    for i, (ch_id, link) in enumerate(rows, 1):
        text += f"{i}. ID: {ch_id} | Ссылка: {link}\n"
        
    await callback.message.answer(text)
    await callback.answer()

# Рассылка
@router.callback_query(F.data == "start_broadcast")
async def callback_start_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        return
    await callback.message.answer("Отправь текст сообщения для рассылки всем пользователям:")
    await state.set_state(AdminStates.waiting_for_broadcast_text)
    await callback.answer()

@router.message(AdminStates.waiting_for_broadcast_text, F.from_user.id == OWNER_ID)
async def send_broadcast(message: Message, state: FSMContext):
    text_to_send = message.text
    await state.clear()
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users = await cursor.fetchall()
            
    success = 0
    fail = 0
    
    status_msg = await message.answer("Рассылка началась...")
    
    for (u_id,) in users:
        try:
            await bot.send_message(u_id, text_to_send)
            success += 1
            await asyncio.sleep(0.05) # защита от флуд-контроля Telegram
        except Exception:
            fail += 1
            
    await status_msg.edit_text(f"Рассылка завершена!\nУспешно: {success}\nНе удалось достать: {fail}")

async def main():
    await init_db()
    await set_bot_commands()
    dp.include_router(router)
    print("Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
