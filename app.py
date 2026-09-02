# -*- coding: utf-8 -*-
"""
بوتی گاردنیا - Flask Webhook Version for PythonAnywhere 24/7
This file runs the bot using webhooks instead of polling,
so it stays alive forever on PythonAnywhere's free web hosting.
"""

import os
import sys
import threading
import hashlib
import hmac
import time
from concurrent.futures import ThreadPoolExecutor

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request

# Import all bot functions
import main_bot

app = Flask(__name__)

# Telegram هەر webhook ـێک بە secret header پشتڕاست دەکاتەوە؛ کەسی دەرەوە
# ناتوانێت update ـی ساختە بنێرێت و فرمانی ئەدمین جێبەجێ بکات.
def get_webhook_secret():
    sec = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if sec:
        return sec
    tok = main_bot.live_config_secret("token", "TELEGRAM_BOT_TOKEN") or main_bot.BOT_TOKEN or ""
    if tok:
        return hashlib.sha256(tok.encode("utf-8")).hexdigest()
    return ""

DEPLOY_SECRET = os.environ.get("GARDNYA_DEPLOY_SECRET", "").strip()

# ═══════════════════════════════════════════════════════════════════════════════
#  Background Scheduler & Keep-Alive 24/7 Management
# ═══════════════════════════════════════════════════════════════════════════════

scheduler_thread = None
keepalive_thread = None
scheduler_lock = threading.Lock()
telegram_setup_thread = None
telegram_setup_lock = threading.Lock()
telegram_setup_status = {
    "ok": False,
    "last_attempt": 0.0,
    "detail": "starting",
}
update_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gardnya-update")
processed_updates = {}
processed_updates_lock = threading.Lock()

WEBHOOK_DOMAIN = "raman1206.pythonanywhere.com"
WEBHOOK_URL = f"https://{WEBHOOK_DOMAIN}/webhook"

def keep_alive_worker():
    """Pings the web app every 3 minutes so PythonAnywhere WSGI worker never goes to sleep."""
    import time
    import requests
    time.sleep(20)
    while True:
        try:
            requests.get(f"https://{WEBHOOK_DOMAIN}/health", timeout=15)
        except Exception:
            pass
        time.sleep(180)

def ensure_scheduler_running():
    """Make sure the background scheduler (mirror hours & prayer times) and keep-alive are running."""
    global scheduler_thread, keepalive_thread
    with scheduler_lock:
        if scheduler_thread is None or not scheduler_thread.is_alive():
            scheduler_thread = threading.Thread(target=main_bot.background_scheduler, daemon=True)
            scheduler_thread.start()
            print("⏰ Background scheduler (re)started!")
        if keepalive_thread is None or not keepalive_thread.is_alive():
            keepalive_thread = threading.Thread(target=keep_alive_worker, daemon=True)
            keepalive_thread.start()
            print("🔄 Keep-alive 24/7 pinger started!")

# ═══════════════════════════════════════════════════════════════════════════════
#  Flask Routes
# ═══════════════════════════════════════════════════════════════════════════════

import subprocess

@app.route('/')
def index():
    return '🌸 Gardnya Bot is alive and running 24/7! ✨'

@app.route('/webhook', methods=['POST'])
def webhook():
    """Telegram updates وەربگرە؛ ئەگەر پێویست بوو scheduler دەستپێبکە"""
    expected_secret = get_webhook_secret()
    received_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if expected_secret and received_secret and not hmac.compare_digest(received_secret, expected_secret):
        return "Forbidden", 403
    ensure_scheduler_running()
    try:
        data = request.get_json(force=True)
        if not data:
            return 'OK', 200
        update_id = data.get("update_id")
        if update_id is not None:
            now = time.time()
            with processed_updates_lock:
                # Telegram لە کاتی دواکەوتن هەمان update دووبارە دەنێرێت.
                for old_id, seen_at in list(processed_updates.items()):
                    if now - seen_at > 1800:
                        processed_updates.pop(old_id, None)
                if update_id in processed_updates:
                    return 'OK', 200
                processed_updates[update_id] = now
        update_executor.submit(process_telegram_update, data)
    except Exception as e:
        print(f"Webhook receive error: {e}")
    return 'OK', 200

