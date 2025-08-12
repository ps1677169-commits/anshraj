import asyncio
import time
import aiosqlite
from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import re
import string
import random

# === Configuration ===
BOT_TOKEN = "8272701346:AAHiZxjcuB2ic7ujxsgG2cy-yIKvzsG-qco"
API_ID = 21519773
API_HASH = "a37a4bd65e6864e813df173dbeb360f9"
STRING_SESSION = "1BVtsOIEBu4JHIjLlBFxmI5sXOz3fMhUybO1s3aE-JU_Tx4E683MJarQ8Dq2t7nvRob25uiUuHuAgAbbDmPkpFoiXZf0_j6jVo7jPT9yCLdp2ihNYg856wH13bPxRkEcSY1FKVey39M92Jlh1wJ20hv0LDgrXVksvZg1cDnOdGz-NM2yR0q98Ji5RSAMv7oVDNh4-MfRkDwNONdqDLv9LtWT__J0mhqFiZ-Eye9vHjc6rVNfu95tsxa8abwt9ZOhCxY8CX5k1_Kj9Y8oXesnxUlnfwxgf-vyTz4EmtKum5rDsNOLGdcCmls0h9PDSqrCLGIU2T3Gqj_JY9zWBU6C6t9EnQILn8Tc="
ADMIN_ID = 7977745800  # Replace with your Telegram user ID
DB_NAME = "passes.db"

# === Init Bots ===
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

# === Active user tracking ===
active_users = {}  # user_id: expires_at
user_response_tracker = {}
message_map = {}
last_active_user = None

# === Utility Functions ===
def parse_duration(s):
    match = re.match(r"^(\d+)([smhd])$", s.strip())
    if not match:
        return None
    value, unit = match.groups()
    value = int(value)
    return {
        "s": value,
        "m": value * 60,
        "h": value * 3600,
        "d": value * 86400
    }.get(unit)

def generate_passcode(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS passes (
                code TEXT PRIMARY KEY,
                expires_at INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS active_users (
                user_id INTEGER PRIMARY KEY,
                expires_at INTEGER
            )
        """)
        await db.commit()

async def load_active_users():
    global active_users
    now = int(time.time())
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id, expires_at FROM active_users") as cursor:
            async for row in cursor:
                user_id, expires_at = row
                if expires_at > now:
                    active_users[user_id] = expires_at

async def validate_pass(code: str):
    now = int(time.time())
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT expires_at FROM passes WHERE code = ?", (code,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0] > now:
                await db.execute("DELETE FROM passes WHERE code = ?", (code,))
                await db.commit()
                return row[0]  # Return expiry timestamp
    return None

# === Commands ===
@dp.message(Command("genpass"))
async def genpass_handler(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔️ You are not allowed.")
        return

    if not command.args:
        return await message.reply("Usage: /genpass 1m | 1h | 1d")

    duration = parse_duration(command.args)
    if not duration:
        return await message.reply("Invalid format. Use like 1m, 1h, or 1d.")

    code = generate_passcode()
    expires_at = int(time.time()) + duration

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO passes (code, expires_at) VALUES (?, ?)", (code, expires_at))
        await db.commit()

    await message.reply(f"✅ Pass Created:\n<code>{code}</code>\nValid for {command.args}", parse_mode="HTML")

@dp.message(Command("start"))
async def start_cmd(message: Message, command: CommandObject):
    if not command.args:
        return await message.reply("🔐 Use: /start <passcode>")

    code = command.args.strip().upper()

    expires_at = await validate_pass(code)
    if expires_at:
        active_users[message.from_user.id] = expires_at

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT OR REPLACE INTO active_users (user_id, expires_at) VALUES (?, ?)",
                (message.from_user.id, expires_at)
            )
            await db.commit()

        await message.reply("✅ Access granted! Send your number to get info.")
    else:
        await message.reply("❌ Invalid or expired pass.")

@dp.message()
async def handle_number(message: Message):
    global last_active_user

    now = int(time.time())
    expires_at = active_users.get(message.from_user.id)

    if not expires_at or now > expires_at:
        active_users.pop(message.from_user.id, None)

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("DELETE FROM active_users WHERE user_id = ?", (message.from_user.id,))
            await db.commit()

        await message.reply("⛔️ Access expired. Please send /start <passcode> again.")
        return

    number = message.text.strip()
    try:
        sent_msg = await client.send_message('PRINCE_INFO_BOT', number)
        message_map[sent_msg.id] = message.from_user.id
        user_response_tracker[message.from_user.id] = 0
        last_active_user = message.from_user.id
        await message.reply("⏳ Waiting for response from info bot...")
    except Exception as e:
        await message.reply(f"❌ Failed to send: {e}")

@client.on(events.NewMessage(from_users='PRINCE_INFO_BOT'))
async def prince_info_reply(event):
    global last_active_user

    reply_to_msg_id = event.message.reply_to_msg_id
    original_user_id = None

    if reply_to_msg_id and reply_to_msg_id in message_map:
        original_user_id = message_map[reply_to_msg_id]
    else:
        original_user_id = last_active_user

    if not original_user_id:
        return

    count = user_response_tracker.get(original_user_id, 0)
    user_response_tracker[original_user_id] = count + 1

    if count == 0:
        return  # Skip first automatic bot message

    try:
        await bot.send_message(original_user_id, event.message.text)
    except Exception as e:
        print(f"❌ Failed to forward message: {e}")

# === Main Runner ===
async def main():
    await init_db()
    await load_active_users()
    await client.start()
    print("✅ Telethon client started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
