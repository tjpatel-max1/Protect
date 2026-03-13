import asyncio
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

import os
import time
import random
import string
import threading

from collections import defaultdict

from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient


# -------- ENV VARIABLES --------
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CONTACT = os.getenv("CONTACT", "Admin")
PORT = int(os.getenv("PORT", 10000))

# -------- BOT --------
bot = Client(
    "protectbot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# -------- DATABASE --------
mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo["protectbot"]

channels = db.channels
videos = db.videos
users = db.users
admins = db.admins
viewer = db.viewer_stats
watch = db.watch_logs

# -------- BUFFER SYSTEM (same as gama) --------
BUFFER_TIME = 5
buffer = defaultdict(list)

# -------- QUEUE --------
queue = asyncio.Queue()

# -------- ANTISPAM --------
user_req = {}
timeouts = {}

SPAM_LIMIT = 3
WINDOW = 30
FIRST_TIMEOUT = 60
SECOND_TIMEOUT = 600

# -------- TOKEN --------
def gen_token():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=10))

# -------- ADMIN CHECK --------
async def is_admin(uid):

    if uid == ADMIN_ID:
        return True

    a = await admins.find_one({"user_id": uid})
    return bool(a)

# -------- USER START --------
@bot.on_message(filters.command("start"))
async def start(c, m):

uid = m.from_user.id

# ---- Admins bypass antispam ----
if not await is_admin(uid):

    now = time.time()

    if uid in timeouts and now < timeouts[uid]:
        wait = int(timeouts[uid] - now)
        await m.reply(f"⚠️ Wait {wait} seconds")
        return

    if uid not in user_req:
        user_req[uid] = []

    user_req[uid] = [t for t in user_req[uid] if now - t < WINDOW]
    user_req[uid].append(now)

    if len(user_req[uid]) >= SPAM_LIMIT:

        timeout = FIRST_TIMEOUT if uid not in timeouts else SECOND_TIMEOUT
        timeouts[uid] = now + timeout

        await m.reply("⚠️ Too many requests")

        try:
            if uid != ADMIN_ID:
                await bot.send_message(
                    ADMIN_ID,
                    f"🚨 Spam detected\nUser: {uid}"
                )
        except:
            pass

        return

    await users.update_one(
        {"user_id": uid},
        {"$set": {"name": m.from_user.first_name}},
        upsert=True
    )

    if len(m.command) == 1:
        await m.reply(f"This bot is private.\nContact {CONTACT}")
        return

    payload = m.command[1]

    try:
        cid, tok = payload.split("_")
        cid = int(cid)
    except:
        return

    course = await channels.find_one({"id": cid, "active": True})
    if not course:
        return

    member = await bot.get_chat_member(course["public"], uid)
    if member.status in ["left", "kicked"]:
        return

    vid = await videos.find_one({"course_id": cid, "token": tok})
    if not vid:
        return

    await bot.copy_message(uid, course["storage"], vid["msg"])

    await viewer.update_one(
        {"course": cid, "user": uid},
        {"$inc": {"count": 1}},
        upsert=True
    )

    await watch.insert_one({
        "course": cid,
        "user": uid,
        "time": time.time()
    })

# -------- STORAGE DETECTOR --------
@bot.on_message(filters.video | filters.document)
async def detect(c, m):

    course = await channels.find_one({"storage": m.chat.id})

    if not course or not course["active"]:
        return

    cid = course["id"]
    tok = gen_token()

    await videos.insert_one({
        "course_id": cid,
        "msg": m.id,
        "token": tok
    })

    btn = InlineKeyboardMarkup(
        [[InlineKeyboardButton(
            "Watch Video",
            url=f"https://t.me/{(await bot.get_me()).username}?start={cid}_{tok}"
        )]]
    )

    buffer[cid].append((course, m, btn))

    await asyncio.sleep(BUFFER_TIME)

    items = buffer[cid]
    buffer[cid] = []

    items.sort(key=lambda x: x[1].id)

    for course, msg, btn in items:
        await queue.put((course, msg, btn))

# -------- QUEUE WORKER --------
async def worker():

    while True:

        course, msg, btn = await queue.get()

        try:

            await bot.send_message(
                course["public"],
                msg.caption,
                reply_markup=btn
            )

            await asyncio.sleep(2)

        except Exception as e:
            print("Worker error:", e)

loop.create_task(worker())