def process_telegram_update(data):
    """یەک update لە پاشبنەما جێبەجێ بکە تا Telegram timeout نەکات."""
    try:
        if 'message' in data:
            main_bot.handle_message(data['message'])
        elif 'chat_member' in data:
            main_bot.handle_chat_member_update(data['chat_member'])
        elif 'my_chat_member' in data:
            main_bot.handle_chat_member_update(data['my_chat_member'])
    except Exception as exc:
        print(f"Webhook processing error: {type(exc).__name__}: {exc}")

@app.route('/health')
def health():
    """Health check endpoint."""
    ensure_scheduler_running()
    tok = main_bot.live_config_secret("token", "TELEGRAM_BOT_TOKEN") or main_bot.BOT_TOKEN or ""
    tok_preview = f"{tok[:6]}...{tok[-4:]}" if len(tok) > 10 else ("none" if not tok else "short")
    groq_state = "configured" if main_bot.GROQ_API_KEY else "missing-key"
    gemini_state = "configured" if main_bot.GEMINI_API_KEY else "missing-key"
    bot_state = "ready" if tok else "missing-token"
    return (
        f'✅ Bot healthy, scheduler running | Telegram: ready | Bot: {bot_state} ({tok_preview}) '
        f'| Groq: {groq_state} | Gemini: {gemini_state} | Domain: {WEBHOOK_DOMAIN}'
    ), 200

@app.route('/pull', methods=['GET', 'POST'])
def git_pull():
    """Trigger automatic git pull on PythonAnywhere via URL."""
    received_secret = request.headers.get("X-Gardnya-Deploy-Secret", "")
    if not DEPLOY_SECRET or not hmac.compare_digest(received_secret, DEPLOY_SECRET):
        return "Not found", 404
    try:
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        res = subprocess.run(["git", "pull"], cwd=repo_dir, capture_output=True, text=True, timeout=30)
        return f"🚀 Git Pull Output:\n{res.stdout}\n{res.stderr}", 200
    except Exception as e:
        return f"⚠️ Git Pull Error: {e}", 500

# ═══════════════════════════════════════════════════════════════════════════════
#  Auto-setup on app load
# ═══════════════════════════════════════════════════════════════════════════════

def configure_telegram_worker():
    """Telegram ڕێکبخە و ناسنامەی بۆت لە تێلێگرام نوێ بکەرەوە."""
    telegram_setup_status["last_attempt"] = time.time()
    main_bot.refresh_bot_identity()
    live_tok = main_bot.BOT_TOKEN or ""
    sec = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not sec and live_tok:
        sec = hashlib.sha256(live_tok.encode("utf-8")).hexdigest()
    result = main_bot.tg_call("setWebhook", {
        "url": WEBHOOK_URL,
        "allowed_updates": ["message", "my_chat_member", "chat_member"],
        "secret_token": sec,
    })
    if result and result.get("ok"):
        telegram_setup_status["ok"] = True
        telegram_setup_status["detail"] = "ready"
        print(f"🌐 Webhook set successfully: {WEBHOOK_URL}")
    else:
        telegram_setup_status["ok"] = False
        telegram_setup_status["detail"] = (
            "invalid-token" if result and result.get("error_code") == 401 else (result.get("description", "setup-failed") if result else "no-response")
        )
        print(f"⚠️ Webhook setup result: {result}")

def ensure_telegram_configured(force=False):
    """Webhook لە کاتی startup و health خۆکار چاک و نوێ بکەرەوە."""
    global telegram_setup_thread
    import time
    with telegram_setup_lock:
        if telegram_setup_thread is not None and telegram_setup_thread.is_alive():
            return
        age = time.time() - telegram_setup_status["last_attempt"] if telegram_setup_status["last_attempt"] else 999999
        if force and age < 30:
            return
        if not force and telegram_setup_status["ok"] and age < 900:
            return
        telegram_setup_status["detail"] = "repairing"
        telegram_setup_thread = threading.Thread(target=configure_telegram_worker, daemon=True)
        telegram_setup_thread.start()


print("═══════════════════════════════════════════════")
print("  🌸 Gardnya Bot - 24/7 Webhook Mode Active!")
print(f"  📡 Webhook: {WEBHOOK_URL}")
print("═══════════════════════════════════════════════")
