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
#  Background Scheduler Management
# ═══════════════════════════════════════════════════════════════════════════════

scheduler_thread = None
scheduler_lock = threading.Lock()

def ensure_scheduler_running():
    """Make sure the background scheduler (mirror hours & prayer times) is running."""
    global scheduler_thread
    with scheduler_lock:
        if scheduler_thread is None or not scheduler_thread.is_alive():
            scheduler_thread = threading.Thread(target=main_bot.background_scheduler, daemon=True)
            scheduler_thread.start()
            print("⏰ Background scheduler (re)started!")

# ═══════════════════════════════════════════════════════════════════════════════
#  Flask Routes
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return '🌸 Gardnya Bot is alive and running 24/7! ✨'

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming Telegram updates via webhook."""
    try:
        data = request.get_json(force=True)
        if data and 'message' in data:
            main_bot.handle_message(data['message'])
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

# ═══════════════════════════════════════════════════════════════════════════════
#  Auto-setup on app load
# ═══════════════════════════════════════════════════════════════════════════════

# Exact domain for ramanyousif2002
WEBHOOK_URL = "https://ramanyousif2002.pythonanywhere.com/webhook"

# Set Telegram webhook
result = main_bot.tg_call("setWebhook", {"url": WEBHOOK_URL, "allowed_updates": ["message"]})
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