# -------- PROTECTION --------
@bot.on_message(filters.command("addprotect"))
async def addprotect(c, m):

    if not await is_admin(m.from_user.id):
        return

    storage = int(m.command[1])
    post = int(m.command[2])
    name = m.command[3]

    if await channels.find_one({"storage": storage}):
        await m.reply("Storage already protected")
        return

    cid = await channels.count_documents({}) + 1

    await channels.insert_one({
        "id": cid,
        "name": name,
        "storage": storage,
        "public": post,
        "active": True
    })

    await m.reply(f"Protection added\nID {cid}")

# -------- PROTECT LIST --------
@bot.on_message(filters.command("protectlist"))
async def protectlist(c, m):

    if not await is_admin(m.from_user.id):
        return

    text = "📚 Protected Courses\n\n"

    async for x in channels.find():

        status = "ACTIVE" if x["active"] else "STOPPED"

        text += (
            f"{x['name']}\n"
            f"ID: {x['id']}\n"
            f"Status: {status}\n\n"
        )

    await m.reply(text)

# -------- STOP --------
@bot.on_message(filters.command("protectstop"))
async def protectstop(c, m):

    if not await is_admin(m.from_user.id):
        return

    cid = int(m.command[1])

    await channels.update_one(
        {"id": cid},
        {"$set": {"active": False}}
    )

    await m.reply("Protection stopped")

# -------- RESTART --------
@bot.on_message(filters.command("protectrestart"))
async def protectrestart(c, m):

    if not await is_admin(m.from_user.id):
        return

    cid = int(m.command[1])

    await channels.update_one(
        {"id": cid},
        {"$set": {"active": True}}
    )

    await m.reply("Protection restarted")

# -------- REMOVE --------
@bot.on_message(filters.command("protectremove"))
async def protectremove(c, m):

    if not await is_admin(m.from_user.id):
        return

    cid = int(m.command[1])

    course = await channels.find_one({"id": cid})

    if not course:
        await m.reply("Course not found")
        return

    await channels.delete_one({"_id": course["_id"]})
    await videos.delete_many({"course_id": cid})

    await m.reply("Protection removed")

# -------- ADMIN MANAGEMENT --------
@bot.on_message(filters.command("addadmin"))
async def addadmin(c, m):

    if m.from_user.id != ADMIN_ID:
        return

    uid = int(m.command[1])

    await admins.update_one(
        {"user_id": uid},
        {"$set": {"user_id": uid}},
        upsert=True
    )

    await m.reply(f"Admin added: {uid}")

@bot.on_message(filters.command("removeadmin"))
async def removeadmin(c, m):

    if m.from_user.id != ADMIN_ID:
        return

    uid = int(m.command[1])

    await admins.delete_one({"user_id": uid})

    await m.reply(f"Admin removed: {uid}")

# -------- BROADCAST --------
@bot.on_message(filters.command("broadcast"))
async def broadcast(c, m):

    if not await is_admin(m.from_user.id):
        return

    text = m.text.split(None,1)[1]

    sent = 0
    blocked = 0

    async for u in users.find():

        try:
            await bot.send_message(u["user_id"], text)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            blocked += 1

    await m.reply(
        f"Broadcast complete\nSent: {sent}\nBlocked: {blocked}"
    )

# -------- ANALYTICS --------
@bot.on_message(filters.command("topviewers"))
async def topviewers(c, m):

    if not await is_admin(m.from_user.id):
        return

    cid = int(m.command[1])

    text = "👥 Channel-Wise Top Viewer Data:\n\n"

    cursor = viewer.find({"course": cid}).sort("count",-1).limit(20)

    i = 1
    async for v in cursor:
        text += f"{i}. {v['user']} - {v['count']} Videos\n"
        i += 1

    if i == 1:
        text += "No data yet."

    await m.reply(text)

# -------- USER STATS --------
@bot.on_message(filters.command("userstats"))
async def userstats(c, m):

    if not await is_admin(m.from_user.id):
        return

    uid = int(m.command[1])

    total = await viewer.count_documents({"user": uid})

    today = await watch.count_documents({
        "user": uid,
        "time": {"$gte": time.time() - 86400}
    })

    await m.reply(
        f"User {uid}\n\nTotal Videos: {total}\nToday: {today}"
    )

# -------- ID HELPER --------
@bot.on_message(filters.command("id"))
async def getid(c, m):
    await m.reply(f"Chat ID:\n`{m.chat.id}`")

# -------- FLASK KEEPALIVE --------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running"

def run():
    app.run("0.0.0.0", PORT)

threading.Thread(target=run).start()

print("BOT RUNNING")

bot.run()
