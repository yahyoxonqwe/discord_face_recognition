import cv2
import os
import json
import numpy as np
import onnxruntime
from scrfd import SCRFD
from arcface_onnx import ArcFaceONNX
import uuid
import sqlite3
from datetime import datetime, timedelta, time
import threading
from io import BytesIO
from PIL import Image
import asyncio
import flask
from flask import Response, render_template_string, url_for
import discord
from discord.ext import commands
from discord import File
from config import *  # MODELS_PATH, EMPLOYEES_JSON, DATABASE_PATH, DISCORD_TOKEN, USERS_MAPPING, images_path



# ---------- Discord Bot ----------
intents = discord.Intents.default()
intents.messages = True
intents.dm_messages = True
bot = commands.Bot(command_prefix='!', intents=intents)


# ---------- Setup face detection & recognition ----------
onnxruntime.set_default_logger_severity(3)
assets_dir = os.path.expanduser(MODELS_PATH)
detector = SCRFD(os.path.join(assets_dir, 'det_500m.onnx'))
detector.prepare(-1)
rec = ArcFaceONNX(os.path.join(assets_dir, 'w600k_mbf.onnx'))
rec.prepare(-1)

# Load known faces/features
data = json.load(open(EMPLOYEES_JSON, 'r'))

conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
cursor = conn.cursor()

# Globals for video capture
global frame_lock, current_frame
frame_lock = threading.Lock()
current_frame = None

# Compute BALL score (preserved your original function)
def get_ball(start, arrival_time, departure_time):
    limit = timedelta(hours=8, minutes=59)
    # agar 10:30 dan oldin kelgan bo'lsa
    if arrival_time < start + timedelta(hours=6, minutes=30):
        if departure_time - arrival_time > limit or departure_time > start + timedelta(hours=13, minutes=59):
            return "0"
        elif departure_time - arrival_time > limit - timedelta(minutes=10):
            return "-0.05"
        elif departure_time - arrival_time > limit - timedelta(hours=1):
            return "-0.1"
        elif departure_time - arrival_time > limit - timedelta(hours=2):
            return "-0.2"
        elif departure_time - arrival_time > limit - timedelta(hours=3):
            return "-0.3"
        elif departure_time - arrival_time > limit - timedelta(hours=4):
            return "-0.4"
        else:
            return "-0.5"
    # agar 14:00 dan oldin ketgan bo'lsa
    elif departure_time < start + timedelta(hours=13, minutes=59):
        if departure_time - arrival_time > limit - timedelta(minutes=10):
            return "-0.05"
        elif departure_time - arrival_time > limit - timedelta(hours=1):
            return "-0.1"
        elif departure_time - arrival_time > limit - timedelta(hours=2):
            return "-0.2"
        elif departure_time - arrival_time > limit - timedelta(hours=3):
            return "-0.3"
        elif departure_time - arrival_time > limit - timedelta(hours=4):
            return "-0.4"
        else:
            return "-0.5"
    # kech qaytgan holatlar
    else:
        if arrival_time < start + timedelta(hours=6, minutes=40):
            return "-0.05"
        elif arrival_time < start + timedelta(hours=7, minutes=30):
            return "-0.1"
        elif arrival_time < start + timedelta(hours=8, minutes=30):
            return "-0.2"
        elif arrival_time < start + timedelta(hours=9, minutes=30):
            return "-0.3"
        elif arrival_time < start + timedelta(hours=10, minutes=30):
            return "-0.4"
        else:
            return "-0.5"

# @bot.event
async def send_massage_and_img(user_id: int, message_text: str, image_buffer):
    """
    Fetches the User by ID, then DMs them `message_text` plus the image in `image_buffer`.
    """
    # fetch the user object
    user = await bot.fetch_user(user_id)

    # reset buffer to start
    image_buffer.seek(0)
    discord_file = discord.File(fp=image_buffer, filename="image.png")

    # Option A: plain text + file
    await user.send(content=message_text, file=discord_file)

async def send_massage(user_id: int, message_text: str):
    """
    Fetches the User by ID, then DMs them `message_text`
    """
    # fetch the user object
    user = await bot.fetch_user(user_id)
    await user.send(content=message_text)

# Frame capture thread
def capture_frames():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError("Cannot open camera")
    global current_frame
    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        with frame_lock:
            current_frame = frame.copy()

# Convert crop to bytes for Discord
def frame_to_bytesio(frame_crop):
    rgb = cv2.cvtColor(frame_crop, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb)
    buf = BytesIO()
    buf.name = f"{uuid.uuid4()}.jpg"
    img.save(buf, format='JPEG')
    buf.seek(0)
    return buf

