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

API_ID=int(os.getenv("API_ID"))
API_HASH=os.getenv("API_HASH")
BOT_TOKEN=os.getenv("BOT_TOKEN")
ADMIN_ID=int(os.getenv("ADMIN_ID"))
MONGO_URI=os.getenv("MONGO_URI")
PORT=int(os.getenv("PORT",10000))
CONTACT=os.getenv("CONTACT_BOT","")

mongo=AsyncIOMotorClient(MONGO_URI)
db=mongo["srcprotect"]

channels=db.channels
videos=db.videos
admins=db.admins
users=db.users
viewer_stats=db.viewer_stats
watch_logs=db.watch_logs
sent_videos=db.sent_videos

bot=Client("bot",api_id=API_ID,api_hash=API_HASH,bot_token=BOT_TOKEN)

POST_DELAY=3
BUFFER_TIME=5

buffer=[]
last_receive=time.time()

BOT_USERNAME=None

def gen_token():
    return ''.join(random.choice(string.ascii_letters+string.digits) for _ in range(10))

async def unique_token():
    while True:
        t=gen_token()
        if not await videos.find_one({"token":t}):
            return t

async def is_admin(uid):
    if uid==ADMIN_ID:
        return True
    if await admins.find_one({"user_id":uid}):
        return True
    return False


# START
@bot.on_message(filters.command("start"))
async def start(client,message):

    user_id=message.from_user.id

    await users.update_one(
        {"user_id":user_id},
        {"$set":{"name":message.from_user.first_name}},
        upsert=True
    )

    if len(message.command)==1:
        await message.reply_text(f"This bot is private.\nContact {CONTACT}")
        return

    payload=message.command[1]

    try:
        course_id,token=payload.split("_")
    except:
        return

    course_id=int(course_id)

    course=await channels.find_one({"id":course_id})

    if not course:
        return

    user=user_id

    member=await client.get_chat_member(course["public"],user)

    if member.status in ["left","kicked"]:
        return

    video=await videos.find_one({"course_id":course_id,"token":token})

    if not video:
        return

    msg=await client.copy_message(
        chat_id=user,
        from_chat_id=course["storage"],
        message_id=video["message_id"],
        protect_content=True
    )

    await sent_videos.insert_one({
        "user_id":user,
        "course_id":course_id,
        "message_id":msg.id
    })

    await viewer_stats.update_one(
        {"course_id":course_id,"user_id":user},
        {"$inc":{"watch_count":1},
         "$set":{"name":message.from_user.first_name}},
        upsert=True
    )

    await watch_logs.insert_one({
        "user_id":user,
        "course_id":course_id,
        "video_id":video["message_id"],
        "time":time.time()
    })


# WATCH BUTTON
@bot.on_callback_query()
async def cb(client,query):

    global BOT_USERNAME

    if not query.data.startswith("watch_"):
        return

    _,course_id,token=query.data.split("_")

    if not BOT_USERNAME:
        me=await client.get_me()
        BOT_USERNAME=me.username

    await query.answer(
        url=f"https://t.me/{BOT_USERNAME}?start={course_id}_{token}"
    )


# STORAGE DETECTION
@bot.on_message(filters.channel & (filters.video | filters.document))
async def storage(client,message):

    global last_receive

    course=await channels.find_one({"storage":message.chat.id})

    if not course or not course.get("active",True):
        return

    buffer.append((course,message))
    last_receive=time.time()





# BROADCAST
@bot.on_message(filters.command("broadcast"))
async def broadcast(client,message):

    if not await is_admin(message.from_user.id):
        return

    if len(message.command)<2:
        await message.reply_text("Usage:\n/broadcast message")
        return

    text=message.text.split(None,1)[1]

    sent=0
    removed=0

    async for u in users.find():

        try:

            await client.send_message(u["user_id"],text)
            sent+=1
            await asyncio.sleep(0.1)

        except:
            await users.delete_one({"user_id":u["user_id"]})
            removed+=1

    await message.reply_text(
        f"Broadcast complete\nSent: {sent}\nRemoved blocked: {removed}"
    )
    
