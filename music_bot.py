# -*- coding: utf-8 -*-
"""
بوتی گاردنیا - Telegram Voice Chat Call Music Assistant (Pyrogram + PyTgCalls)
"""

import os
import sys
import re
import json
import random
import asyncio
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import Message
from pytgcalls import GroupCallFactory
import yt_dlp

def load_music_config() -> dict:
    """وەرگرتنی نهێنییەکان لە config.jsonـی gitignored بۆ ئەوەی لە GitHub ئاشکرا نەبن."""
    config_path = Path(__file__).resolve().parent / "config.json"
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as config_file:
            return json.load(config_file)
    except Exception as exc:
        print(f"Music config warning: {exc}")
        return {}

MUSIC_CONFIG = load_music_config()

API_ID = int(os.environ.get("TELEGRAM_API_ID", 33605478))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "0026515a5d113337a0878ed2e6b1be10")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or MUSIC_CONFIG.get("token", "")
if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN لە Environment یان config.json دانەنراوە")

app = Client(
    "gardnya_music_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

app.send = app.invoke

group_call_factory = GroupCallFactory(app)
group_call = group_call_factory.get_file_group_call()

DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)

def download_youtube_audio(query_or_url: str):
    search_target = query_or_url if query_or_url.startswith("http") else f"ytsearch1:{query_or_url}"
    file_id = os.urandom(8).hex()
    out_template = str(DOWNLOADS_DIR / f"{file_id}.%(ext)s")

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': out_template,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'max_filesize': 25000000
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(search_target, download=True)
        if 'entries' in info and len(info['entries']) > 0:
            info = info['entries'][0]
        
        file_path = ydl.prepare_filename(info)
        title = info.get('title', 'گۆرانیی داواکراو')
        return file_path, title

@app.on_message(filters.command(["start", "help"]))
async def start_cmd(client: Client, message: Message):
    text = (
        f"🌸 سڵاو {message.from_user.first_name} گیان! من بەشی موزیکی بوتی گاردنیام 🎵\n\n"
        "فرمانەکانی پەخشکردن لە ناو کاڵ (Group Voice Call):\n"
        "• `/play ناوی گۆرانی یان لینک` - لێدانی گۆرانی لە کاڵ\n"
        "• `/pause` - ڕاگرتنی کاتیی گۆرانی\n"
        "• `/resume` - بەردەوامبوونی گۆرانی\n"
        "• `/stop` یان `/leave` - دەرچوون لە کاڵ"
    )
    await message.reply_text(text)

@app.on_message(filters.command(["play", "gorani", "music"]))
async def play_music_cmd(client: Client, message: Message):
    chat_id = message.chat.id
    query = message.text.split(maxsplit=1)
    
    if len(query) < 2:
        await message.reply_text("تکایە ناوی گۆرانییەک یان لینکی یوتوب بنووسە!\n\nنمونە: `/play شێروان عەبدوڵا`")
        return

    query_str = query[1]
    msg = await message.reply_text("⏳ گۆرانییەکە ئامادە دەکرێت و دەچمە ناو کاڵ... 🎵")

    try:
        file_path, title = await asyncio.to_thread(download_youtube_audio, query_str)
        
        group_call.input_filename = file_path
        if not group_call.is_connected:
            await group_call.start(chat_id)
        
        await msg.edit_text(f"🎵 **ئێستا پەخش دەبێت:**\n**{title}**\n\nبۆ ڕاگرتن: `/pause` | دەستپێکردنەوە: `/resume` | دەرچوون: `/stop`")
    except Exception as e:
        print("Play Error:", e)
        await msg.edit_text(f"کێشەیەک ڕوویدا: {e}\n\nدڵنیا ببەوە کە کاڵی گروپ کراوەتەوە و بوت ئەدمینە.")

@app.on_message(filters.command(["pause"]))
async def pause_cmd(client: Client, message: Message):
    try:
        group_call.pause_playout()
        await message.reply_text("⏸️ گۆرانییەکە ڕاوەستا.")
    except Exception as e:
        await message.reply_text(f"کێشە: {e}")

@app.on_message(filters.command(["resume"]))
async def resume_cmd(client: Client, message: Message):
    try:
        group_call.resume_playout()
        await message.reply_text("▶️ گۆرانییەکە دەستی پێ کردەوە.")
    except Exception as e:
        await message.reply_text(f"کێشە: {e}")

@app.on_message(filters.command(["stop", "leave"]))
async def stop_cmd(client: Client, message: Message):
    try:
        group_call.stop()
        await message.reply_text("⏹️ لە کاڵەکە دەرباز بووم.")
    except Exception as e:
        await message.reply_text(f"کێشە: {e}")

if __name__ == "__main__":
    print("===============================================")
    print("  Gardnya Voice Call Music Engine Started!")
    print("===============================================")
    app.run()