# Async inference: detect, DB update, notify
async def inference(frame):
    global daily_time, data, images_path
    img = frame
    try:
        faces, kpss = detector.autodetect(img, max_num=20)
    except:pass

    # Get current datetime
    current_time = datetime.now().replace(microsecond=0) #+ timedelta(hours=17, minutes=30)

    # Define the start and end times for the time interval
    start_time = current_time.replace(hour=4, minute=1, second=0, microsecond=0)


    info = []
    
    
    for face, kps in zip(faces, kpss):
        
        x_min, y_min, x_max, y_max, confidence = int(face[0]), int(face[1]), int(face[2]), int(face[3]) ,face[4]
        if x_min < 0 or y_min < 0 or x_max < 0 or y_max < 0:
            continue

        feat = rec.get(img, kps)

        maxi = -1
        ID = 'person' + str(uuid.uuid4())
        
        
        for db_id , db_feats in data.items():
            for db_feat in db_feats:
                similarity = rec.compute_sim(feat, np.array(db_feat))
                if similarity > maxi:
                    maxi = similarity
                    ID = db_id  
        odam = img[y_min:y_max, x_min:x_max]      
        
        if 0.2 <= maxi < 0.4:
            continue
        elif maxi < 0.2:
            ID = 'person' + str(uuid.uuid4())
            data.setdefault(ID, []).append(feat)
        info.append([ID, [y_min, y_max, x_min, x_max]])
            

        random_filename = os.path.join(images_path, f"{str(uuid.uuid4())}.jpg")

        # Check if the current time is within the time interval
        if datetime.strptime('00:00', '%H:%M').time() < current_time.time() < datetime.strptime('04:00', '%H:%M').time():
            start_time -= timedelta(days=1)

        try:
            cursor.execute("SELECT departure_time FROM users WHERE name = ? ORDER BY departure_time DESC LIMIT 1", (ID,))
            last_seen = cursor.fetchone()[0]
        except:
            last_seen = current_time.strftime('%Y-%m-%d %H:%M:%S')

        # Perform your database operations here
        cursor.execute("UPDATE users SET departure_time = ? WHERE name = ? AND arrival_time >= ?", (current_time.strftime('%Y-%m-%d %H:%M:%S'), ID, start_time))
        check = True
        if cursor.rowcount == 0:
            cursor.execute("INSERT INTO users (name, arrival_time, departure_time, image) VALUES (?,  ?, ?, ?)", (ID, current_time.strftime('%Y-%m-%d %H:%M:%S'), current_time.strftime('%Y-%m-%d %H:%M:%S'), random_filename))   
            if not ID.startswith('person'):
                message_text_start = "Assalomu aleykum " + ID +" \nXush kelibsiz !!!\n\n" + "Kelgan vaqtingiz  :  " + current_time.strftime('%H:%M:%S')
                buf = frame_to_bytesio(img[y_min:y_max, x_min:x_max])

                await send_massage_and_img(USERS_MAPPING[ID], message_text_start, buf)
                
            
            check = False
            cv2.imwrite(random_filename, odam) 

        time_difference = current_time - datetime.strptime(last_seen, '%Y-%m-%d %H:%M:%S')
        if check and not ID.startswith('person') and time_difference > timedelta(minutes=1):
            message_text_repeat = "Qayta ko'rindingiz :  " + str(ID) + "\nKo'ringan vaqtingiz  :  " + current_time.strftime('%H:%M:%S')
            buf = frame_to_bytesio(img[y_min:y_max, x_min:x_max])

            # send massage
            await send_massage_and_img(USERS_MAPPING[ID], message_text_repeat, buf)


#### Ko'rib chiqish shu joyini 
    if  daily_time == current_time:
        cursor.execute("SELECT name, departure_time FROM users  WHERE  arrival_time >= ?", (start_time-timedelta(days=1), ))
        total_seen = cursor.fetchall()
        for shaxs, departure_time in total_seen:
            if not shaxs.startswith('person') and shaxs in users_list.keys(): 
                text = shaxs + "\nIshdan ketgan vaqtingiz:  " + departure_time
                try:
                    user = bot.get_user(USERS_MAPPING[shaxs])
                    await user.send(content=message_text_start)
                except Exception as e:pass

        commands = defaultdict(list)
        for key, value in data.items():
            if not key.startswith('unknown'):
                commands[key] = value
        data = commands
        daily_time += timedelta(days=1)
        
    conn.commit()
    return info

# ---------- Flask app ----------
app = flask.Flask(__name__)
HTML = """
<!DOCTYPE html>
<html><body>
  <img src='{{ url_for('video_feed') }}' style='width:100vw;height:100vh;object-fit:cover;'>
</body></html>
"""
@app.route('/')
def index():
    return render_template_string(HTML)
@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

def gen_frames():
    while True:
        with frame_lock:
            f = current_frame
        if f is None:
            continue
        future = asyncio.run_coroutine_threadsafe(inference(f), bot.loop)
        infos = future.result(timeout=5)
        for uid, (y1, y2, x1, x2) in infos:
            cv2.rectangle(f, (x1, y1), (x2, y2), (0,255,0), 2)
            cv2.putText(f, uid, (x1, max(y1-10,0)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,0), 2)
        ret, jpeg = cv2.imencode('.jpg', f)
        if not ret:
            continue
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')



