import os
import time
import asyncio
import random
import string

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CONTACT = "@VIP_Official_gang_Bot"

bot = Client(
    "protectbot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

mongo = AsyncIOMotorClient(MONGO)
db = mongo["telegram_protect"]

channels = db.channels
videos = db.videos
admins = db.admins
users = db.users
viewer_stats = db.viewer_stats
watch_logs = db.watch_logs
sent_videos = db.sent_videos

# ---------------- ANTI SPAM ----------------

user_requests = {}
user_timeouts = {}

SPAM_LIMIT = 3
SPAM_WINDOW = 30
FIRST_TIMEOUT = 60
SECOND_TIMEOUT = 600


# ---------------- UTILITIES ----------------

async def is_admin(uid):

    if uid == ADMIN_ID:
        return True

    admin = await admins.find_one({"user_id": uid})
    return bool(admin)


def generate_token():

    return ''.join(random.choices(
        string.ascii_letters + string.digits,
        k=10
    ))


# ---------------- START ----------------

@bot.on_message(filters.command("start"))
async def start(client, message):

    uid = message.from_user.id
    now = time.time()

    # timeout check
    if uid in user_timeouts and now < user_timeouts[uid]:

        wait = int(user_timeouts[uid] - now)

        await message.reply_text(
            f"⚠️ Please wait {wait} seconds before requesting again."
        )
        return

    # track requests
    if uid not in user_requests:
        user_requests[uid] = []

    user_requests[uid] = [
        t for t in user_requests[uid]
        if now - t < SPAM_WINDOW
    ]

    user_requests[uid].append(now)

    # spam detection
    if len(user_requests[uid]) >= SPAM_LIMIT:

        if uid in user_timeouts:
            timeout = SECOND_TIMEOUT
        else:
            timeout = FIRST_TIMEOUT

        user_timeouts[uid] = now + timeout

        await message.reply_text(
            f"⚠️ Too many requests.\n"
            f"You are restricted for {int(timeout/60)} minutes."
        )

        try:
            await bot.send_message(
                ADMIN_ID,
                f"🚨 Spam User Detected\n\n"
                f"Name: {message.from_user.first_name}\n"
                f"UserID: {uid}\n"
                f"Penalty: {int(timeout/60)} minutes"
            )
        except:
            pass

        return

    await users.update_one(
        {"user_id": uid},
        {"$set": {"name": message.from_user.first_name}},
        upsert=True
    )

    if len(message.command) == 1:

        await message.reply_text(
            f"This bot is private.\nContact {CONTACT}"
        )
        return

    payload = message.command[1]

    try:
        cid, token = payload.split("_")
    except:
        return

    cid = int(cid)

    course = await channels.find_one({"id": cid})

    if not course:
        return

    member = await client.get_chat_member(course["public"], uid)

    if member.status in ["left", "kicked"]:
        return

    video = await videos.find_one({
        "course_id": cid,
        "token": token
    })

    if not video:
        return

    msg = await client.copy_message(
        uid,
        course["storage"],
        video["message_id"],
        protect_content=True
    )

    await sent_videos.insert_one({
        "user_id": uid,
        "course_id": cid,
        "message_id": msg.id
    })

    await viewer_stats.update_one(
        {"course_id": cid, "user_id": uid},
        {"$inc": {"watch_count": 1},
         "$set": {"name": message.from_user.first_name}},
        upsert=True
    )

    await watch_logs.insert_one({
        "user_id": uid,
        "course_id": cid,
        "video": video["message_id"],
        "time": time.time()
    })


# ---------------- ADD PROTECT ----------------

@bot.on_message(filters.command("addprotect"))
async def addprotect(client, message):

    if not await is_admin(message.from_user.id):
        return

    storage = int(message.command[1])
    public = int(message.command[2])
    name = message.command[3]

    if await channels.find_one({"storage": storage}):
        await message.reply_text("Storage already registered.")
        return

    count = await channels.count_documents({})
    cid = count + 1

    await channels.insert_one({
        "id": cid,
        "name": name,
        "storage": storage,
        "public": public,
        "active": True
    })

    await message.reply_text(
        f"Protection added.\nCourse ID: {cid}"
    )


# ---------------- PROTECT LIST ----------------

@bot.on_message(filters.command("protectlist"))
async def protectlist(client, message):

    if not await is_admin(message.from_user.id):
        return

    text = "📚 Protected Courses\n\n"

    async for c in channels.find():

        status = "ACTIVE" if c["active"] else "STOPPED"

        text += (
            f"{c['name']}\n"
            f"ID: {c['id']}\n"
            f"Status: {status}\n\n"
        )

    await message.reply_text(text)


# ---------------- BROADCAST ----------------

@bot.on_message(filters.command("broadcast"))
async def broadcast(client, message):

    if not await is_admin(message.from_user.id):
        return

    text = message.text.split(None, 1)[1]

    sent = 0
    blocked = 0

    async for u in users.find():

        try:
            await bot.send_message(u["user_id"], text)
            sent += 1
        except:
            blocked += 1

    await message.reply_text(
        f"Broadcast complete\nSent: {sent}\nBlocked: {blocked}"
    )


# ---------------- TOP VIEWERS ----------------

@bot.on_message(filters.command("topviewers"))
async def topviewers(client, message):

    if not await is_admin(message.from_user.id):
        return

    cid = int(message.command[1])

    text = "👥 Channel-Wise Top Viewer Data:\n\n"

    cursor = viewer_stats.find(
        {"course_id": cid}
    ).sort("watch_count", -1).limit(10)

    i = 1

    async for v in cursor:

        text += f"{i}. {v['name']} - {v['watch_count']} Videos\n"
        i += 1

    if i == 1:
        text += "No data yet."

    await message.reply_text(text)


# ---------------- RECONNECT ----------------

@bot.on_message(filters.command("reconnect"))
async def reconnect(client, message):

    if not await is_admin(message.from_user.id):
        return

    text = "Reconnecting courses...\n\n"

    async for c in channels.find():

        try:
            await bot.get_chat(c["storage"])
            await bot.get_chat(c["public"])
            text += f"✅ {c['name']}\n"
        except:
            text += f"❌ {c['name']}\n"

    await message.reply_text(text)


# ---------------- STORAGE DETECT ----------------

@bot.on_message(filters.video | filters.document)
async def detect_storage(client, message):

    if not message.chat:
        return

    storage = message.chat.id

    course = await channels.find_one({"storage": storage})

    if not course:
        return

    cid = course["id"]

    token = generate_token()

    await videos.insert_one({
        "course_id": cid,
        "message_id": message.id,
        "token": token
    })

    button = InlineKeyboardMarkup(
        [[InlineKeyboardButton(
            "Watch Video",
            url=f"https://t.me/{(await bot.get_me()).username}?start={cid}_{token}"
        )]]
    )

    await bot.send_message(
        course["public"],
        f"Index: {message.id}\n\nWatch video below",
        reply_markup=button
    )


# ---------------- RUN ----------------

print("BOT RUNNING")

bot.run()