# WORKER
async def worker():

    global buffer

    while True:

        if buffer and time.time()-last_receive>BUFFER_TIME:

            buffer.sort(key=lambda x:x[1].id)

            for course,msg in buffer:

                sent=False

                while not sent:

                    try:

                        t=await unique_token()

                        await videos.insert_one({
                            "course_id":course["id"],
                            "token":t,
                            "message_id":msg.id
                        })

                        btn=InlineKeyboardMarkup(
                            [[InlineKeyboardButton(
                                "▶ Watch Video",
                                callback_data=f"watch_{course['id']}_{t}"
                            )]]
                        )

                        await bot.send_message(
                            course["public"],
                            msg.caption or "",
                            reply_markup=btn
                        )

                        sent=True

                        await asyncio.sleep(POST_DELAY)

                    except Exception as e:

                        txt=str(e)

                        if "FloodWait" in txt:

                            try:
                                wait=int(txt.split()[-2])
                            except:
                                wait=10

                            print("FloodWait detected. Waiting:",wait)

                            await asyncio.sleep(wait)

                        else:

                            print("Worker error:",e)

                            await asyncio.sleep(5)

            buffer=[]

        await asyncio.sleep(1)


# TOP VIEWERS
@bot.on_message(filters.command("topviewers"))
async def topviewers(client,message):

    if not await is_admin(message.from_user.id):
        return

    if len(message.command)<2:
        await message.reply_text("Usage:\n/topviewers course_id")
        return

    cid=int(message.command[1])

    text="👥 Channel-Wise Top Viewer Data:\n\n"

    i=1

    async for u in viewer_stats.find({"course_id":cid}).sort("watch_count",-1).limit(100):

        name=u.get("name","User")
        uid=u.get("user_id","")

        text+=f"{i}. {name} ({uid}) - {u['watch_count']} Videos\n"
        i+=1

    if i==1:
        text+="No data yet."

    await message.reply_text(text)


# USER STATS
@bot.on_message(filters.command("userstats"))
async def userstats(client,message):

    if not await is_admin(message.from_user.id):
        return

    if len(message.command)<2:
        return

    uid=int(message.command[1])

    total=await watch_logs.count_documents({"user_id":uid})

    today=time.time()-86400

    today_count=await watch_logs.count_documents({
        "user_id":uid,
        "time":{"$gt":today}
    })

    await message.reply_text(
        f"User {uid}\n\nTotal Videos: {total}\nToday: {today_count}"
    )


# PROTECT LIST
@bot.on_message(filters.command("protectlist"))
async def protectlist(client,message):

    if not await is_admin(message.from_user.id):
        return

    text="📚 Protected Courses\n\n"
    i=1

    async for c in channels.find():

        name=c.get("name","Unnamed")
        status="ACTIVE" if c.get("active",True) else "STOPPED"

        text+=f"{i}. {name} ({status})\n"
        i+=1

    if i==1:
        text+="No courses added yet."

    await message.reply_text(text)


# ADMIN MANAGEMENT
@bot.on_message(filters.command("addadmin"))
async def addadmin(client,message):

    if not await is_admin(message.from_user.id):
        return

    if len(message.command)<2:
        await message.reply_text("Usage:\n/addadmin user_id")
        return

    uid=int(message.command[1])

    if await admins.find_one({"user_id":uid}):
        await message.reply_text("Admin already exists.")
        return

    await admins.insert_one({"user_id":uid})

    await message.reply_text(f"Admin added:\n{uid}")


@bot.on_message(filters.command("removeadmin"))
async def removeadmin(client,message):

    if not await is_admin(message.from_user.id):
        return

    if len(message.command)<2:
        await message.reply_text("Usage:\n/removeadmin user_id")
        return

    uid=int(message.command[1])

    await admins.delete_one({"user_id":uid})

    await message.reply_text(f"Admin removed:\n{uid}")


# ID COMMAND
@bot.on_message(filters.command("id"))
async def get_id(client,message):

    if message.chat.type=="private":
        await message.reply_text(f"Your ID:\n{message.from_user.id}")
    else:
        await message.reply_text(f"Chat ID:\n{message.chat.id}")


# FLASK KEEPALIVE
app=Flask(__name__)

@app.route("/")
def home():
    return "Bot Running"

def run():
    app.run("0.0.0.0",PORT)

threading.Thread(target=run).start()

loop.create_task(worker())

bot.run()
