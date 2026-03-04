import os
import time
import random
import string
import threading

from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
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


# ---------------- TOKEN ----------------

def generate_token(length=6):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


async def unique_token():

    while True:

        token = generate_token()

        exists = await videos_db.find_one({"token": token})

        if not exists:
            return token


# ---------------- ADMIN COMMAND ----------------

@bot.on_message(filters.command("addprotect") & filters.user(ADMIN_ID))
async def addprotect(client, message):

    parts = message.text.split()

    if len(parts) < 4:
        await message.reply_text("Usage:\n/addprotect -100storageID -100publicID NAME")
        return

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


# ---------------- START ----------------

@bot.on_message(filters.command("start"))
async def start(client, message):

    user_id = message.from_user.id

    if not allow_request(user_id):
        await message.reply_text("⚠️ Please wait a few seconds.")
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

    member = await client.get_chat_member(course["public"], user_id)

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


# ---------------- STORAGE DETECT ----------------

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
        [[InlineKeyboardButton(
            "▶ Watch Video",
            callback_data=f"watch_{course['id']}_{token}"
        )]]
    )

    await client.send_message(
        course["public"],
        message.caption or "",
        reply_markup=button
    )


# ---------------- CALLBACK ----------------

@bot.on_callback_query()
async def callback_handler(client, query):

    data = query.data

    if data.startswith("watch_"):

        _, course_id, token = data.split("_")

        me = await client.get_me()

        await query.answer(
            url=f"https://t.me/{me.username}?start={course_id}_{token}"
        )


# ---------------- FLASK ----------------

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running"


def run_flask():
    app.run("0.0.0.0", PORT)


threading.Thread(target=run_flask).start()


# ---------------- START BOT ----------------

bot.run()
