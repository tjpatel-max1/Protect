import asyncio

try:
    asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import os
import random
import string
import threading

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import FloodWait

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
MONGO_URL = os.environ["MONGO_URI"]
OWNER_ID = int(os.environ["OWNER_ID"])
PORT = int(os.environ.get("PORT", 10000))

bot = Client("protectbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

mongo = AsyncIOMotorClient(MONGO_URL)
db = mongo.protectbot

channels_db = db.channels
videos_db = db.videos
admins_db = db.admins

upload_queue = Queue()

POST_DELAY = 2

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot running"


def run():
    app.run(host="0.0.0.0", port=PORT)


def random_token():
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(10))


async def is_admin(user_id):
    admin = await admins_db.find_one({"user_id": user_id})
    return admin is not None or user_id == OWNER_ID


async def unique_token():
    while True:
        token = random_token()
        exists = await videos_db.find_one({"token": token})
        if not exists:
            return token


@bot.on_message(filters.command("start") & filters.private)
async def start(bot, message):

    args = message.text.split()

    if len(args) == 1:
        await message.reply_text(
            "This bot is private.\n\nContact @VIP_Official_gang_Bot"
        )
        return

    data = args[1]

    try:
        course_id, token = data.split("_")
        course_id = int(course_id)
    except:
        return

    course = await channels_db.find_one({"id": course_id})

    if not course:
        return

    member = await bot.get_chat_member(course["public"], message.from_user.id)

    if member.status in ["left", "kicked"]:
        return

    video = await videos_db.find_one({
        "course_id": course_id,
        "token": token
    })

    if not video:
        return

    await bot.copy_message(
        message.chat.id,
        course["storage"],
        video["message_id"],
        protect_content=True
    )


@bot.on_callback_query()
async def callback_handler(bot, callback):

    data = callback.data

    if not data.startswith("watch_"):
        return

    try:
        _, course_id, token = data.split("_")
        course_id = int(course_id)
    except:
        return

    await callback.answer()

    bot_username = (await bot.get_me()).username

    await callback.message.reply(
        f"https://t.me/{bot_username}?start={course_id}_{token}"
    )


@bot.on_message(filters.command("addadmin") & filters.private)
async def add_admin(bot, message):

    if message.from_user.id != OWNER_ID:
        return

    user = int(message.command[1])

    await admins_db.insert_one({"user_id": user})

    await message.reply_text("Admin added")


@bot.on_message(filters.command("removeadmin") & filters.private)
async def remove_admin(bot, message):

    if message.from_user.id != OWNER_ID:
        return

    user = int(message.command[1])

    await admins_db.delete_one({"user_id": user})

    await message.reply_text("Admin removed")


@bot.on_message(filters.command("addprotect") & filters.private)
async def add_protect(bot, message):

    if not await is_admin(message.from_user.id):
        return

    storage = int(message.command[1])
    public = int(message.command[2])
    name = message.command[3]

    course = await channels_db.count_documents({}) + 1

    await channels_db.insert_one({
        "id": course,
        "name": name,
        "storage": storage,
        "public": public,
        "active": True
    })

    await message.reply_text("Protection added")


@bot.on_message(filters.command("protectlist") & filters.private)
async def protect_list(bot, message):

    if not await is_admin(message.from_user.id):
        return

    text = "Protected Courses\n\n"

    async for c in channels_db.find():

        status = "ACTIVE" if c["active"] else "STOPPED"

        text += f"{c['id']}. {c['name']} ({status})\n"

    await message.reply_text(text)


@bot.on_message(filters.command("protectstop") & filters.private)
async def protect_stop(bot, message):

    if not await is_admin(message.from_user.id):
        return

    cid = int(message.command[1])

    await channels_db.update_one({"id": cid}, {"$set": {"active": False}})

    await message.reply_text("Protection stopped")


@bot.on_message(filters.command("protectrestart") & filters.private)
async def protect_restart(bot, message):

    if not await is_admin(message.from_user.id):
        return

    cid = int(message.command[1])

    await channels_db.update_one({"id": cid}, {"$set": {"active": True}})

    await message.reply_text("Protection restarted")


@bot.on_message(filters.command("protectremove") & filters.private)
async def protect_remove(bot, message):

    if not await is_admin(message.from_user.id):
        return

    cid = int(message.command[1])

    await channels_db.delete_one({"id": cid})

    await message.reply_text("Protection removed")


@bot.on_message(filters.command("protectcleandb") & filters.private)
async def clean_db(bot, message):

    if not await is_admin(message.from_user.id):
        return

    cid = int(message.command[1])

    await videos_db.delete_many({"course_id": cid})

    await message.reply_text("Database cleaned")


@bot.on_message(filters.channel & (filters.video | filters.document))
async def detect_storage(bot, message):

    course = await channels_db.find_one({"storage": message.chat.id})

    if not course:
        return

    if not course["active"]:
        return

    await upload_queue.put((course, message))


async def upload_worker():

    while True:

        course, message = await upload_queue.get()

        try:

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

            while True:
                try:
                    await bot.send_message(
                        course["public"],
                        message.caption or "",
                        reply_markup=button
                    )
                    break

                except FloodWait as e:
                    await asyncio.sleep(e.value)

            await asyncio.sleep(POST_DELAY)

        except Exception as e:
            print("Worker error:", e)

        upload_queue.task_done()


async def startup():

    asyncio.create_task(upload_worker())


if __name__ == "__main__":

    threading.Thread(target=run).start()

    loop = asyncio.get_event_loop()

    loop.run_until_complete(startup())

    bot.run()
