# -*- coding: utf-8 -*-
"""
بوتی گاردنیا - Flask Webhook Version for PythonAnywhere 24/7
This file runs the bot using webhooks instead of polling,
so it stays alive forever on PythonAnywhere's free web hosting.
"""

import os
import sys
import threading

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request

# Import all bot functions
import main_bot

app = Flask(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
#  Background Scheduler & Keep-Alive 24/7 Management
# ═══════════════════════════════════════════════════════════════════════════════

scheduler_thread = None
keepalive_thread = None
scheduler_lock = threading.Lock()

def keep_alive_worker():
    """Pings the web app every 3 minutes so PythonAnywhere WSGI worker never goes to sleep."""
    import time
    import requests
    time.sleep(20)
    while True:
        try:
            requests.get("https://ramanyousif2002.pythonanywhere.com/health", timeout=15)
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
    """Handle incoming Telegram updates via webhook."""
    try:
        data = request.get_json(force=True)
        if data:
            if 'message' in data:
                main_bot.handle_message(data['message'])
            elif 'chat_member' in data:
                main_bot.handle_chat_member_update(data['chat_member'])
            elif 'my_chat_member' in data:
                chat = data['my_chat_member'].get('chat', {})
                if chat.get('type') in ['group', 'supergroup']:
                    main_bot.register_group(chat['id'])
                    print(f"🎉 Auto-registered group {chat.get('title')} ({chat['id']})")
    except Exception as e:
        print(f"Webhook error: {e}")
    # Ensure scheduler is alive on every webhook call
    ensure_scheduler_running()
    return 'OK', 200

@app.route('/health')
def health():
    """Health check endpoint."""
    ensure_scheduler_running()
    return '✅ Bot healthy, scheduler running', 200

@app.route('/pull', methods=['GET', 'POST'])
def git_pull():
    """Trigger automatic git pull on PythonAnywhere via URL."""
    try:
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        res = subprocess.run(["git", "pull"], cwd=repo_dir, capture_output=True, text=True, timeout=30)
        return f"🚀 Git Pull Output:\n{res.stdout}\n{res.stderr}", 200
    except Exception as e:
        return f"⚠️ Git Pull Error: {e}", 500

# ═══════════════════════════════════════════════════════════════════════════════
#  Auto-setup on app load
# ═══════════════════════════════════════════════════════════════════════════════

# Exact domain for ramanyousif2002
WEBHOOK_URL = "https://ramanyousif2002.pythonanywhere.com/webhook"

# Set Telegram webhook with chat_member support
result = main_bot.tg_call("setWebhook", {
    "url": WEBHOOK_URL,
    "allowed_updates": ["message", "my_chat_member", "chat_member"]
})
if result and result.get("ok"):
    print(f"🌐 Webhook set successfully: {WEBHOOK_URL}")
else:
    print(f"⚠️ Webhook setup result: {result}")

# Start background scheduler
ensure_scheduler_running()

print("═══════════════════════════════════════════════")
print("  🌸 Gardnya Bot - 24/7 Webhook Mode Active!")
print(f"  📡 Webhook: {WEBHOOK_URL}")
print("═══════════════════════════════════════════════")
