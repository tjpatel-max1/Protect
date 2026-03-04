#2nd bot
import os
import time
import random
import string
import asyncio

from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient


# ---------------- ENV ----------------

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
MONGO_URI = os.getenv("MONGO_URI")

PORT = int(os.getenv("PORT", 10000))


# ---------------- DATABASE ----------------

mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo["srcprotect"]

channels_db = db.channels
videos_db = db.videos


# ---------------- BOT ----------------

bot = Client(
    "srcprotectbot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# ---------------- ANTISPAM ----------------

user_last_request = {}

def allow_request(user_id):

    now = time.time()

    if user_id in user_last_request:
        if now - user_last_request[user_id] < 3:
            return False

    user_last_request[user_id] = now
    return True


# ---------------- TOKEN GENERATOR ----------------

def generate_token(length=6):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


async def unique_token():

    while True:

        token = generate_token()

        exists = await videos_db.find_one({"token": token})

        if not exists:
            return token


# ---------------- ADMIN COMMANDS ----------------

@bot.on_message(filters.command("addprotect") & filters.user(ADMIN_ID))
async def addprotect(client, message):

    try:

        parts = message.text.split()

        storage = int(parts[1])
        public = int(parts[2])
        name = parts[3]

        count = await channels_db.count_documents({})

        await channels_db.insert_one({
            "id": count + 1,
            "name": name,
            "storage": storage,
            "public": public,
            "active": True
        })

        await message.reply_text("Protection added.")

    except:

        await message.reply_text(
            "Usage:\n/addprotect -100storageID -100publicID NAME"
        )


@bot.on_message(filters.command("list") & filters.user(ADMIN_ID))
async def list_courses(client, message):

    text = "Protected Courses\n\n"

    async for c in channels_db.find():

        status = "ACTIVE" if c["active"] else "STOPPED"

        text += f"{c['id']}. {c['name']} ({status})\n"

    await message.reply_text(text)


@bot.on_message(filters.command("stop") & filters.user(ADMIN_ID))
async def stop_course(client, message):

    course_id = int(message.command[1])

    await channels_db.update_one(
        {"id": course_id},
        {"$set": {"active": False}}
    )

    await message.reply_text("Course stopped.")


@bot.on_message(filters.command("restart") & filters.user(ADMIN_ID))
async def restart_course(client, message):

    course_id = int(message.command[1])

    await channels_db.update_one(
        {"id": course_id},
        {"$set": {"active": True}}
    )

    await message.reply_text("Course restarted.")


# ---------------- STORAGE DETECTION ----------------

@bot.on_message(filters.video | filters.document)
async def detect_storage(client, message):

    storage_id = message.chat.id

    course = await channels_db.find_one({"storage": storage_id})

    if not course:
        return

    if not course["active"]:
        return

    token = await unique_token()

    await videos_db.insert_one({
        "course_id": course["id"],
        "token": token,
        "message_id": message.id
    })

    button = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(
                "▶ Watch Video",
                callback_data=f"watch_{course['id']}_{token}"
            )
        ]]
    )

    caption = f"{message.caption or ''}"

    await client.send_message(
        course["public"],
        caption,
        reply_markup=button
    )


# ---------------- CALLBACK REDIRECT ----------------

@bot.on_callback_query()
async def callback_handler(client, callback_query):

    data = callback_query.data

    if data.startswith("watch_"):

        parts = data.split("_")

        course_id = parts[1]
        token = parts[2]

        me = await client.get_me()

        await callback_query.answer(
            url=f"https://t.me/{me.username}?start={course_id}_{token}"
        )


# ---------------- START COMMAND ----------------

@bot.on_message(filters.command("start"))
async def start(client, message):

    user_id = message.from_user.id

    if not allow_request(user_id):

        await message.reply_text(
            "⚠️ Please wait a few seconds."
        )

        return

    if len(message.command) == 1:

        await message.reply_text(
            "This bot is private.\n\nContact @VIP_Official_gang_Bot"
        )

        return

    payload = message.command[1]

    course_id, token = payload.split("_")

    course_id = int(course_id)

    course = await channels_db.find_one({"id": course_id})

    if not course:
        return

    member = await client.get_chat_member(
        course["public"],
        user_id
    )

    if member.status in ["left", "kicked"]:

        await message.reply_text(
            "You haven't purchased the subscription.\n\n"
            "Contact @VIP_Official_gang_Bot"
        )

        return

    video = await videos_db.find_one({
        "course_id": course_id,
        "token": token
    })

    if not video:

        await message.reply_text("Video not found.")
        return

    await client.copy_message(
        chat_id=user_id,
        from_chat_id=course["storage"],
        message_id=video["message_id"],
        protect_content=True
    )


# ---------------- FLASK SERVER ----------------

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running"


# ---------------- ENTRYPOINT ----------------

async def main():

    await bot.start()

    print("Bot started")

    # Mongo index for fast token lookup
    await videos_db.create_index("token", unique=True)

    asyncio.create_task(
        asyncio.to_thread(app.run, "0.0.0.0", PORT)
    )

    try:
        await asyncio.Future()

    except asyncio.CancelledError:
        pass

    finally:
        await bot.stop()


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("Bot stopped")