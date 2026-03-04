#Little error in sequence
import asyncio
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

import os
import time
import random
import string
import threading
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from motor.motor_asyncio import AsyncIOMotorClient
from asyncio import Queue

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
MONGO_URI = os.getenv("MONGO_URI")
PORT = int(os.getenv("PORT",10000))

mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo["srcprotect"]

channels_db = db.channels
videos_db = db.videos
admins_db = db.admins

bot = Client("protectbot",api_id=API_ID,api_hash=API_HASH,bot_token=BOT_TOKEN)

upload_queue = Queue()

user_last_request={}

def allow_request(user):
    now=time.time()
    if user in user_last_request:
        if now-user_last_request[user] < 3:
            return False
    user_last_request[user]=now
    return True

def generate_token(length=10):
    chars=string.ascii_letters+string.digits
    return ''.join(random.choice(chars) for _ in range(length))

async def unique_token():
    while True:
        token=generate_token()
        exists=await videos_db.find_one({"token":token})
        if not exists:
            return token

async def is_admin(user):
    if user==ADMIN_ID:
        return True
    admin=await admins_db.find_one({"user_id":user})
    return bool(admin)

@bot.on_message(filters.command("id"))
async def getid(client,message):
    await message.reply_text(f"`{message.chat.id}`")

@bot.on_message(filters.command("addadmin"))
async def addadmin(client,message):
    if message.from_user.id!=ADMIN_ID:
        return
    user=int(message.command[1])
    await admins_db.insert_one({"user_id":user})
    await message.reply_text("Admin added")

@bot.on_message(filters.command("removeadmin"))
async def removeadmin(client,message):
    if message.from_user.id!=ADMIN_ID:
        return
    user=int(message.command[1])
    await admins_db.delete_one({"user_id":user})
    await message.reply_text("Admin removed")

@bot.on_message(filters.command("addprotect"))
async def addprotect(client,message):

    if not await is_admin(message.from_user.id):
        return

    storage=int(message.command[1])
    public=int(message.command[2])
    name=message.command[3]

    count=await channels_db.count_documents({})

    await channels_db.insert_one({
        "id":count+1,
        "name":name,
        "storage":storage,
        "public":public,
        "active":True
    })

    await message.reply_text("Protection added")

@bot.on_message(filters.command("protectlist"))
async def protectlist(client,message):

    if not await is_admin(message.from_user.id):
        return

    text="Protected Courses\n\n"

    async for c in channels_db.find():

        status="ACTIVE" if c["active"] else "STOPPED"

        text+=f"{c['id']}. {c['name']} ({status})\n"

    await message.reply_text(text)

@bot.on_message(filters.command("protectstop"))
async def protectstop(client,message):

    if not await is_admin(message.from_user.id):
        return

    cid=int(message.command[1])

    await channels_db.update_one({"id":cid},{"$set":{"active":False}})

    await message.reply_text("Protection stopped")

@bot.on_message(filters.command("protectrestart"))
async def protectrestart(client,message):

    if not await is_admin(message.from_user.id):
        return

    cid=int(message.command[1])

    await channels_db.update_one({"id":cid},{"$set":{"active":True}})

    await message.reply_text("Protection restarted")

@bot.on_message(filters.command("protectremove"))
async def protectremove(client,message):

    if not await is_admin(message.from_user.id):
        return

    cid=int(message.command[1])

    await channels_db.delete_one({"id":cid})
    await videos_db.delete_many({"course_id":cid})

    await message.reply_text("Protection removed")

@bot.on_message(filters.command("protectcleandb"))
async def cleandb(client,message):

    if not await is_admin(message.from_user.id):
        return

    cid=int(message.command[1])

    await videos_db.delete_many({"course_id":cid})

    await message.reply_text("Database cleaned for this course")

@bot.on_message(filters.channel & (filters.video | filters.document))
async def detect_storage(client,message):

    course=await channels_db.find_one({"storage":message.chat.id})

    if not course:
        return

    if not course["active"]:
        return

    await upload_queue.put((course,message))

async def upload_worker():

    while True:

        course,message = await upload_queue.get()

        try:

            token=await unique_token()

            await videos_db.insert_one({
                "course_id":course["id"],
                "token":token,
                "message_id":message.id
            })

            button=InlineKeyboardMarkup(
                [[InlineKeyboardButton(
                "▶ Watch Video",
                callback_data=f"watch_{course['id']}_{token}"
                )]]
            )

            await bot.send_message(
                course["public"],
                message.caption or "",
                reply_markup=button
            )

            await asyncio.sleep(1)

        except Exception as e:
            print("Worker error:",e)

        upload_queue.task_done()

@bot.on_callback_query()
async def callback_handler(client,query):

    data=query.data

    if not data.startswith("watch_"):
        return

    parts=data.split("_")

    if len(parts)!=3:
        return

    _,course_id,token=parts

    me=await client.get_me()

    await query.answer(
        url=f"https://t.me/{me.username}?start={course_id}_{token}"
    )

@bot.on_message(filters.command("start"))
async def start(client,message):

    user=message.from_user.id

    if not allow_request(user):
        return

    if len(message.command)==1:

        await message.reply_text(
        "This bot is private.\n\nContact @VIP_Official_gang_Bot")

        return

    payload=message.command[1]

    course_id,token=payload.split("_")

    course_id=int(course_id)

    course=await channels_db.find_one({"id":course_id})

    if not course:
        return

    member=await client.get_chat_member(course["public"],user)

    if member.status in ["left","kicked"]:
        return

    video=await videos_db.find_one({
        "course_id":course_id,
        "token":token
    })

    if not video:
        return

    await client.copy_message(
        chat_id=user,
        from_chat_id=course["storage"],
        message_id=video["message_id"],
        protect_content=True
    )

app=Flask(__name__)

@app.route("/")
def home():
    return "Bot Running"

def run():
    app.run("0.0.0.0",PORT)

threading.Thread(target=run).start()

loop.create_task(upload_worker())

bot.run()
