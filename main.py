#!/usr/bin/env python3
import asyncio
import logging
import os
import json
from datetime import datetime
from aiohttp import web
from telethon import TelegramClient, events
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError
)

# ================= CONFIG =================
TARGET_BOT = "Leaskdd_bases_bot"   # bypass bot username
SESSION = "ultimate.session"

API_HOST = "0.0.0.0"
API_PORT = int(os.getenv("PORT", 10000))

# ================= FILES =================
RULES_FILE = "rules.json"
HISTORY_FILE = "history.json"

# ================= GLOBAL STATE =================
client = None
PHONE = None
LOGIN_IN_PROGRESS = False
USERBOT_INITIALIZED = False

DELETE_ENABLED = True            # /start /stop switch
RULES = {}                       # {"hello bhai": 0.1}
DELETE_HISTORY = []              # logs

routes = web.RouteTableDef()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SilentDelete")

# ================= UTILS =================
def save_rules():
    with open(RULES_FILE, "w") as f:
        json.dump(RULES, f)

def load_rules():
    global RULES
    if os.path.exists(RULES_FILE):
        with open(RULES_FILE, "r") as f:
            RULES = json.load(f)

def save_history():
    with open(HISTORY_FILE, "w") as f:
        json.dump(DELETE_HISTORY, f)

def load_history():
    global DELETE_HISTORY
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            DELETE_HISTORY = json.load(f)

# ================= LOGIN APIs =================
@routes.get("/login/start/{api_id}/{api_hash}/{phone}")
async def login_start(request):
    global client, PHONE, LOGIN_IN_PROGRESS

    if LOGIN_IN_PROGRESS:
        return web.json_response({"error": "login_in_progress"})

    api_id = int(request.match_info["api_id"])
    api_hash = request.match_info["api_hash"]
    PHONE = request.match_info["phone"]

    client = TelegramClient(SESSION, api_id, api_hash)
    await client.connect()

    if await client.is_user_authorized():
        return web.json_response({"status": "already_logged_in"})

    LOGIN_IN_PROGRESS = True
    await client.send_code_request(PHONE)
    return web.json_response({"status": "otp_sent"})


@routes.get("/login/otp/{otp}")
async def login_otp(request):
    global LOGIN_IN_PROGRESS
    try:
        await client.sign_in(PHONE, request.match_info["otp"])
        LOGIN_IN_PROGRESS = False
        return web.json_response({"status": "login_success"})
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        return web.json_response({"error": "invalid_otp"})


@routes.get("/login/password/{password}")
async def login_password(request):
    global LOGIN_IN_PROGRESS
    try:
        await client.sign_in(password=request.match_info["password"])
        LOGIN_IN_PROGRESS = False
        return web.json_response({"status": "login_success"})
    except Exception as e:
        return web.json_response({"error": str(e)})

# ================= RULE APIs =================
@routes.get("/add/{text}")
async def add_rule(request):
    text = request.match_info["text"]
    delay = float(request.query.get("delay", "0").replace("s", ""))
    RULES[text] = delay
    save_rules()
    return web.json_response({
        "status": "rule_added",
        "text": text,
        "delay": delay
    })


@routes.get("/remove/{text}")
async def remove_rule(request):
    text = request.match_info["text"]
    if text in RULES:
        del RULES[text]
        save_rules()
        return web.json_response({"status": "rule_removed", "text": text})
    return web.json_response({"error": "rule_not_found"}, status=404)


@routes.get("/rules")
async def list_rules(request):
    return web.json_response(RULES)

# ================= START / STOP =================
@routes.get("/stop")
async def stop_delete(request):
    global DELETE_ENABLED
    DELETE_ENABLED = False
    return web.json_response({
        "status": "stopped",
        "delete_enabled": DELETE_ENABLED
    })


@routes.get("/start")
async def start_delete(request):
    global DELETE_ENABLED
    DELETE_ENABLED = True
    return web.json_response({
        "status": "started",
        "delete_enabled": DELETE_ENABLED
    })

# ================= HISTORY =================
@routes.get("/history")
async def history(request):
    return web.json_response({
        "total": len(DELETE_HISTORY),
        "data": DELETE_HISTORY[::-1]
    })

# ================= USERBOT HANDLER =================
async def init_userbot():
    global USERBOT_INITIALIZED
    if USERBOT_INITIALIZED:
        return

    @client.on(events.NewMessage(from_users=[TARGET_BOT, 'me']))
    async def handler(event):
        if not DELETE_ENABLED:
            return

        text = event.raw_text or ""
        matched = False

        for key, delay in RULES.items():
            if key in text:
                matched = True
                if delay > 0:
                    await asyncio.sleep(delay)
                await event.delete()
                log_entry = {
                    "text": text,
                    "rule": key,
                    "delay": delay,
                    "time": datetime.now().isoformat()
                }
                DELETE_HISTORY.append(log_entry)
                save_history()
                break
        # ✅ No default delete anymore

    USERBOT_INITIALIZED = True
    logger.info("✅ Silent delete handler active (user + bypass bot)")

# ================= HEALTH =================
@routes.get("/health")
async def health(request):
    return web.json_response({
        "authorized": await client.is_user_authorized() if client else False,
        "delete_enabled": DELETE_ENABLED,
        "rules": RULES,
        "logs": len(DELETE_HISTORY),
        "time": datetime.now().isoformat()
    })

# ================= MAIN =================
async def main():
    load_rules()
    load_history()
    app = web.Application()
    app.add_routes(routes)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, API_HOST, API_PORT)
    await site.start()

    logger.info(f"🌐 API running on {API_HOST}:{API_PORT}")

    while True:
        if client and client.is_connected() and await client.is_user_authorized():
            await init_userbot()
        await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())