daily_time = datetime.now().replace(hour=4, minute=0, second=30, microsecond=0) + timedelta(days=1)

@bot.event
async def on_ready():
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False), daemon=True).start()
    asyncio.create_task(daily_report_task())

async def daily_report_task():
    """
    Ushbu funksiya har kuni soat 04:00 atrofida quyidagi ishlarni bajaradi:
    1) Bazadan "arrival_time >= (daily_time - 1 kun)" yozuvlarni olib keladi.
    2) 'unknown' bilan boshlanmaydigan ismlar bo‘yicha foydalanuvchiga message jo‘natadi.
    3) data lug‘atidagi 'unknown' kalitlarini tozalaydi.
    4) daily_time ni keyingi kun 04:00 ga oshiradi.
    """
    global daily_time, data, users_list, cursor  # agar bu o‘zgaruvchilar global e’lon qilingan bo‘lsa


    # Agar hozirgi vaqt daily_time (ya’ni, kelishgan 04:00) ga teng bo‘lsa:
    if datetime.now() == daily_time:

        # 2. "arrival_time == (start_time - 1 kun)" sharti bo‘yicha DB dan nom va departure_time ni olamiz
        yesterday = start_time - timedelta(days=1)
        cursor.execute(
            "SELECT name, departure_time FROM users WHERE arrival_time >= ?",
            (yesterday,)
        )
        total_seen = cursor.fetchall()

        # 3. Har bir (shaxs, departure_time) juftligini tekshirib, 'unknown' bilan boshlanmagan bo‘lsa,
        #    agar users_list da shaxs bo‘lsa, foydalanuvchiga "departure_time" xabarini jo‘natamiz
        for shaxs, departure_time in total_seen:
            if not shaxs.startswith('unknown') and (shaxs in users_list):
                try:
                    # Agar bu Discord Bot bo‘lsa:
                    user_id = users_list[shaxs]
                    discord_user = bot.get_user(user_id)
                    if discord_user:
                        await discord_user.send(f"{shaxs}\nIshdan ketgan vaqtingiz: {departure_time}")

                    # Agar bu Telegram Async Bot bo‘lsa, masalan aiogram/pyrogram:
                    # await bot.send_message(user_id, f"{shaxs}\nIshdan ketgan vaqtingiz: {departure_time}")

                except Exception:
                    # Xatolik yuz bersa ham e’tiborsiz o'tkazamiz
                    pass

        # 4. data lug‘atidan 'unknown' bilan boshlanadigan kalitlarni olib tashlaymiz
        commands = defaultdict(list)
        for key, value in data.items():
            if not key.startswith('unknown'):
                commands[key] = value
        data = commands  # eski 'data' ustiga yangilangan lug‘atni yozib qo‘yamiz

        # 5. Endi new_daily_time = old_daily_time + 1 kun
        daily_time += timedelta(days=1)

    # Har 60 soniyada bir marotaba tekshiramiz
    await asyncio.sleep(60)

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if isinstance(message.channel, discord.DMChannel):
        parts = message.content.strip().split('\n', 1)
        try:
            msg_date = datetime.strptime(parts[0], '%d-%m-%Y').date()
        except:
            return await message.channel.send("Sana noto'g'ri. DD-MM-YYYY formatida bo'ling.")
        uid = next((name for name, id_ in USERS_MAPPING.items() if id_ == message.author.id), None)
        if not uid:
            return await message.channel.send("Ro'yxatda yo'qsiz.")
        if len(parts) == 1:
            cursor.execute(
                "SELECT arrival_time, departure_time, reason FROM users WHERE name=? AND DATE(arrival_time)=? ORDER BY arrival_time DESC LIMIT 1",
                (uid, msg_date.isoformat())
            )
            row = cursor.fetchone()
            if not row:
                return await message.channel.send("Bu sana bo'yicha yozuv yo'q.")
            arr, dep, reason = row
            BALL = get_ball(
                datetime.combine(msg_date, time(4,0)),
                datetime.strptime(arr, '%Y-%m-%d %H:%M:%S'),
                datetime.strptime(dep, '%Y-%m-%d %H:%M:%S')
            )
            return await message.channel.send(
                f"Sana: {parts[0]}\nKeldi: {arr}\nKetdi: {dep}\nBALL: {BALL}\nSabab: {reason or '🙅‍♂️'}"
            )
        # update reason
        reason = parts[1].strip()
        cursor.execute(
            "UPDATE users SET reason=? WHERE name=? AND DATE(arrival_time)=?",
            (reason, uid, msg_date.isoformat())
        )
        conn.commit()
        return await message.channel.send(f"Sabab saqlandi: {reason}")
    await bot.process_commands(message)
 
# ---------- Main ----------
if __name__ == '__main__':
    threading.Thread(target=capture_frames, daemon=True).start()
    bot.run(DISCORD_TOKEN)

















