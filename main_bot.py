# -*- coding: utf-8 -*-
"""
بوتی گاردنیا - Gardnya Telegram Security, Smart AI & Group Companion Bot
"""

import os
import re
import sys
import json
import time
import random
import threading
import datetime
import base64
import difflib
import importlib.util
import shutil
import subprocess
import tempfile
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
#  ڕێکخستنەکان (Credentials & Configuration)
# ═══════════════════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent
# WSGI/PythonAnywhere هەندێک جار working directory ـەکە دەگۆڕێت. بۆیە
# config هەمیشە لە هەمان فۆڵدەری main_bot.py دەخوێندرێتەوە.
CONFIG_FILE = BASE_DIR / "config.json"
CONFIG_SOURCES = []
config = {
    "token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
    "botUsername": os.environ.get("BOT_USERNAME", "gardny4_bot"),
    "geminiApiKey": os.environ.get("GEMINI_API_KEY", ""),
    "googleVisionApiKey": os.environ.get("GOOGLE_VISION_API_KEY", ""),
    "groqApiKey": os.environ.get("GROQ_API_KEY", ""),
    "groqModel": "llama-3.3-70b-versatile",
    "aiEnabled": True,
    "aiInPrivateChats": True,
    "aiHistoryMessages": 10,
    "blockNSFWStickers": True,
    "blockNSFWGIFs": True,
    "blockNSFWPhotos": True,
    "blockLinks": True,
    "blockBadWords": True,
    "enableMirrorHours": True,
    "enablePrayerTimes": True,
    "maxWarnings": 3,
    "autoMuteMinutes": 60
}

def load_config_file(path: Path, quiet: bool = False) -> dict:
    """ڕێکخستنەکان لە فایل بخوێنەوە، بە بێ پیشاندانی نهێنییەکان."""
    try:
        if path.exists() and path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                return loaded
    except Exception as exc:
        if not quiet:
            print(f"Warning: Failed to load configuration ({type(exc).__name__})")
    return {}

# ڕێگای سەرەکی هەمیشە فۆڵدەری خۆی بۆتە. `cwd` ـیش تەنها وەک پشتیوانیە
# بۆ کۆنفیگی کۆنەکانی PythonAnywhere.
for _candidate in (Path.cwd() / "config.json", CONFIG_FILE):
    _candidate = _candidate.resolve()
    if _candidate not in CONFIG_SOURCES:
        _loaded_config = load_config_file(_candidate)
        if _loaded_config:
            config.update(_loaded_config)
            CONFIG_SOURCES.append(_candidate)

def config_secret_or_env(config_key: str, environment_key: str, *aliases: str) -> str:
    """ڕێگری لەوەی بەها نموونەییەکان بوتەکە وەستێنن."""
    value = ""
    for key in (config_key, *aliases):
        candidate = str(config.get(key, "") or "").strip()
        if candidate:
            value = candidate
            break
    placeholder_prefixes = ("YOUR_", "PASTE_", "TOKEN_")
    if not value or value.upper().startswith(placeholder_prefixes):
        return os.environ.get(environment_key, "")
    return value

def live_config_secret(config_key: str, environment_key: str, *aliases: str) -> str:
    """کلیلی AI لە config ـی نوێ بخوێنەوە؛ ئەمە پێویستی بە restart بۆ گۆڕینی کلیل کەم دەکات."""
    keys = (config_key, *aliases)
    placeholder_prefixes = ("YOUR_", "PASTE_", "TOKEN_")
    # لە شوێنی سەرەکی بۆتەوە دەست پێبکە؛ ئەوە کۆنفیگی نوێترینە.
    for path in (CONFIG_FILE, Path.cwd() / "config.json"):
        fresh = load_config_file(path, quiet=True)
        for key in keys:
            value = str(fresh.get(key, "") or "").strip()
            if value and not value.upper().startswith(placeholder_prefixes):
                return value
    return config_secret_or_env(config_key, environment_key, *aliases)

BOT_TOKEN = config_secret_or_env("token", "TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = config_secret_or_env("geminiApiKey", "GEMINI_API_KEY")
GOOGLE_VISION_API_KEY = config_secret_or_env(
    "googleVisionApiKey",
    "GOOGLE_VISION_API_KEY",
    "googleVisionAPIKey",
    "visionApiKey",
)
GROQ_API_KEY = config_secret_or_env("groqApiKey", "GROQ_API_KEY")
GROQ_MODEL = config.get("groqModel", "llama-3.3-70b-versatile")
MAX_WARNINGS = int(config.get("maxWarnings", 3))
AUTO_MUTE_MINUTES = int(config.get("autoMuteMinutes", 60))

# Kurdistan Timezone (UTC+3)
KURDISTAN_UTC_OFFSET = datetime.timezone(datetime.timedelta(hours=3))

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

# پەیوەندیی جێگیرتر بۆ پراکسیی PythonAnywhere و هەڵە کاتییەکانی 502/503/504
telegram_session = requests.Session()
telegram_retry = Retry(
    total=4,
    connect=4,
    read=2,
    backoff_factor=1.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET", "POST"}),
    raise_on_status=False,
)
telegram_session.mount("https://", HTTPAdapter(max_retries=telegram_retry))
telegram_error_state = {"count": 0, "last_log": 0.0}

# مۆدێلی خۆجێیی و بێ‌بەرامبەر بۆ ناسینەوەی ڕووتی و ناوەڕۆکی سێکسی.
# بە lazy-loading دەکرێتەوە بۆ ئەوەی دەستپێکردنی بۆت خێرا بێت و مۆدێل تەنها
# لە یەکەم پشکنینی میدیا بار بکرێت.
local_nsfw_detector = None
local_nsfw_detector_failed = False
local_nsfw_detector_lock = threading.Lock()
LOCAL_NSFW_THRESHOLDS = {
    "FEMALE_BREAST_EXPOSED": 0.45,
    "FEMALE_GENITALIA_EXPOSED": 0.45,
    "MALE_GENITALIA_EXPOSED": 0.45,
    "ANUS_EXPOSED": 0.45,
    "BUTTOCKS_EXPOSED": 0.55,
}
google_vision_status = {
    "last_check": 0.0,
    "http_status": 0,
    "result": "هێشتا پشکنین نەکراوە",
}
telegram_media_status = {
    "stage": "هێشتا فایلێک داوانەکراوە",
}

# Initialize Groq AI Client (fallback)
groq_client = None
if GROQ_API_KEY:
    try:
        import groq
        groq_client = groq.Groq(api_key=GROQ_API_KEY)
    except Exception as e:
        print(f"Groq Init Warning: {e}")

def groq_model_candidates():
    """مۆدێلی کوردیی ڕوون سەرەتا؛ پاشان مۆدێلی config و جێگرەوەکان."""
    models = ["llama-3.3-70b-versatile", config.get("groqModel", GROQ_MODEL), GROQ_MODEL, "openai/gpt-oss-120b"]
    return list(dict.fromkeys(model for model in models if model))

def request_groq_text(messages: list, model_name: str, max_tokens: int = 800,
                      temperature: float = 0.55, json_mode: bool = False):
    """SDK سەرەتا؛ ئەگەر دەستپێنەکەوت، Groq REST API وەک fallback بەکاربهێنە."""
    if not GROQ_API_KEY:
        return None

    request_body = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        request_body["response_format"] = {"type": "json_object"}

    if groq_client:
        try:
            result = groq_client.chat.completions.create(**request_body)
            return result.choices[0].message.content
        except Exception as exc:
            print(f"Groq SDK Notice ({model_name}): {type(exc).__name__}")

    try:
        response = telegram_session.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json=request_body,
            timeout=(15, 45),
        )
        if response.status_code == 200:
            choices = response.json().get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content")
        else:
            print(f"Groq REST Notice ({model_name}): HTTP {response.status_code}")
    except Exception as exc:
        print(f"Groq REST Notice ({model_name}): {type(exc).__name__}")
    return None

print(f"🤖 AI Engine: {'Google Gemini 2.0 Flash' if GEMINI_API_KEY else 'Groq ' + GROQ_MODEL if GROQ_API_KEY else 'None'}")
print(f"🌍 Timezone: Kurdistan (UTC+3)")

STATE_FILE = BASE_DIR / "data" / "state.json"
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

if STATE_FILE.exists():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state_data = json.load(f)
    except Exception:
        state_data = {"warnings": {}, "rules": {}, "groups": [], "last_broadcasts": {}}
else:
    state_data = {"warnings": {}, "rules": {}, "groups": [], "last_broadcasts": {}}

def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed to save state: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
#  سیستەمی ژیریی دەستکردی کوردیی زۆر ڕوخۆش و پڕ لە ئیمۆجی
# ═══════════════════════════════════════════════════════════════════════════════

AI_SYSTEM_PROMPT = """
You are Gardnya (گاردنیا), a warm, clever and fun Kurdish friend in a Telegram group.
Write ONLY in very clear, natural, everyday Sorani Kurdish, like a normal person chatting with friends.
Never sound like a textbook, lecturer, official notice, machine translation, or scientific report unless
the user explicitly asks for a technical or scientific explanation. Answer the real question first.
Use short, smooth sentences and familiar words. When the moment fits, add a light, friendly joke or
playful phrase, but never mock, insult, embarrass, or make fun of the user. Use 1-3 suitable emojis in
ordinary friendly conversation; do not put emojis after every sentence and do not repeat the same emoji.

YOUR CAPABILITIES & FEATURES:
When someone asks what you do, what your features are, or what you know (چ کارێک دەزانیت، تایبەتمەندییەکانت، ئیشت چییە، چیت پێ دەکرێت...):
Proudly and warmly explain your main powers:
1. 🎮 یاری و مەتەڵی بەکۆمەڵ (/game1 تا /game4 - وشە تێکئاڵاوەکان، ڕاست یان هەڵە، ژمارەی نهێنی، و سەدان مەتەڵی کوردی و کۆمیدی بە بێسنووری).
2. 🛡️ پاراستنی گروپ لە لینک، سپام، ڕیکلام، قسەی نەشیاو، و بەکارهێنانی AI Vision بۆ بلۆککردنی ستیکەر و ڤیدیۆی نەشیاو.
3. 🌸 پێشوازی تایبەت لە ئەندامانی نوێ بە وێنەی پڕۆفایلی خۆیان.
4. 🔒 قوفڵکردنی گروپ بۆ کاتی خەو و کردنەوە لە بەیانیاندا (/lock و /unlock).
5. 🕌 بانگی نوێژەکان و پەخشی کاتژمێرە یەکسانەکان.
6. 🎙️ ڕاگەیاندنی دەنگی و تاگکردنی هەمووان (@all).
7. 🤖 وەڵامدانەوەی زیرەکانەی هەموو پرسیارەکان بە کوردییەکی شیرین.

CRITICAL RULES:
1. STRICT BOUNDARIES AGAINST FLIRTING / SEXUALITY / HUGGING / KISSING:
   - You NEVER engage in romantic, sexual, hugging, kissing, or flirtatious talk (باوەش، ماچ، سێکس، خۆشەویستی...).
   - If ANYONE asks for hugs, kisses, love, sexual topics, or flirts with you, FIRMLY AND POLITELY REJECT THEM with dignity:
     Tell them: "شەرم بکە گیان! ئێمە تەنها هاوڕێین، تکایە ڕێز لە سنوورەکان بگرە و باسی ماچ و باوەش و ئەم شتانە مەکە 🌸🚫"
2. Keep ordinary chat answers concise, lively and natural, but give enough detail to be useful.
3. A little friendly humor is welcome when appropriate. Serious, sad, safety, health and emergency
   topics must be answered calmly and respectfully without jokes.
4. Use 1-3 suitable emojis in casual chat, and fewer or none in serious answers.
5. Avoid repeatedly calling people گیانەکەم، قوربانت or گوڵم; sound friendly without overdoing it.
6. Be respectful, practical, accurate, and easy to understand.
"""

WELCOME_MESSAGES = [
    "🌸 سڵاو {name} گیان! زۆر زۆر بەخێر بێیت بۆ گروپەکەمان 🎉\n\nگەرمترین بەخێرهاتنت لێ دەکەین، هیواداریین کاتێکی زۆر خۆش و بەسوود لەگەڵمان بەسەر بەریت! ✨❤️🥰",
    "👑 سڵاو لە {name} خۆشەویست! زۆر بەخێربێیت بۆ نێو خێزانە چاک و ئازیزەکەمان 🌟\n\nگروپ بە هاتنی تۆ گەشاوەتر بوو، بە هیوای کاتی زۆر خۆش و سەرکەوتووانە! 🌺💐💖",
    "✨ سڵاو و دەرەکەت خۆش {name} گیان! بەخێربێیت بەسەر چاوانمان 💐\n\nزۆر دڵخۆشین بە بینینت لە نێوماندا! 🎉🌸🤗"
]

# Telegram هەندێک جار هەمان جۆین بە message و chat_member هەردووکیان دەنێرێت.
# ئەم کۆگایە ڕێگری لە دوو کارتی بەخێرهاتن بۆ هەمان کەس دەکات.
recent_welcome_events = {}
recent_welcome_lock = threading.Lock()

SMART_REPLIES = [
    {
        "patterns": ["ماچ", "ماچم", "ماچت", "ماچێک", "باوەش", "باوەشم", "باوەشت", "باوش", "باوشم", "باوشت", "سێکس", "سێکسی", "خۆشەویستم بە", "خۆشمەوێیت", "خۆشم دەوێیت", "بۆم ڕووت بە", "وەرە باوەشم", "رووت", "sexy", "kiss", "hug"],
        "replies": [
            "شەرم بکە گیان! ئێمە لێرە تەنها وەک هاوڕێین، تکایە ڕێز لە سنوورەکان بگرە و باسی ماچ و باوەش و ئەم شتانە مەکە 🌸🚫",
            "تکایە سنووری خۆت بزانە گوڵم! من تەنها هاوڕێ و خزمەتکاری گروپم، قسەی وا لەگەڵ من ناکرێت 🙅‍♀️✨",
            "ئێمە تەنها هاوڕێی چاتین براکەم! تکایە باسی باوەش و ماچ مەکە و ڕێزی خۆت بپارێزە 🌸✋",
            "کەمێک شەرم بکە ئازیزم! لێرە تەنها ڕێز و برایەتی و هاوڕێیەتی هەیە، قسەی لەم شێوەیە قەدەغەیە ⛔🌸"
        ]
    },
    {
        "patterns": ["سڵاو", "سلاو", "سلام", "هەڵۆ", "hello", "hi", "slaw"],
        "replies": [
            "سڵاو لە تۆی گوڵ و ئازیزیش گیانەکەم! چۆنیت؟ 🌸❤️",
            "سڵاو و ڕێز و گوڵباران بۆ تۆی بەڕێز! بەخێربێیت گیان 😊✨",
            "سڵاو لە چاوە گەشەکانت، هەمیشە بەخێر بێیت! 💖🌺",
            "سڵاو گیان! هیوادارم ڕۆژێکی زۆر خۆشت هەبێت 🌸🥰"
        ]
    },
    {
        "patterns": ["چۆنیت", "چونیت", "چۆنی", "چاکیت", "باشیت", "چ هەواڵ", "choni", "bashit"],
        "replies": [
            "سوپاس بۆ خودا من زۆر باش و دڵخۆشم، تۆ بڵێ چۆنیت گوڵم؟ ✨❤️",
            "زۆر باشم بە بینینی پەیامە جوانەکەت! هەواڵت چۆنە گیان؟ 😊🌸",
            "سوپاس بۆ خوا من زۆر چاکم، هیوادارم تۆش لە لوتکەی باشیدا بیت! 💖💐"
        ]
    },
    {
        "patterns": ["باشم", "سوپاس بۆ خوا", "سوپاس باشم", "bashm", "swpas bashm"],
        "replies": [
            "خوای گەورە هەمیشە دڵت بە خۆشی و بەختەوەری بهێڵێتەوە گوڵم! 🌸❤️",
            "هەمیشە لەشساغ و کەیفساز بیت گیانەکەم! ✨💖",
            "دڵخۆشم کە باشیت ئازیزم، هەمیشە شاد بیت! 🥰💐"
        ]
    },
    {
        "patterns": ["ha?", "ha", "ها؟", "ها"],
        "replies": [
            "گیان شتێکت دەویست گوڵم؟ گوێم لێتە! 🌸😊",
            "بەڵێ گیانەکەم لە خزمەتدام! چۆن یارمەتیت بدەم؟ ✨❤️",
            "فەرموو گوڵم، شتێک بووە؟ 🥰💐"
        ]
    },
    {
        "patterns": ["ch?", "ch", "چی؟", "چی", "چییە", "چی بووە", "chya", "ch buwa"],
        "replies": [
            "هیچ نەبووە گیانەکەم! تەنها لە خزمەتی چاتی ئێوەی گوڵدام 🌸✨",
            "هەموو شتێک بە خێرە گوڵم، فەرموو لە خزمەتدام! 😊💖",
            "تەنها چاودێری ئارامی گروپەکەتان دەکەم گوڵم! 🤖🌸"
        ]
    },
    {
        "patterns": ["واز بێنە", "وازبێنە", "waz bena", "wazbena", "دا واز بێنە"],
        "replies": [
            "بەسەرچاو گیانەکەم! تۆ چۆن پێت خۆشە منیش بێدەنگ دەبم 🌸🤐✨",
            "فەرمانی تۆیە گوڵم، هەر کاتێک پێت خۆش بوو بانگم بکەوە! 😊💖",
            "چاوەکانت ماچ دەکەم، ئاسوودە بە گیان! 🌸🥰"
        ]
    },
    {
        "patterns": ["دەستت خۆش", "دەست خۆش", "دەستت کەڵەک پێ بێت", "dast xosh", "dastxosh"],
        "replies": [
            "عافیەتبیت گیانەکەم! شایەنی هیچی تر نییە 🌸❤️",
            "سەرکەوتوو و تەندروست بیت، دەستی تۆش خۆش بێت براکەم! ✨💖",
            "سەرچاوم گیانی گاردنیا! هەمیشە لە خزمەتتام 🥰💐"
        ]
    },
    {
        "patterns": ["سوپاس", "سوپاست دەکەم", "دەستت خۆش بیت", "spas", "supas"],
        "replies": [
            "شایەنی نییە گیانەکەم! هەموو کات لە خزمەتتدام ❤️🌸",
            "سوپاس بۆ تۆش بۆ ئەو دڵە پاک و جوانەت! ✨💖",
            "سەرچاوم بەڕێزم! هەمیشە شاد بیت 🤗💐"
        ]
    },
    {
        "patterns": ["شەوشاد", "شەوتان شاد", "شەو باش", "shaw shad", "shawbash"],
        "replies": [
            "شەوت پڕ لە ئارامی و خەوی خۆش گوڵم! خودات لەگەڵ 🌙✨😴",
            "شەوێکی پڕ لە بەرەکەت و پشوودان بۆ تۆی ئازیز! 🌸🌌💖"
        ]
    },
    {
        "patterns": ["بەیانیت باش", "بەیانی باش", "bayani bash"],
        "replies": [
            "بەیانیت گوڵباران و ڕۆژت پڕ لە کامەرانی و وزەی پۆزەتیڤ! ☀️🌸💐",
            "بەیانیت باش گوڵم! هیوای ڕۆژێکی سەرکەوتووانە بۆ تۆ 🌻✨❤️"
        ]
    },
    {
        "patterns": ["چی دەکەی", "chi akay", "سەرقاڵی چیت"],
        "replies": [
            "خەریکی چاودێری و پاراستنی ئەم گروپە خۆشەویستەم و گوێگرتن لە پەیامەکانتان! 🤖🌸✨",
            "لە خزمەتی ئێوەی گوڵدام و چاوەڕێی فەرمانی ئێوەم! 🥰💖"
        ]
    },
    {
        "patterns": ["ناوی تۆ چییە", "ناوت چییە", "تۆ کێیت", "کێیت", "nawt chya"],
        "replies": [
            "من ناوم گاردنیایە! بوتی پاراستنی گروپ و هاوڕێی زیرەک و دڵسۆزتان 🤖🌸❤️",
            "من گاردنیام! بوتی ئاسایش و ژیریی دەستکردی کوردی، خزمەتکاری ئێوەی گوڵ 🌺✨"
        ]
    },
    {
        "patterns": ["گاردنیا", "gardnya", "بووت", "بوت"],
        "replies": [
            "گیانی گاردنیا، فەرموو سەرچاوم لە خزمەتتام! 🌸🥰",
            "بەڵێ گوڵم! چۆن دەتوانم یارمەتیت بدەم ئەمڕۆ؟ ✨❤️",
            "گیانەکەم فەرموو، بە دڵ گوێم لێتە! 💖💐"
        ]
    },
    {
        "patterns": [
            "چ کارێک", "چیت پێ ئەکرێت", "چیت پێ دەکرێت", "چیت پێ دێت", "تایبەتمەندی",
            "فەرمانەکانت", "چی ئەزانیت", "چی دەزانیت", "ئیشت چییە", "کاری تۆ چییە",
            "باسی خۆت بکە", "دەتوانیت چی بکەیت", "تواناکانت", "خزمەتگوزاری",
            "چیت لە دەست دێت", "چیت پێ ئەکرێ", "چ کاریک", "chyt pe akret", "isht chya", "kary to chya"
        ],
        "replies": [
            "🌸 <b>سڵاو گوڵم! من بوتی گاردنیام 🤖❤️</b>\n\nئەمانە بەشێک لە گرنگترین توانا و تایبەتمەندییەکانمن:\n\n🎮 <b>١. یاری و مەتەڵی بەکۆمەڵ:</b>\n• <code>/game1</code> - یاریی وشە تێکئاڵاوەکان 🧩\n• <code>/game2</code> - یاریی ڕاستە یان هەڵەیە ⚡\n• <code>/game3</code> - دۆزینەوەی ژمارەی نهێنی (١-١٠٠) 🎯\n• <code>/game4</code> یان <code>/quiz</code> - زیاتر لە ١٠٠٠ مەتەڵی کوردی و کۆمیدی بێ کۆتایی ❓😂\n\n🛡️ <b>٢. پاراستنی ئاسایشی گروپ:</b>\n• سڕینەوەی خۆکاری لینک، سپام، و ڕیکلام 🔗\n• فلتەرکردنی قسەی نەشیاو و جنێو 🤬\n• پشکنینی وێنە، ڤیدیۆ و ستیکەری سێکسی بە ژیریی دەستکرد (AI Vision) 🔞\n• دەرکردنی بۆتە بێ مۆڵەتەکان 🚫\n\n👑 <b>٣. بەخێرهاتن و بەڕێوەبردن:</b>\n• پێشوازی لە ئەندامانی نوێ بە وێنەی پڕۆفایلی خۆیان و دەقی کەشخە 🖼️🌸\n• قوفڵکردنی گروپ بۆ کاتی خەو (<code>/lock</code>) و کردنەوە لە بەیانیاندا (<code>/unlock</code>) 🔒\n• پەخشی کاتی بانگەکان و کاتژمێرە یەکسانەکان 🕌⏰\n• تاگکردنی هەموو ئەندامان ٥ بە ٥ بە <code>@all</code> 📢\n\n🤖 <b>٤. ژیریی دەستکرد (AI):</b>\n• وەڵامدانەوەی زیرەکانەی هەموو پرسیار و قسەکانتان بە کوردییەکی شیرین و ڕوخۆش! 💬✨🥰"
        ]
    }
]

import html

# ═══════════════════════════════════════════════════════════════════════════════
#  کاتژمێرە یەکسانەکان بە سیستەمی ۱۲ کاتژمێری و قۆناغەکانی ڕۆژ (Mirror Hours)
# ═══════════════════════════════════════════════════════════════════════════════

MIRROR_HOURS_CONFIG = {
    # 🌙 خولی شەو و بەیانی (12 کاتژمێر - یەکجار پەخش دەکرێت)
    "00:12": {"time_label": "12:12 (شەو 🌙)", "quote": "دەستپێکی ڕۆژێکی نوێ و پڕ لە هیوا، شەوتان ئارام و پڕ بەرەکەت بێت 🌙✨🌸"},
    "01:01": {"time_label": "01:01 (شەو 🌙)", "quote": "هەمیشە هیوای باشت هەبێت، شەوێکی پڕ لە ئارامی بۆ هەمووتان 🌸❤️✨"},
    "02:02": {"time_label": "02:02 (شەو 🌙)", "quote": "دڵە پاکەکان هەمیشە ئاسوودەن، شەوتان شاد و خەوتان شیرین ✨😴💖"},
    "03:03": {"time_label": "03:03 (شەو 🌙)", "quote": "بە هیوای کاتێکی ئارام و دەستپێکێکی پڕ لە خێر و سەرکەوتن 🌟🕊️🌸"},
    "04:04": {"time_label": "04:04 (بەیانی ☀️)", "quote": "بەیانیتان باش و ڕۆژتان پڕ لە بەرەکەت و خێر بێت ☀️💐✨"},
    "05:05": {"time_label": "05:05 (بەیانی ☀️)", "quote": "هەمیشە خەندە بکە، بەیانیت باش و ڕۆژت پڕ لە کامەرانی 🌸✨🥰"},
    "06:06": {"time_label": "06:06 (بەیانی ☀️)", "quote": "ڕۆژێکی نوێ و دەرفەتێکی نوێ، بە هیوای سەرکەوتن بۆ هەمووان 🌻💖☀️"},
    "07:07": {"time_label": "07:07 (بەیانی ☀️)", "quote": "بەیانیتان گوڵڕێژ، هیوای ڕۆژێکی چالاک و بەرهەمدار 🌺☕✨"},
    "08:08": {"time_label": "08:08 (بەیانی ☀️)", "quote": "هەرگیز کۆڵ مەدە لە ئامانجەکانت، ڕۆژێکی پڕ سەرکەوتن 🚀🌟💪"},
    "09:09": {"time_label": "09:09 (بەیانی ☀️)", "quote": "هەمیشە میهرەبان و گەشاوە بن، ڕۆژتان پڕ لە شادی 🌸👑💖"},
    "10:10": {"time_label": "10:10 (بەیانی ☀️)", "quote": "دڵتان پڕ بێت لە وزەی ئەرێنی و خۆشەویستی، کاتێکی بەجۆش 💖☕✨"},
    "11:11": {"time_label": "11:11 (بەیانی 🌟)", "quote": "کاتژمێری ئاواتەکان! بە هیوای هاتنەدی هەموو خەونەکانتان ✨🌈🌸"},
    "12:12": {"time_label": "12:12 (نیوەڕۆ 🌞)", "quote": "نیوەڕۆتان باش! ڕۆژێکی پڕ لە خێر و لەشساغی بۆ هەمووان 🌞🍀❤️"},

    # 🌞 خولی پاشنیوەڕۆ، عەسر، ئێوارە و شەو (12 کاتژمێر - یەکجار پەخش دەکرێت)
    "13:01": {"time_label": "01:01 (نیوەڕۆ 🌞)", "quote": "هەمیشە دەمتان بە خەندە و دڵتان ئارام بێت، نیوەڕۆتان باش 😊🌸💐"},
    "14:02": {"time_label": "02:02 (نیوەڕۆ 🌞)", "quote": "بەهێز بە و بڕوات بە توانای خۆت هەبێت بەرەو سەرکەوتن 💪✨🔥"},
    "15:03": {"time_label": "03:03 (عەسر 🌤️)", "quote": "پڕ بن لە ئاشتی و میهرەبانی، کاتێکی ئارام بۆ هەمووتان 🕊️❤️🌸"},
    "16:04": {"time_label": "04:04 (عەسر 🌤️)", "quote": "عەسرێکی دڵڕفێن و ساتێکی خۆش لەگەڵ ئازیزانتان ☕🍂✨"},
    "17:05": {"time_label": "05:05 (عەسر 🌤️)", "quote": "ئێوارەیەکی پڕ لە ئارامی و ساتەوەختی شیرین بۆ هەمووان 🌇✨💐"},
    "19:07": {"time_label": "07:07 (ئێوارە 🌇)", "quote": "سوپاسگوزاری خودا بە بۆ هەموو نیعمەتەکان، شەوتان شاد 🌙🤲❤️"},
    "20:08": {"time_label": "08:08 (شەو 🌙)", "quote": "کاتێکی خۆش و بەجۆش لەگەڵ هاوڕێ و خێزانە ئازیزەکانتان 🌟🎉🥰"},
    "21:09": {"time_label": "09:09 (شەو 🌙)", "quote": "مێشکت ئارام بکەرەوە، شەوتان شاد و چاتتان پڕ لە گەرمی 🫖🌙🌸"},
    "22:10": {"time_label": "10:10 (شەو 🌙)", "quote": "کاتژمێری ئارامی! هیوای خەوێکی پڕ لە ئاسوودەیی بۆ هەمووان ✨😴💖"},
    "23:11": {"time_label": "11:11 (شەو 🌙)", "quote": "بێدەنگیی شەو باشترین دەرفەتە بۆ نزا، شەوتان پڕ لە بەرەکەت 🤲🌌🌸"}
}

# ═══════════════════════════════════════════════════════════════════════════════
#  کاتی بانگەکان و زیکر (Prayer Times & Azan Schedule in Kurdistan)
# ═══════════════════════════════════════════════════════════════════════════════

PRAYER_SCHEDULE = {
    "04:30": {
        "name": "بانگی بەیانی (الفجر)",
        "zikr": "«اللَّهُمَّ أَنْتَ رَبِّي لَا إِلَهَ إِلَّا أَنْتَ، خَلَقْتَنِي وَأَنَا عَبْدُكَ، وَأَنَا عَلَى عَهْدِكَ وَوَعْدِكَ مَا اسْتَطَعْتُ» 🤲✨"
    },
    "12:20": {
        "name": "بانگی نیوەڕۆ (الظهر)",
        "zikr": "«سُبْحَانَ اللَّهِ وَبِحَمْدِهِ، سُبْحَانَ اللَّهِ الْعَظِيمِ» - خوایە نوێژ و کردەوە چاکەکانمان لێ قبوڵ بکەیت 🌸🕋"
    },
    "16:05": {
        "name": "بانگی عەسر (العصر)",
        "zikr": "«لَا إِلَهَ إِلَّا اللَّهُ وَحْدَهُ لَا شَرِيكَ لَهُ، لَهُ الْمُلْكُ وَلَهُ الْحَمْدُ، وَهُوَ عَلَى كُلِّ شَيْءٍ قَدِيرٌ» 📿✨"
    },
    "19:10": {
        "name": "بانگی مەغریب (المغرب)",
        "zikr": "«اللَّهُمَّ إِنِّي أَسْأَلُكَ الْعَفْوَ وَالْعَافِيَةَ فِي الدُّنْيَا وَالْآخِرَةِ» - خودا دوعاکانتان گیرابکات 🤲🌇"
    },
    "20:45": {
        "name": "بانگی عیشا (العشاء)",
        "zikr": "«اللَّهُمَّ صَلِّ عَلَىٰ مُحَمَّدٍ وَعَلَىٰ آلِ مُحَمَّدٍ» - خوایە بە خێر و ئارامی کۆتایی بەم ڕۆژەمان بهێنیت 🌙✨"
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
#  فیلتەری جنێو، قسەی ناشرین و سپام
# ═══════════════════════════════════════════════════════════════════════════════

BAD_WORDS_LIST = [
    'قن', 'قنت', 'قنم', 'قنی', 'قوز', 'قۆز', 'قوزت', 'قوزم', 'قوزی',
    'کیر', 'کێرم', 'کیرم', 'کێر', 'کێری', 'کێرت', 'کیرت',
    'گواو', 'گوخۆر', 'گوو', 'گو', 'گوت', 'گووم',
    'حیز', 'سۆزانی', 'سێکس', 'پۆرن', 'قەحبە', 'گەواد', 'پینتی', 'بێنامووس', 'نامووس',
    'ئەتگێم', 'ئەگێم', 'بگێم', 'بگێرم',
    'fuck', r'f\s*u\s*c\s*k', 'shit', 'bitch', 'asshole', 'dick', 'pussy',
    'bastard', 'whore', 'slut', 'nigger', 'faggot', 'cock', 'cunt',
    'motherf', 'stfu', 'porn', 'xxx', 'nude', 'naked',
    'boobs', 'tits', 'penis', 'vagina', 'orgasm', 'hentai'
]

BAD_PHRASES_LIST = [
    r'لە\s*دایکت', r'دایکت\s*بگێم', r'دایکت\s*گێم', r'دایکت\s*بێ', r'دایکت\s*بم',
    r'لە\s*خوشکت', r'خوشکت\s*بگێم', r'خوشکت\s*گێم', r'خوشکت\s*بێ', r'خوشکت\s*بم',
    r'لە\s*عەرزت', r'لە\s*قەبرت', r'داپیرەت\s*بم'
]

# ═══════════════════════════════════════════════════════════════════════════════
#  فەنکشنەکانی پەیوەندی بە Telegram API
# ═══════════════════════════════════════════════════════════════════════════════

def tg_call(method: str, payload: dict = None):
    try:
        # getUpdates خۆی تا 30 چرکە long-polling دەکات؛ read timeout دەبێت کەمێک زیاتر بێت.
        timeout = (15, 40) if method == "getUpdates" else (15, 30)
        r = telegram_session.post(f"{API_BASE}/{method}", json=payload or {}, timeout=timeout)
        if r.status_code >= 500:
            raise requests.HTTPError(f"Telegram HTTP {r.status_code}")
        result = r.json()
        telegram_error_state["count"] = 0
        return result
    except Exception as e:
        telegram_error_state["count"] += 1
        now = time.time()
        # token هیچ کات لە log ـدا پیشان مەدە؛ هەڵە دووبارەکانیش هەر 30 چرکە جارێک بنووسە.
        if now - telegram_error_state["last_log"] >= 30:
            safe_error = str(e).replace(BOT_TOKEN, "<BOT_TOKEN_REDACTED>") if BOT_TOKEN else str(e)
            print(f"Telegram connection problem ({method}, attempt {telegram_error_state['count']}): {safe_error}")
            telegram_error_state["last_log"] = now
        return None

BOT_ID = 0

def refresh_bot_identity() -> bool:
    """دوای 503 ـی دەستپێکیش ناسنامەی بۆت خۆکار دووبارە وەربگرە."""
    global BOT_ID
    me_data = tg_call("getMe")
    if me_data and me_data.get("ok"):
        BOT_ID = me_data["result"]["id"]
        print(f"Bot authenticated as: @{me_data['result'].get('username', 'bot')} (ID: {BOT_ID})")
        return True
    return False

refresh_bot_identity()

def send_message(chat_id: int, text: str, reply_to: int = 0, thread_id: int = 0, parse_mode: str = "HTML", reply_markup: dict = None):
    body = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if parse_mode:
        body["parse_mode"] = parse_mode
    if reply_to > 0:
        body["reply_to_message_id"] = reply_to
        body["allow_sending_without_reply"] = True
    if thread_id > 0:
        body["message_thread_id"] = thread_id
    if reply_markup:
        body["reply_markup"] = reply_markup
    res = tg_call("sendMessage", body)
    if not res or not res.get("ok"):
        # Fallback without parse_mode if HTML entity formatting fails
        body.pop("parse_mode", None)
        res = tg_call("sendMessage", body)
    return res

def get_chat_latest_photo_bytes(chat_id: int, chat_info: dict = None):
    """دابەزاندنی نوێترین وێنەی ڕاستەقینەی سەر گروپ لە تێلێگرام لە کاتی گۆڕین یان نوێکردنەوە"""
    try:
        if not chat_info or not chat_info.get("photo"):
            chat_res = tg_call("getChat", {"chat_id": chat_id})
            chat_info = chat_res.get("result", {}) if chat_res else {}
            
        photo_info = chat_info.get("photo", {}) if chat_info else {}
        photo_id = photo_info.get("big_file_id") or photo_info.get("small_file_id")
        
        if photo_id:
            photo_bytes, _ = download_telegram_file(photo_id)
            if photo_bytes and len(photo_bytes) > 100:
                return photo_bytes
    except Exception:
        print(f"Error fetching group live photo bytes ({chat_id})")
    return None

def get_chat_photo_bytes(chat_id: int):
    return get_chat_latest_photo_bytes(chat_id)

def get_channel_live_photo_bytes(channel_identifier: str):
    """دابەزاندنی ڕاستەوخۆ و نوێی وێنەی پڕۆفایلی چەناڵ بە شێوەی باێت لە سێرڤەری تێلێگرام"""
    if not channel_identifier:
        return None
    try:
        clean_ch = channel_identifier.strip()
        if not clean_ch.startswith("@") and not clean_ch.startswith("-100"):
            clean_ch = f"@{clean_ch}"
        
        chat_res = tg_call("getChat", {"chat_id": clean_ch})
        if chat_res and chat_res.get("ok"):
            photo_info = chat_res.get("result", {}).get("photo", {})
            photo_id = photo_info.get("big_file_id") or photo_info.get("small_file_id")
            if photo_id:
                photo_bytes, _ = download_telegram_file(photo_id)
                if photo_bytes and len(photo_bytes) > 100:
                    return photo_bytes
    except Exception:
        print(f"Error fetching channel live photo ({channel_identifier})")
    return None

def is_user_subscribed_to_channel(channel_identifier: str, user_id: int) -> bool:
    """پشکنینی ئەوەی ئایا بەکارهێنەر جۆینی چەناڵەکەی کردووە یان نا"""
    if not channel_identifier or not user_id:
        return True
    try:
        clean_ch = channel_identifier.strip()
        if not clean_ch.startswith("@") and not clean_ch.startswith("-100"):
            clean_ch = f"@{clean_ch}"
            
        res = tg_call("getChatMember", {"chat_id": clean_ch, "user_id": user_id})
        if res and res.get("ok"):
            status = res.get("result", {}).get("status", "")
            if status in ["member", "administrator", "creator", "restricted"]:
                return True
            else:
                return False
        else:
            print(f"Channel sub check error for {user_id} in {clean_ch}: {res}")
            return False
    except Exception as e:
        print(f"is_user_subscribed_to_channel error: {e}")
        return False

# کۆگای کاتی ڕێگری لە سپامکردنی کارتی جۆین
force_join_cooldowns = {}
# کۆگای ئایدی پەیامی کارتی جۆینی هەر بەکارهێنەرێک لە هەر گروپ بۆ سڕینەوە کاتی جۆینکردن
force_join_card_msgs = state_data.setdefault("force_join_card_msgs", {})

def delete_force_join_card(chat_id: int, user_id: int) -> bool:
    """سڕینەوەی کارتی جۆینی بەکارهێنەر دوای ئەوەی جۆینی چەناڵەکە دەکات."""
    cd_key = f"{chat_id}_{user_id}"
    card_mid = force_join_card_msgs.get(cd_key)
    if not card_mid:
        return False

    deleted = delete_message(chat_id, card_mid)
    if deleted and deleted.get("ok"):
        force_join_card_msgs.pop(cd_key, None)
        force_join_cooldowns.pop(cd_key, None)
        save_state()
        print(f"✅ Force-Join: Deleted completed join card for user {user_id} in chat {chat_id}")
        return True
    return False

def channel_update_matches_identifier(chat: dict, channel_identifier: str) -> bool:
    """بەراوردکردنی چەناڵی update لەگەڵ چەناڵی دانراوی گروپ."""
    configured = str(channel_identifier or "").strip().lower()
    if not configured:
        return False
    if configured == str(chat.get("id", "")):
        return True
    username = str(chat.get("username", "")).strip().lower().lstrip("@")
    return bool(username and configured.lstrip("@") == username)

def send_force_join_card(chat_id: int, user_id: int, display_name: str, channel_identifier: str, thread_id: int = 0):
    """دروستکردن و ناردنی کارتی شیک و تایبەتی بۆت بۆ ئیجباری جۆینکردن بە تاگکردنی بەکارهێنەر"""
    clean_ch = channel_identifier.strip().lstrip("@")
    channel_link = f"https://t.me/{clean_ch}"
    group_link = "https://t.me/pat_u_mat_gruop"
    
    # وەرگرتنی ناوی فەرمیی چەناڵ لە تێلێگرام
    ch_res = tg_call("getChat", {"chat_id": f"@{clean_ch}"})
    ch_title = ch_res.get("result", {}).get("title") if ch_res else ""
    if not ch_title:
        ch_title = f"@{clean_ch}"
    ch_title_escaped = html.escape(ch_title)
    
    # تاگکردنی ڕاستەوخۆ و کلیکداری بەکارهێنەر (Clickable User Mention Link)
    user_mention = f'<a href="tg://user?id={user_id}">{html.escape(display_name)}</a>'
    # لینکی کلیکداری چەناڵ بۆ ئەوەی ڕاستەوخۆ چەناڵەکە بکاتەوە
    channel_mention = f'<a href="{channel_link}">@{clean_ch}</a>'
    
    caption = (
        f"👑 <b>ئاگاداری بۆ بەڕێز:</b> {user_mention} ✨\n"
        f"⋆┈┈┈┈┈┈┈┈┈⋆\n"
        f"🔒 <b>بۆ چاتکردن، سەرەتا پێویستە جۆینی کەناڵەکەمان بکەیت:</b>\n\n"
        f"📢 <b>کەناڵ:</b> <b>{ch_title_escaped}</b>\n"
        f"🏷️ <b>یوزەر:</b> {channel_mention}\n"
        f"⋆┈┈┈┈┈┈┈┈┈⋆\n"
        f"⚠️ <i>تا جۆین نەکەیت ناتوانیت پەیام بنێریت و چاتەکانت دەسڕدرێنەوە.</i>\n\n"
        f"🌸 <b>پاش جۆینکردن، دەتوانیت بە ئازادی لەگەڵمان بەشدار بیت</b> 🥰"
    )
    
    markup = {
        "inline_keyboard": [
            [
                {"text": "ئێرە دابگرە بۆ جۆین کردن ✅", "url": channel_link}
            ],
            [
                {"text": "👑 ɢʀᴏᴜᴘ ᴘᴀᴛ & ᴍᴀᴛ 👑", "url": group_link}
            ]
        ]
    }

    # سڕینەوەی کارتی کۆنی جۆین ئەگەر هەبێت
    cd_key = f"{chat_id}_{user_id}"
    old_card_mid = force_join_card_msgs.get(cd_key)
    if old_card_mid:
        try:
            old_deleted = delete_message(chat_id, old_card_mid)
            if old_deleted and old_deleted.get("ok"):
                force_join_card_msgs.pop(cd_key, None)
                save_state()
        except Exception:
            pass

    # ١. دابەزاندنی نوێترین وێنەی سەر پڕۆفایلی ئەو گروپەی لێی بەکاردەهێنرێت
    sent_res = None
    group_photo_bytes = get_chat_latest_photo_bytes(chat_id)
    if group_photo_bytes:
        sent_res = send_photo(chat_id, group_photo_bytes, caption, 0, thread_id, reply_markup=markup)
    else:
        # ۲. ئەگەر گروپەکە وێنەی نەبوو، وێنەی چەناڵەکە دابنێ
        ch_photo_bytes = get_channel_live_photo_bytes(channel_identifier)
        if ch_photo_bytes:
            sent_res = send_photo(chat_id, ch_photo_bytes, caption, 0, thread_id, reply_markup=markup)
        else:
            sent_res = send_message(chat_id, caption, 0, thread_id, reply_markup=markup)

    # تۆمارکردنی ئایدی پەیامی کارتی جۆین بۆ سڕینەوەی کاتی جۆینکردن
    if sent_res and sent_res.get("ok"):
        card_mid = sent_res.get("result", {}).get("message_id")
        if card_mid:
            force_join_card_msgs[cd_key] = card_mid
            save_state()

def send_photo(chat_id: int, photo_source, caption: str, reply_to: int = 0, thread_id: int = 0, reply_markup: dict = None):
    try:
        data = {
            "chat_id": str(chat_id),
            "caption": caption,
            "parse_mode": "HTML"
        }
        if reply_to > 0:
            data["reply_to_message_id"] = str(reply_to)
            data["allow_sending_without_reply"] = "true"
        if thread_id > 0:
            data["message_thread_id"] = str(thread_id)
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)

        photo_bytes = None
        if isinstance(photo_source, bytes):
            photo_bytes = photo_source
        elif isinstance(photo_source, str) and os.path.exists(photo_source):
            with open(photo_source, "rb") as f:
                photo_bytes = f.read()
        else:
            return send_message(chat_id, caption, reply_to, thread_id, reply_markup=reply_markup)

        if not photo_bytes:
            return send_message(chat_id, caption, reply_to, thread_id, reply_markup=reply_markup)

        def post_photo_payload(current_data):
            response = telegram_session.post(
                f"{API_BASE}/sendPhoto",
                data=current_data,
                files={"photo": ("photo.jpg", photo_bytes, "image/jpeg")},
                timeout=(15, 40),
            )
            return response.json()

        res = post_photo_payload(data)
        if not res.get("ok"):
            # هەڵەی HTML نابێت ببێتە هۆی نەهاتنی کارتەکە.
            data.pop("parse_mode", None)
            res = post_photo_payload(data)
        if res.get("ok"):
            return res
        return send_message(chat_id, caption, reply_to, thread_id, reply_markup=reply_markup)
    except Exception:
        print("sendPhoto Error: Telegram photo service is temporarily unavailable")
        return send_message(chat_id, caption, reply_to, thread_id, reply_markup=reply_markup)

def delete_message(chat_id: int, message_id: int):
    return tg_call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

def get_display_name(user_obj: dict) -> str:
    if not user_obj:
        return "ئازیز"
    if user_obj.get("title"):
        return user_obj["title"]
    if user_obj.get("first_name"):
        return user_obj["first_name"]
    if user_obj.get("username"):
        return f"@{user_obj['username']}"
    return str(user_obj.get("id", "ئازیز"))

def is_admin(chat_id: int, user_id: int) -> bool:
    if user_id == chat_id or user_id == 0:
        return True
    res = tg_call("getChatMember", {"chat_id": chat_id, "user_id": user_id})
    if res and res.get("ok"):
        status = res["result"]["status"]
        return status in ["creator", "administrator"]
    return False

def is_message_from_admin(chat_id: int, user_id: int, msg: dict) -> bool:
    """ناسینەوە و پاراستنی پەیامی ئەدمین، ئۆنەر، یان پەیامی نێردراو بە ناوی چاتێک."""
    # Telegram ناسنامەی کەسی ئەدمین نادات کاتێک بە ناوی گروپ یان چەناڵ پەیام دەنێرێت.
    # بوونی sender_chat نیشانەی ئەو جۆرە پەیامەیە و نابێت پشکنینی سڕینەوەیی لەسەری جێبەجێ بکرێت.
    sender_chat = msg.get("sender_chat") or {}
    if sender_chat.get("id"):
        return True
    return is_admin(chat_id, user_id)

def add_user_warning(chat_id: int, user_id: int) -> int:
    c_key = str(chat_id)
    u_key = str(user_id)
    if "warnings" not in state_data:
        state_data["warnings"] = {}
    if c_key not in state_data["warnings"]:
        state_data["warnings"][c_key] = {}
    current = state_data["warnings"][c_key].get(u_key, 0) + 1
    state_data["warnings"][c_key][u_key] = current
    save_state()
    return current

def reset_user_warnings(chat_id: int, user_id: int):
    c_key = str(chat_id)
    u_key = str(user_id)
    if "warnings" in state_data and c_key in state_data["warnings"]:
        if u_key in state_data["warnings"][c_key]:
            del state_data["warnings"][c_key][u_key]
            save_state()

def set_user_mute(chat_id: int, user_id: int, minutes: int = 60):
    until = int(time.time()) + (minutes * 60)
    return tg_call("restrictChatMember", {
        "chat_id": chat_id,
        "user_id": user_id,
        "until_date": until,
        "permissions": {
            "can_send_messages": False,
            "can_send_media_messages": False,
            "can_send_other_messages": False,
            "can_add_web_page_previews": False
        }
    })

def unmute_user(chat_id: int, user_id: int):
    return tg_call("restrictChatMember", {
        "chat_id": chat_id,
        "user_id": user_id,
        "permissions": {
            "can_send_messages": True,
            "can_send_media_messages": True,
            "can_send_other_messages": True,
            "can_add_web_page_previews": True
        }
    })

def ban_user(chat_id: int, user_id: int):
    return tg_call("banChatMember", {"chat_id": chat_id, "user_id": user_id})

def unban_user(chat_id: int, user_id: int):
    return tg_call("unbanChatMember", {"chat_id": chat_id, "user_id": user_id, "only_if_banned": True})

def set_chat_locked(chat_id: int, locked: bool) -> bool:
    """قوفڵکردن یان کردنەوەی گروپ بۆ کاتی خەو"""
    perms = {
        "can_send_messages": not locked,
        "can_send_media_messages": not locked,
        "can_send_polls": not locked,
        "can_send_other_messages": not locked,
        "can_add_web_page_previews": not locked,
        "can_change_info": False,
        "can_invite_users": not locked,
        "can_pin_messages": False
    }
    res = tg_call("setChatPermissions", {"chat_id": chat_id, "permissions": perms})
    return bool(res and res.get("ok"))

def purge_chat_messages(chat_id: int, start_msg_id: int, count: int = 20):
    """پاککردنەوەی پەیامەکان بە کۆمەڵ"""
    count = min(max(count, 1), 100)
    for mid in range(start_msg_id, max(start_msg_id - count - 5, 0), -1):
        try:
            delete_message(chat_id, mid)
        except Exception:
            pass

def add_user_quiz_point(chat_id: int, user_id: int, user_name: str = "") -> int:
    c_key = str(chat_id)
    u_key = str(user_id)
    if "quiz_scores" not in state_data:
        state_data["quiz_scores"] = {}
    if c_key not in state_data["quiz_scores"]:
        state_data["quiz_scores"][c_key] = {}
    current = state_data["quiz_scores"][c_key].get(u_key, 0) + 1
    state_data["quiz_scores"][c_key][u_key] = current

    if "game_session_scores" not in state_data:
        state_data["game_session_scores"] = {}
    if c_key not in state_data["game_session_scores"]:
        state_data["game_session_scores"][c_key] = {}
    session_current = state_data["game_session_scores"][c_key].get(u_key, 0) + 1
    state_data["game_session_scores"][c_key][u_key] = session_current
    
    if "user_names" not in state_data:
        state_data["user_names"] = {}
    if user_name:
        state_data["user_names"][u_key] = user_name
        
    save_state()
    return current

def record_game_participant(chat_id: int, user_id: int, user_name: str = ""):
    """تۆمارکردنی هەموو بەشداربووان، تەنانەت ئەگەر وەڵامیان هەڵە بێت."""
    c_key = str(chat_id)
    if "game_session_players" not in state_data:
        state_data["game_session_players"] = {}
    players = state_data["game_session_players"].setdefault(c_key, [])
    if str(user_id) not in players:
        players.append(str(user_id))
    if user_name:
        state_data.setdefault("user_names", {})[str(user_id)] = user_name
    save_state()

def build_current_game_scoreboard(chat_id: int) -> str:
    """ڕیزبەندیی تەنها ئەو کەسانەی لە خولی یاریی ئێستا بەشداربوون."""
    c_key = str(chat_id)
    players = state_data.get("game_session_players", {}).get(c_key, [])
    scores = state_data.get("game_session_scores", {}).get(c_key, {})
    if not players:
        return "🏁 <b>یارییەکە تەواو بوو!</b>\n\nهیچ بەشداربووێک لەم خولەدا تۆمار نەکرا 🌸"

    ranked = sorted(players, key=lambda uid: scores.get(str(uid), 0), reverse=True)
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    names = state_data.get("user_names", {})
    board = "🏁 <b>یارییەکە تەواو بوو — ڕیزبەندیی بەشداربووان:</b>\n\n"
    for index, uid in enumerate(ranked[:10]):
        name = html.escape(names.get(str(uid), f"بەشداربوو {index + 1}"))
        medal = medals[index] if index < len(medals) else f"#{index + 1}"
        board += f"{medal} <b>{name}</b>: <b>{scores.get(str(uid), 0)} خاڵ</b>\n"
    return board

# ═══════════════════════════════════════════════════════════════════════════════
#  بانکی مەتەڵ و یارییە بەکۆمەڵە کوردییەکان (Kurdish Quizzes & Games)
# ═══════════════════════════════════════════════════════════════════════════════

KURDISH_UNSCRAMBLE_WORDS = [
    {"word": "سلێمانی", "scrambled": "ی • ل • م • ا • ن • ی • س", "category": "شارێکی دڵڕفێنی کوردستان 🏙️", "answers": ["سلێمانی", "سلیمانی", "slemani"]},
    {"word": "هەولێر", "scrambled": "ل • ێ • ر • هـ • و • ە", "category": "پایتەختی دێرینی کوردستان 🏰", "answers": ["هەولێر", "ھەولێر", "hawler", "erbil"]},
    {"word": "دهۆک", "scrambled": "ک • هـ • د • ۆ", "category": "بووکی باکووری کوردستان 🌄", "answers": ["دهۆک", "دهوك", "dhok", "duhok"]},
    {"word": "کەرکووک", "scrambled": "و • ک • ر • ک • ک • و", "category": "قودس و شاری نەوتی کوردستان 🛢️", "answers": ["کەرکووک", "کەرکوک", "كركوك", "karkuk", "kirkuk"]},
    {"word": "هەڵەبجە", "scrambled": "ج • ب • هـ • ل • ە • ە", "category": "شاری شەهیدان و گوڵەبەیبوون 🌸", "answers": ["هەڵەبجە", "ھەڵەبجە", "هلەبجە", "halabja"]},
    {"word": "پەپوولە", "scrambled": "و • پ • ل • ە • پ • ە", "category": "گیاندار و مێروویەکی باڵداری جوان 🦋", "answers": ["پەپوولە", "پەپولە", "papula"]},
    {"word": "شەمشەمەکوێرە", "scrambled": "ک • و • ێ • ر • ە • ش • ە • م • ش • ە • م • ە", "category": "گیاندارێکی شیردەری شەوانە 🦇", "answers": ["شەمشەمەکوێرە", "شەمشەمە کوێرە", "shamshamakwera"]},
    {"word": "دۆڵمە", "scrambled": "ل • م • د • ە • ۆ", "category": "خۆشترین خواردنی کوردی 🍲", "answers": ["دۆڵمە", "دولمە", "دولمه", "dolma"]},
    {"word": "هەنار", "scrambled": "ر • ن • هـ • ا", "category": "میوەیەکی بەناوبانگی هەڵەبجە 🍎", "answers": ["هەنار", "ھەنار", "hanar"]},
    {"word": "قەڵای دمدم", "scrambled": "د • م • د • م • ق • ە • ڵ • ا • ی", "category": "شاکار و داستانێکی مێژوویی کورد 🏰", "answers": ["قەڵای دمدم", "قلای دمدم", "دمدم"]},
    {"word": "هەڵگورد", "scrambled": "ر • د • هـ • ڵ • گ • و", "category": "بەرزترین لوتکەی شاخی باشووری کوردستان 🏔️", "answers": ["هەڵگورد", "ھەڵگورد", "helgurd", "halgurd"]},
    {"word": "کەباب", "scrambled": "ب • ا • ک • ب • ە", "category": "خواردنێکی بەتامی سەر خەڵووز 🍢", "answers": ["کەباب", "کباب", "kabab"]},
    {"word": "نەورۆز", "scrambled": "ر • ۆ • ن • ە • و • ز", "category": "جەژنی نەتەوەیی و سەری ساڵی کوردی 🔥", "answers": ["نەورۆز", "نوروز", "nawroz"]},
    {"word": "قەرەداغ", "scrambled": "غ • د • ا • ق • ە • ر • ە", "category": "ناوچەیەکی سەرسەوزی سروشتی لە کوردستان 🌲", "answers": ["قەرەداغ", "قرەداغ", "qaradagh"]},
    {"word": "زێراب", "scrambled": "ر • ا • ز • ێ • ب", "category": "ڕووبار و جۆگەی ئاو 🌊", "answers": ["زێراب", "زیراب"]}
]

# کۆگای فراوانی وشە بۆ ئەو کاتەی خزمەتگوزاریی AI کاتییەک وەڵام نادات
EXTRA_KURDISH_UNSCRAMBLE_WORDS = [
    ("قوتابخانە", "شوێنی خوێندن و فێربوون 🏫"), ("زانکۆ", "شوێنی خوێندنی باڵا 🎓"),
    ("نەخۆشخانە", "شوێنی چارەسەری نەخۆشان 🏥"), ("دەرمانخانە", "شوێنی کڕینی دەرمان 💊"),
    ("مامۆستا", "پیشەی فێرکردن 👩‍🏫"), ("قوتابی", "کەسێک کە دەخوێنێت 📚"),
    ("ئەندازیار", "پیشەی دیزاین و دروستکردن 📐"), ("پزیشک", "پیشەی چارەسەری نەخۆشی 🩺"),
    ("جوتیار", "پیشەی کشتوکاڵ 🚜"), ("دارتاش", "پیشەی کارکردن بە دار 🪵"),
    ("ئاسنگەر", "پیشەی کارکردن بە ئاسن 🔨"), ("دروومان", "پیشەی دروستکردنی جل 🧵"),
    ("ڕووبار", "ئاوێکی بەردەوام ڕادەکات 🌊"), ("تاڤگە", "ئاو لە بەرزاییەوە دەڕژێت 💦"),
    ("کانیاو", "سەرچاوەی سروشتی ئاو 💧"), ("دارستان", "شوێنێکی پڕ لە دار 🌲"),
    ("ئەشکەوت", "شوێنێکی سروشتی ناو شاخ 🪨"), ("ڕەنگینکەوان", "دوای باران لە ئاسمان دەردەکەوێت 🌈"),
    ("ئەستێرە", "لە شەودا لە ئاسمان دەدرەوشێتەوە ⭐"), ("ئاسمان", "لە سەرووی زەوییە ☁️"),
    ("هەور", "هەڵگری دڵۆپەکانی بارانە ☁️"), ("باران", "دڵۆپی ئاو لە ئاسمانەوە 🌧️"),
    ("بەفر", "بارینی سپیی زستان ❄️"), ("برووسکە", "ڕووناکییەکی خێرای ئاسمان ⚡"),
    ("هەورەتریشقە", "دەنگی بەهێزی کاتی باران 🌩️"), ("پڵنگ", "ئاژەڵێکی کێویی خالدار 🐆"),
    ("گورگ", "ئاژەڵێکی کێویی بەهێز 🐺"), ("ڕێوی", "ئاژەڵێکی زیرەکی کێویی 🦊"),
    ("کەروێشک", "ئاژەڵێکی بچووک و خێرا 🐇"), ("ئاسک", "ئاژەڵێکی جوانی کێویی 🦌"),
    ("ئەسپ", "ئاژەڵێک بۆ سواری 🐎"), ("هەڵۆ", "باڵندەیەکی بەهێزی بەرزفڕ 🦅"),
    ("کەو", "باڵندەیەکی کێویی کوردستان 🐦"), ("کۆتر", "باڵندەیەکی ئاشتی 🕊️"),
    ("چۆلەکە", "باڵندەیەکی بچووک 🐤"), ("ماسی", "گیاندارێک لە ئاو دەژی 🐟"),
    ("کیسەڵ", "گیاندارێکی خاوەن قەڵغان 🐢"), ("پرتەقاڵ", "میوەیەکی نارنجی 🍊"),
    ("شووتی", "میوەیەکی سەوز و ناوسوور 🍉"), ("کالەک", "میوەیەکی شیرینی هاوین 🍈"),
    ("ترێ", "میوەیەکی دەنکەدەنک 🍇"), ("هەنجیر", "میوەیەکی شیرین و ناسک 🌿"),
    ("گوێز", "میوەیەکی وشکی خاوەن توێکڵ 🌰"), ("بادەم", "جۆرێک میوەی وشک 🌰"),
    ("خیار", "سەوزەیەکی درێژ و سەوز 🥒"), ("تەماتە", "سەوزەیەکی سوور 🍅"),
    ("پەتاتە", "سەوزەیەکی ژێرزەوی 🥔"), ("پیاز", "سەوزەیەک فرمێسک دەڕێژێنێت 🧅"),
    ("گێزەر", "سەوزەیەکی نارنجی 🥕"), ("بیبەر", "سەوزەیەکی توند یان شیرین 🌶️"),
    ("هەنگوین", "خواردنێکی شیرین کە هەنگ دروستی دەکات 🍯"), ("پەنیر", "خواردنێک لە شیر دروست دەبێت 🧀"),
    ("کتێب", "سەرچاوەی زانیاری و خوێندن 📖"), ("قەڵەم", "ئامرازێک بۆ نووسین ✏️"),
    ("دەفتەر", "پەڕەی کۆکراوە بۆ نووسین 📒"), ("پەنجەرە", "ڕووناکی لێوە دێتە ژوورەوە 🪟"),
    ("دەرگا", "ڕێگای چوونە ژوورەوە 🚪"), ("کورسی", "کەلەپوورێک بۆ دانیشتن 🪑"),
    ("سەرین", "لە کاتی خەودا سەر لەسەری دادەنێین 🛏️"), ("پەتوو", "لە سەرمادا خۆمانی پێ دادەپۆشین 🧣"),
    ("مۆبایل", "ئامێرێک بۆ پەیوەندی و چات 📱"), ("کۆمپیوتەر", "ئامێرێکی ئەلیکترۆنی بۆ کارکردن 💻"),
    ("ئۆتۆمبێل", "ئامرازێک بۆ گواستنەوە 🚗"), ("فڕۆکە", "لە ئاسماندا دەفڕێت ✈️"),
    ("پاسکیل", "ئامرازێکی دوو تایە بۆ سواری 🚲"), ("کاتژمێر", "کات پیشان دەدات ⌚"),
    ("کلیل", "دەرگا و قوفڵ پێ دەکرێتەوە 🔑"), ("باخچە", "شوێنێکی پڕ لە گوڵ و دار 🌷"),
    ("ئازادی", "مافی ژیان و هەڵبژاردن 🕊️"), ("هاوڕێیەتی", "پەیوەندییەکی جوانی نێوان مرۆڤەکان 🤝"),
    ("خۆشەویستی", "هەستێکی جوان و بەهێز ❤️"), ("سەرکەوتن", "گەیشتن بە ئامانج 🏆"),
    ("داهاتوو", "کاتی دوای ئێستا 🔮"), ("بیرکاری", "زانستی ژمارە و چارەسەر ➗"),
    ("تەکنەلۆجیا", "زانستی ئامێر و نوێکاری 🤖"), ("ژینگە", "سروشت و دەوروبەری ژیان 🌍")
]

for _word, _category in EXTRA_KURDISH_UNSCRAMBLE_WORDS:
    if not any(item["word"] == _word for item in KURDISH_UNSCRAMBLE_WORDS):
        _letters = [char for char in _word if not char.isspace()]
        _mixed = _letters[1::2] + _letters[::2]
        if _mixed == _letters:
            _mixed.reverse()
        KURDISH_UNSCRAMBLE_WORDS.append({
            "word": _word,
            "scrambled": " • ".join(_mixed),
            "category": _category,
            "answers": [_word]
        })

KURDISH_TRUE_FALSE = [
    {
        "question": "ئایا نەهەنگی شین گەورەترین گیانداری سەر زەوییە لە مێژوودا؟",
        "answer": "ڕاست",
        "aliases": ["ڕاست", "راست", "rast", "true", "t", "1"],
        "info": "نەهەنگی شین کێشی دەگاتە نزیکەی ۲۰۰ تۆن و درێژییەکەی ۳۰ مەترە 🐋"
    },
    {
        "question": "ئایا قەڵای هەولێر کۆنترین شوێنی نیشتەجێبووی جیهانە کە بەردەوام مرۆڤی لێ ژیاوە؟",
        "answer": "ڕاست",
        "aliases": ["ڕاست", "راست", "rast", "true", "t", "1"],
        "info": "مێژووی ژیان لە قەڵای هەولێر دەگەڕێتەوە بۆ زیاتر لە ٦۰۰۰ ساڵ پێش ئێستا 🏰"
    },
    {
        "question": "ئایا شەمشەمەکوێرە باڵندەیە و هێلکە دەکات؟",
        "answer": "هەڵە",
        "aliases": ["هەڵە", "هەلە", "hala", "false", "f", "0"],
        "info": "شەمشەمەکوێرە گیاندارێکی شیردەرە و بێچووی دەبێت و شیر دەدات نەک هێلکە 🦇"
    },
    {
        "question": "ئایا هەسارەی مەریخ لە هەموو هەسارەکانی کۆمەڵەی خۆر گەورەترە؟",
        "answer": "هەڵە",
        "aliases": ["هەڵە", "هەلە", "hala", "false", "f", "0"],
        "info": "هەسارەی موشتەری (Jupiter) گەورەترین هەسارەی کۆمەڵەی خۆرە 🪐"
    },
    {
        "question": "ئایا گازی ئۆکسجین زۆرترین ڕێژەی بەرگەهەوای زەوی پێکدەهێنێت؟",
        "answer": "هەڵە",
        "aliases": ["هەڵە", "هەلە", "hala", "false", "f", "0"],
        "info": "گازی نایترۆجین ٧٨٪ی بەرگەهەوای زەوی پێکدەهێنێت و ئۆکسجین تەنها ٢١٪ە 🌍"
    },
    {
        "question": "ئایا زۆربەی سەهۆڵبەندانەکانی جیهان لە جەمسەری باشوور (Antarctica) دان؟",
        "answer": "ڕاست",
        "aliases": ["ڕاست", "راست", "rast", "true", "t", "1"],
        "info": "نزیکەی ۹۰٪ی سەهۆڵی سەر زەوی لە جەمسەری باشوورە 🧊"
    },
    {
        "question": "ئایا چاوی مرۆڤ لە دوای لەدایکبوونەوە هەتا مردن گەشە ناکات و هەمان قەبارە دەمێنێتەوە؟",
        "answer": "ڕاست",
        "aliases": ["ڕاست", "راست", "rast", "true", "t", "1"],
        "info": "چاوی مرۆڤ تاکە ئەندامە کە قەبارەکەی لە لەدایکبوونەوە بە نەگۆڕی دەمێنێتەوە 👀"
    },
    {
        "question": "ئایا ڕووباری نیل درێژترین ڕووباری جیهانە؟",
        "answer": "ڕاست",
        "aliases": ["ڕاست", "راست", "rast", "true", "t", "1"],
        "info": "ڕووباری نیل درێژترین ڕووبارە بە درێژایی ٦٦٥٠ کیلۆمەتر 🌊"
    },
    {
        "question": "ئایا هەنگ لە یەک چرکەدا زیاتر لە ٢٠٠ جار باڵەکانی لێدەدات؟",
        "answer": "ڕاست",
        "aliases": ["ڕاست", "راست", "rast", "true", "t", "1"],
        "info": "دەنگی زیکە و فڕینی هەنگ بەهۆی خێرایی لێدانی باڵەکانییەتی 🐝"
    },
    {
        "question": "ئایا گەڵای دارەکان لە زستاندا بەهۆی بارانبارینەوە زەرد دەبن و هەڵدەوەرێن؟",
        "answer": "هەڵە",
        "aliases": ["هەڵە", "هەلە", "hala", "false", "f", "0"],
        "info": "بەهۆی کەمبوونەوەی ڕووناکی خۆر و ڕاگرتنی ماددەی کلۆرۆفیل گەڵاکان هەڵدەوەرێن 🍂"
    }
]

KURDISH_QUIZZES = [
    {
        "question": "چییە هەرچەند لێی ببەیت زۆرتر دەبێت؟",
        "answers": ["کەلێن", "چاڵ", "کون", "چال", "kelen", "chal", "kwn"],
        "display_answer": "کەلێن یان چاڵ 🕳️"
    },
    {
        "question": "چییە لە دایک دەبێت بە باڵندەیی بەڵام مەلەوانێکی زۆر چاکە و ناتوانێت بفڕێت؟",
        "answers": ["بەتریک", "پەنگوین", "پەنگوینە", "بەتریکە", "penguin", "batrik"],
        "display_answer": "بەتریک (پەنگوین) 🐧"
    },
    {
        "question": "پایتەختی هەرێمی کوردستان ناوی چییە؟",
        "answers": ["هەولێر", "ھەولێر", "erbil", "hawler", "hawlerê"],
        "display_answer": "هەولێری پایتەخت 🏰"
    },
    {
        "question": "چییە پێی نییە بەڵام بە شەودا دەڕوات و بە ڕۆژدا دەوەستێت؟",
        "answers": ["خەو", "ئەستێرە", "مانگ", "xaw", "astera"],
        "display_answer": "خەو یان ئەستێرەکان 🌙✨"
    },
    {
        "question": "بەرزترین شاخی باشووری کوردستان ناوی چییە؟",
        "answers": ["هەڵگورد", "ھەڵگورد", "هلگورد", "helgurd", "halgurd"],
        "display_answer": "لووتکەی هەڵگورد 🏔️"
    },
    {
        "question": "چییە لە ئاودا دروست دەبێت بەڵام ئەگەر بچێتەوە ناو ئاو دەتوێتەوە و دەمرێت؟",
        "answers": ["سەهۆڵ", "بەفر", "خوێ", "شەکر", "sahol", "bafr"],
        "display_answer": "سەهۆڵ یان خوێ 🧊"
    },
    {
        "question": "چییە هەمیشە لە پێش تۆدایە بەڵام هەرگیز ناتوانیت بە چاو بیبینیت؟",
        "answers": ["داهاتوو", "ئایندە", "سبەینێ", "dahatu", "ayinda"],
        "display_answer": "داهاتوو (ئایندە) 🔮"
    },
    {
        "question": "چییە تەنها یەک چاوی هەیە بەڵام نابینایە و ناتوانێت هیچ شتێک ببینێت؟",
        "answers": ["دەرزی", "دەرزێ", "darzi", "derzi"],
        "display_answer": "دەرزی 🪡"
    },
    {
        "question": "چییە پێستی هەیە بەڵام گۆشتی نییە، پەڕەی هەیە بەڵام باڵندە نییە؟",
        "answers": ["کتێب", "دەفتەر", "kteb", "daftar"],
        "display_answer": "کتێب 📚"
    },
    {
        "question": "چییە کاتێک باران دەبارێت ئەو بەرز دەبێتەوە؟",
        "answers": ["چەتر", "شەمسیە", "chatr", "shamsya"],
        "display_answer": "چەتر ☂️"
    },
    {
        "question": "چییە کە بۆ تۆیە، بەڵام خەڵکی تر زۆرتر لە تۆ بەکاری دەهێنن؟",
        "answers": ["ناو", "ناوت", "ناوی خۆت", "naw", "nawt"],
        "display_answer": "ناوی خۆت 🏷️"
    },
    {
        "question": "شاری دڵداری و ڕۆشنبیری کوردستان ناوی کام شارەیە؟",
        "answers": ["سلێمانی", "سلیمانی", "slemani", "sulaymaniyah"],
        "display_answer": "شاری سلێمانی 🌸"
    },
    {
        "question": "چییە بە دەوری هەموو ماڵەکەدا دەسووڕێتەوە بێ ئەوەی یەک هەنگاو بجوڵێت؟",
        "answers": ["پەرژین", "حەسار", "دیوار", "شوورە", "diwar", "hasar"],
        "display_answer": "پەرژین یان دیواری ماڵ 🏡"
    },
    {
        "question": "چییە کاتێک پێویستت پێیەتی فڕێی دەدەیت، بەڵام کاتێک پێویستت پێی نییە هەڵی دەگریتەوە؟",
        "answers": ["لەنگەر", "لەنگەری کەشتی", "لنگەر", "anchor", "langer"],
        "display_answer": "لەنگەری کەشتی ⚓"
    },
    {
        "question": "چییە چەند پاکی بکەیتەوە ڕەشتر دەبێت؟",
        "answers": ["تەختەڕەش", "تەختە ڕەش", "سبورە", "takhta rash", "blackboard"],
        "display_answer": "تەختەڕەش 🎓"
    },
    {
        "question": "چییە زمان و دەمی نییە بەڵام بە هەموو زمانەکانی دونیا قسە دەکات و دەنگ دەداتەوە؟",
        "answers": ["دەنگدانەوە", "زرنگانەوە", "پەنگدانەوە", "echo", "danganawa"],
        "display_answer": "دەنگدانەوە (سەدا) 📢"
    },
    {
        "question": "چییە ملی هەیە بەڵام سەری نییە، قۆڵی هەیە بەڵام دەستی نییە؟",
        "answers": ["کراس", "بلوز", "جل", "قەمیس", "kras", "bluz"],
        "display_answer": "کراس یان بلوز 👕"
    },
    {
        "question": "کام باڵندەیە کە هێلکە ناکات بەڵکو بێچووی دەبێت و شیر دەدات؟",
        "answers": ["شەمشەمەکوێرە", "شەمشەمە کوێرە", "باڵندەی شەو", "bat", "shamshama kwera"],
        "display_answer": "شەمشەمەکوێرە 🦇"
    },
    {
        "question": "چییە لە تاریکیدا دیارە و لە ڕووناکیدا وون دەبێت؟",
        "answers": ["ئەستێرە", "شەوق", "مانگ", "astera", "mang"],
        "display_answer": "ئەستێرەکان 🌟"
    },
    {
        "question": "چییە ددانی زۆری هەیە بەڵام هەرگیز ناتوانێت گازی لێ بگرێت؟",
        "answers": ["شانە", "مەشانە", "شانه", "shana", "comb"],
        "display_answer": "شانەی قژ 💇‍♂️"
    },
    {
        "question": "چییە ئەگەر نانی پێ بدەیت دەژی و گەشە دەکات، بەڵام ئەگەر ئاوی پێ بدەیت دەمرێت؟",
        "answers": ["ئاگر", "پشکۆ", "agir", "fire"],
        "display_answer": "ئاگر 🔥"
    },
    {
        "question": "چییە بەردەوام بە دواتدا دەڕوات بەڵام هەرگیز ناتوانیت دەستی لێ بدەیت یان بیگریت؟",
        "answers": ["سێبەر", "سێبەرەکەت", "سیبەر", "sebar", "shadow"],
        "display_answer": "سێبەر 👤"
    },
    {
        "question": "چییە تەنها کاتێک دەیشکێنیت دەتوانیت بەکاری بهێنیت و بیخۆیت؟",
        "answers": ["هێلکە", "هێلکه", "هیلکە", "helka", "egg"],
        "display_answer": "هێلکە 🥚"
    },
    {
        "question": "چییە سەری دەبڕیت و لە جیاتی ئەو تۆ فرمێسک دەڕێژیت و بۆی دەگریت؟",
        "answers": ["پیاز", "پیازە", "pyaz", "onion"],
        "display_answer": "پیاز 🧅"
    },
    {
        "question": "چییە پڕە لە کون بەڵام ئاو لە خۆیدا ڕادەگرێت؟",
        "answers": ["ئیسفەنج", "ئسفەنج", "sponge", "isfanj"],
        "display_answer": "ئیسفەنج 🧽"
    },
    {
        "question": "چییە کلیلێکی زۆری هەیە بەڵام هیچ دەرگایەک ناکاتەوە؟",
        "answers": ["پیانۆ", "پیانو", "ساز", "piano"],
        "display_answer": "پیانۆ 🎹"
    },
    {
        "question": "چییە پێش ئەوەی دایگیرسێنیت درێژە، بەڵام لە کاتی سووتان و بەکارهێناندا کورت دەبێتەوە؟",
        "answers": ["مۆم", "مۆمە", "mom", "candle"],
        "display_answer": "مۆم 🕯️"
    },
    {
        "question": "چییە هەموو ژوورەکانی ماڵ دەگەڕێت و لە کۆتاییدا لە سووچێکدا دەوەستێت؟",
        "answers": ["گسک", "گسکەدەم", "گسکە کارەبایی", "gsk", "broom"],
        "display_answer": "گسک 🧹"
    },
    {
        "question": "چییە پێستی سەوزە، ناوەکەی سوورە و دەنکەکانی ڕەشن؟",
        "answers": ["شووتی", "شوتی", "shuti", "watermelon"],
        "display_answer": "شووتی 🍉"
    },
    {
        "question": "چییە شار و وڵاتی هەیە بێ خانووبەرە، ڕووباری هەیە بێ ئاو، و دارستانی هەیە بێ دار؟",
        "answers": ["نەخشە", "نەخشه", "naxsha", "map"],
        "display_answer": "نەخشەی جیهان 🗺️"
    },
    {
        "question": "چییە قسەی لەگەڵ دەکەیت وەڵامت ناداتەوە، بەڵام هەموو ڕوخسارت وەک خۆت پیشان دەداتەوە؟",
        "answers": ["ئاوێنە", "ئاوێنه", "awena", "mirror"],
        "display_answer": "ئاوێنە 🪞"
    },
    {
        "question": "چییە باڵی نییە بەڵام دەفڕێت، چاوی نییە بەڵام بە کوڵ دەگریت؟",
        "answers": ["هەور", "ھەور", "hewr", "cloud"],
        "display_answer": "هەور ☁️🌧️"
    },
    {
        "question": "چییە بەردەوام دەڕوات و یەک چرکەش ناوەستێت، بەڵام هەرگیز لە شوێنی خۆی جوڵە ناکات؟",
        "answers": ["کاتژمێر", "کات", "saat", "katjmer"],
        "display_answer": "کاتژمێر ⏰"
    },
    {
        "question": "چییە لە بەیانیاندا بە چوار پێ، لە نیوەڕۆدا بە دوو پێ، و لە ئێواراندا بە سێ پێ دەڕوات؟",
        "answers": ["مرۆڤ", "ئادەمیزاد", "مروف", "mrov", "human"],
        "display_answer": "مرۆڤ (منداڵی، گەنجی، پیری) 🚶‍♂️"
    },
    {
        "question": "چییە هەرچەندە بیبەستیتەوە خێراتر دەڕوات؟",
        "answers": ["پێڵاو", "قەیتان", "قەیتانی پێڵاو", "pelaw", "shoes"],
        "display_answer": "پێڵاو (قەیتان) 👟"
    },
    {
        "question": "چییە گەورە دەبێت بێ ئەوەی تەمەنی زیاد بکات، و بچووک دەبێتەوە بێ ئەوەی کەم ببێت؟",
        "answers": ["مانگ", "مانگەشەو", "mang", "moon"],
        "display_answer": "مانگ لە ئاسماندا 🌙"
    },
    {
        "question": "چییە بە دەمدا دەچێت بەڵام قووتی نادەیت و تەنها دەیجوی؟",
        "answers": ["بنێشت", "بنیست", "bnesht", "gum"],
        "display_answer": "بنێشت 🍬"
    },
    {
        "question": "چییە کاتێک ناوی دەهێنیت دەستبەجێ دەشکێت و لەناو دەچێت؟",
        "answers": ["بێدەنگی", "سکووت", "بیدەنگی", "bedangi", "silence"],
        "display_answer": "بێدەنگی 🤫"
    },
    {
        "question": "چییە سەدان کونی هەیە بەڵام هیچ دەرگایەکی نییە و ئاردی پێدا دەبێژیت؟",
        "answers": ["بێژنگ", "سۆزن", "بێژینگە", "bezhng", "sieve"],
        "display_answer": "بێژنگ 🌾"
    },
    {
        "question": "چییە هەموو ڕێبوار و ئۆتۆمبێلەکان بە سەریدا دەڕۆن بەڵام خۆی هەرگیز یەک هەنگاو ناجوڵێت؟",
        "answers": ["شەقام", "ڕێگا", "کۆڵان", "جادە", "shaqam", "rega"],
        "display_answer": "شەقام یان ڕێگا 🛣️"
    },
    {
        "question": "چییە قەڵایەکی سوورە و سەربازەکانی ناوەوەی سپین؟",
        "answers": ["دەم و ددان", "ددان", "دەم", "ddan", "teeth"],
        "display_answer": "دەم و ددانەکان 👄🦷"
    },
    {
        "question": "چییە ماڵەکەی لەسەر پشتیەتی و زۆر بە هێواشی دەڕوات؟",
        "answers": ["کیسەڵ", "کیسەل", "کیسەڵە", "kesal", "turtle"],
        "display_answer": "کیسەڵ 🐢"
    },
    {
        "question": "چییە لە ناو ئاو دەژی و هەناسە دەدات بەڵام ئەگەر بێتە دەرەوەی ئاو دەمرێت؟",
        "answers": ["ماسی", "ماسیە", "masi", "fish"],
        "display_answer": "ماسی 🐟"
    },
    {
        "question": "چییە خۆی نابینایە و چاوی نییە بەڵام ڕێگای ڕاست پیشانی کەسانی نابینا و بەساڵاچوو دەدات؟",
        "answers": ["گۆچان", "دارعەسا", "عەسا", "gochan", "cane"],
        "display_answer": "گۆچان (دارعەسا) 🦯"
    },
    {
        "question": "چییە هەزاران سەرباز و کرێکاری هەیە بەڵام تەنها یەک شای مێینەی هەیە؟",
        "answers": ["هەنگ", "شانەی هەنگ", "hang", "bee"],
        "display_answer": "شانەی هەنگ 🐝🍯"
    },
    {
        "question": "چییە بە ڕۆژدا پڕە لە پێ و بە شەودا کاتێک دەخەویت بەتاڵە؟",
        "answers": ["پێڵاو", "کەوش", "pelaw", "shoes"],
        "display_answer": "پێڵاو 👞"
    },
    {
        "question": "چییە دەتوانیت لە دەستتدا بیگریت بەڵام ئەگەر ئاوی لێ بدەیت کەم دەبێتەوە و دەتوێتەوە؟",
        "answers": ["سابوون", "سابون", "sabun", "soap"],
        "display_answer": "سابوون 🧼"
    },
    {
        "question": "چییە بێ باڵ دەفڕێت و بێ ددان پەردەی گوێت دەزرنگێنێتەوە و گەڵاکان دەلەرێنێت؟",
        "answers": ["با", "ڕەشەبا", "شەماڵ", "ba", "wind"],
        "display_answer": "با (ڕەشەبا) 💨"
    },
    {
        "question": "چییە سەری هەیە و پێی نییە، پشتی هەیە و زگی نییە و لە هەموو ماڵێکدا لەسەری دادەنیشین؟",
        "answers": ["کورسی", "مێز", "kursi", "chair"],
        "display_answer": "کورسی 🪑"
    },
    {
        "question": "چییە بێ ئەوەی یەک هەنگاو لە جێی خۆت بجوڵێیت دەتبات بۆ هەموو شوێنێکی دونیا؟",
        "answers": ["خەیاڵ", "بیرکردنەوە", "خەو", "xayal", "thought"],
        "display_answer": "خەیاڵ و بیرکردنەوە 💭✨"
    },
    {
        "question": "چییە لە ناو ماڵدا دەبارێت بێ ئەوەی یەک هەور لە ئاسماندا هەبێت؟",
        "answers": ["دووش", "حەمام", "دوش", "shower", "dush"],
        "display_answer": "دووشی حەمام 🚿"
    },
    {
        "question": "چییە کە کەم بێت شیرین و تەندروستە، بەڵام کە زۆر بێت تەمبەڵت دەکات؟",
        "answers": ["خەو", "نووستن", "xaw", "sleep"],
        "display_answer": "خەو 😴"
    },
    {
        "question": "چییە هەموو مرۆڤێکی سەر زەوی هەیەتی و پەنجەکانی هی هیچ دوو کەسێک لە یەک ناچن؟",
        "answers": ["پەنجەمۆر", "پەنجە مۆر", "دەستنیشان", "panjamor", "fingerprint"],
        "display_answer": "پەنجەمۆر 🖐️🔍"
    },
    {
        "question": "چییە لە ناو تەنووردا بە سپێتی دادەنرێت و کاتێک دەبرژێت بە سوورێتی و گەرمی دێتە دەرەوە؟",
        "answers": ["نان", "نانە", "nan", "bread"],
        "display_answer": "نان 🍞"
    },
    {
        "question": "چییە پڕە لە سندووقی ئاودار و توێکڵێکی پڕتەقاڵی جوانی هەیە؟",
        "answers": ["پڕتەقاڵ", "پرتەقال", "لیمۆ", "portaqal", "orange"],
        "display_answer": "پڕتەقاڵ 🍊"
    },
    {
        "question": "چییە سەری لە ئاسمانە و بەرزە، بەڵام ڕەگ و پێیەکانی لە قووڵایی زەویدان؟",
        "answers": ["دار", "درەخت", "dar", "tree"],
        "display_answer": "دار (درەخت) 🌳"
    },
    {
        "question": "چییە باڵندە نییە و نافڕێت بەڵام پڕە لە پەڕ و لە ژێر سەرت دادەنێیت؟",
        "answers": ["سەرین", "باڵنج", "بالنج", "sarin", "pillow"],
        "display_answer": "سەرین (باڵنج) 🛏️"
    },
    {
        "question": "چییە هەموو ڕۆژێک لە بەیانیدا لەدایک دەبێت و لە ئێواراندا ئاوا دەبێت و دەمرێت؟",
        "answers": ["خۆر", "ڕۆژ", "هەتاو", "xor", "sun"],
        "display_answer": "خۆر (هەتاو) ☀️"
    },
    {
        "question": "چییە لە وەرزی زستاندا دەبارێت و چیایەکان سپیپۆش دەکات؟",
        "answers": ["بەفر", "بەفرە", "bafr", "snow"],
        "display_answer": "بەفر ❄️🏔️"
    },
    {
        "question": "چییە لە هەموو ژوور و سووچێکی ماڵدا هەیە و لە هەر چوار لادا کۆتایی دێت؟",
        "answers": ["گۆشە", "سووچ", "سوچ", "gosha", "corner"],
        "display_answer": "گۆشە (سووچی ژوور) 📐"
    },
    {
        "question": "چییە دوو برای دوانەن و بەردەوام دەبینن بەڵام هەرگیز ناتوانن یەکتری ببینن بێ ئاوێنە؟",
        "answers": ["چاو", "چاوەکان", "chaw", "eyes"],
        "display_answer": "چاوەکان 👀"
    },
    {
        "question": "چییە لەسەر سەر دەڕوێت و بە بڕین درێژتر دەبێتەوە و نایەشێت؟",
        "answers": ["قژ", "موو", "پرچ", "qzh", "hair"],
        "display_answer": "قژ (پرچ) 💇"
    },
    {
        "question": "چییە لە دڵی مرۆڤدایە و ئەگەر بۆ یەک چرکە بوەستێت ژیان کۆتایی دێت؟",
        "answers": ["دڵ", "لێدانی دڵ", "dl", "heart"],
        "display_answer": "دڵ ❤️"
    },
    {
        "question": "چییە خواردنی هەمەجۆر دەخوات بێ ئەوەی قەڵەو بێت و دەبێتە سووتەمەنی؟",
        "answers": ["ئۆتۆمبێل", "سەیارە", "car", "sayara"],
        "display_answer": "ئۆتۆمبێل 🚗"
    },
    {
        "question": "چییە دەتوانیت لە ڕێگەیەوە لەگەڵ کەسانی دوور لە خۆت بە دەنگ و ڕەنگ قسە بکەیت؟",
        "answers": ["مۆبایل", "تەلەفۆن", "دەستەوانە", "mobile", "phone"],
        "display_answer": "مۆبایل (تەلەفۆن) 📱"
    },
    {
        "question": "چییە لە زستاندا خواردن سارد دەکات و لە هاویندا بەستوو دەیهێڵێتەوە؟",
        "answers": ["سەلاجە", "فرێزەر", "بەفرگر", "salaja", "fridge"],
        "display_answer": "سەلاجە (بەفرگر) 🧊❄️"
    },
    {
        "question": "چییە پڕە لە چیرۆک و فیلم بێ ئەوەی مرۆڤ بێت و لە سەر دیوار هەڵواسراوە؟",
        "answers": ["تەلەڤزیۆن", "تیڤی", "tv", "television"],
        "display_answer": "تەلەڤزیۆن (TV) 📺"
    },
    {
        "question": "چییە بە شەودا ئەستێرەکان دەدرەوشێنێتەوە و ڕۆژدا بە خۆر ڕووناک دەبێتەوە؟",
        "answers": ["ئاسمان", "گەردوون", "asman", "sky"],
        "display_answer": "ئاسمان 🌌"
    },
    {
        "question": "چییە چوار پێی هەیە بەڵام ناتوانێت یەک هەنگاویش بهاوێژێت و قاپ و نانی لەسەر دادەنێیت؟",
        "answers": ["مێز", "مێزی نانخواردن", "mez", "table"],
        "display_answer": "مێز 🪵"
    },
    {
        "question": "چییە کە بۆنی خۆشە و گوڵەباخ و نێرگز بەرهەمی دەهێنن؟",
        "answers": ["گوڵ", "بۆن", "عەتر", "gul", "flower"],
        "display_answer": "گوڵ 🌸💐"
    },
    {
        "question": "چییە لە مانگی ڕەمەزاندا دەخورێت و بەناوبانگە بە خورمای بەسرە و بەغدا؟",
        "answers": ["خورما", "خورمایە", "xurma", "dates"],
        "display_answer": "خورما 🌴"
    },
    {
        "question": "چییە مرۆڤ لە بێستاندا دەیکێڵێت و لە کۆتایی هاویندا ترێی لێ دەکاتەوە؟",
        "answers": ["ڕەز", "مێو", "دارترێ", "rez", "vineyard"],
        "display_answer": "ڕەز (مێوی ترێ) 🍇"
    },
    {
        "question": "چییە کاتێک لە ئاگر دایبنێیت ئاوی تێدایە و چای پێ لێدەنێیت؟",
        "answers": ["قۆری", "چایدان", "کتری", "qori", "kettle"],
        "display_answer": "قۆری یان چایدان 🫖"
    },
    {
        "question": "چییە لە دایک دەبێت بە سپێتی و دەتوێتەوە لە ناو چادا؟",
        "answers": ["شەکر", "قەند", "shakar", "sugar"],
        "display_answer": "شەکر (قەند) 🧂"
    },
    {
        "question": "چییە شەوانە ئەگەر کلیلەکەی بسووڕێنیت دەرگا دادەخات بۆ پاراستنی ماڵ؟",
        "answers": ["قوفڵ", "کلیل", "qufl", "lock"],
        "display_answer": "قوفڵ 🔒"
    },
    # 🎭 مەتەڵە کۆمیدی و خۆش و پێکەنیناوییەکان (Comedy & Funny Riddles)
    {
        "question": "چییە سپییە، دەفڕێت و لە کاتی شەڕە چەقۆدا لە دەم دێتە دەرەوە؟ 😂",
        "answers": ["ددان", "ددانە", "ddan", "tooth"],
        "display_answer": "ددان کاتێک زلەیەکت لێ دەدەن! 🦷😂"
    },
    {
        "question": "بۆچی مریشک ناتوانێت پێڵاو لەپێ بکات؟ 🐔😂",
        "answers": ["قەیتان", "قەیتانی پێڵاو", "دەست", "دەستی نییە", "qaytan"],
        "display_answer": "چونکە دەستی نییە قەیتانی پێڵاوەکەی ببەستێتەوە! 👟🐔😂"
    },
    {
        "question": "چییە دەچێتە ناو سەلاجە و ئەگەر دەرگاکەی بکەیتەوە سارد دەبێت؟ 🐘😂",
        "answers": ["فیل", "فیلەکە", "fil", "elephant"],
        "display_answer": "فیلێک کە دەرگای سەلاجەکەی بۆ بکەیتەوە و بیخەیتە ناوی! 🐘🧊😂"
    },
    {
        "question": "چییە کە بە هەڵە بنووسرێت ڕاستە، بەڵام کە بە ڕاستی بنووسرێت هەڵەیە؟ 🧠😂",
        "answers": ["هەڵە", "وشەی هەڵە", "وشەی هه‌ڵه‌", "hala"],
        "display_answer": "وشەی (هەڵە)! 📝😂"
    },
    {
        "question": "چییە یەک گوێی هەیە بەڵام ئەگەر هەرچەندە هاواریش بکەیت نابیستێت؟ ☕😂",
        "answers": ["فنجان", "فنجانی چا", "کوپ", "قۆری", "fnjan", "cup"],
        "display_answer": "فنجانی چا یان کوپ! ☕👂😂"
    },
    {
        "question": "بۆچی کاتژمێر دەست و پەنجەی هەیە بەڵام هەرگیز چەپڵە لێنادات؟ ⏰😂",
        "answers": ["دڵ", "چەپڵە", "دەستی نییە", "پەنجە", "باتری", "chapla"],
        "display_answer": "چونکە مۆسیقا ژەندن نازانێت و بێدەنگە! 👏⏰😂"
    },
    {
        "question": "چییە دەتوانیت بە چاوی چەپت بیبینیت بەڵام هەرگیز بە چاوی ڕاستت نایبینیت؟ 👀😂",
        "answers": ["چاوی ڕاست", "چاوی راست", "چاو", "chawi rast"],
        "display_answer": "چاوی ڕاستت خۆت! 👁️😂"
    },
    {
        "question": "چییە لە کۆتایی هەموو وتار و نامە و قسەیەکدا هەمیشە دێت؟ ✍️😂",
        "answers": ["خاڵ", "خاڵە", "نوقتە", "point", "dot"],
        "display_answer": "خاڵ (.) لە کۆتایی ڕستە! 🔴😂"
    },
    {
        "question": "چییە بە دەنگی بەرز پێدەکەنێت بەڵام کاتێک دەمی دەکەیتەوە هیچ ددانی تێدا نییە؟ 👶😂",
        "answers": ["منداڵ", "ساوا", "کۆرپە", "mndal", "baby"],
        "display_answer": "منداڵی ساوا و شیرەخۆرە! 👶🍼😂"
    },
    {
        "question": "چییە زۆر خێرا ڕادەکات بەڵام قاچی نییە، کاتێکیش پێت دەگات دڵت کەیفخۆش دەکات؟ 💸😂",
        "answers": ["پارە", "موعاش", "ڕاتب", "مووچە", "para", "money"],
        "display_answer": "پارە و مووچەی سەری مانگ! 💵💰😂"
    },
    {
        "question": "بۆچی ماسی هەرگیز لە قوتابخانە و تاقیکردنەوە دەرناچێت؟ 🐟😂",
        "answers": ["مێشک", "خوێندن", "ئاو", "پێنووس", "ژێر ئاو"],
        "display_answer": "چونکە هەمیشە مێشکی لە ژێر ئاوە و دەفتەرەکەی تەڕ دەبێت! 🌊🐟😂"
    },
    {
        "question": "چییە کاتێک باران دەبارێت یەکەم کەس دەچێتە ماڵەوە و دەخەوێت؟ 🐌😂",
        "answers": ["کیسەڵ", "شەیتانۆکە", "حلزۆن", "kesal"],
        "display_answer": "شەیتانۆکە (حلزۆن) دەچێتە ناو ماڵەکەی خۆی! 🐌🌧️😂"
    },
    {
        "question": "چییە هەموو کەسێک دەتوانێت بە ئاسانی فڕێی بدات بەڵام زۆر بە زەحمەت دەتوانێت هەڵی بگریتەوە؟ 🗣️😂",
        "answers": ["قسە", "قسەی ناشرین", "قسەی هەڵە", "نهێنی", "qsa"],
        "display_answer": "قسەیەک کە لە دەم دەردەچێت! 💬😂"
    },
    {
        "question": "چییە بە شەودا ئەگەر برسی بێت دێتە سەر پێستت و پێت دەڵێت وززززز؟ 🦟😂",
        "answers": ["مێشولە", "مێشولەیە", "پشیلە", "meshula", "mosquito"],
        "display_answer": "مێشولەی هاوینان! 🦟😂"
    },
    {
        "question": "چییە کاتێک لە دەستت دەکەوێتە خوارەوە ناشکێت، بەڵام ئەگەر بیخەیتە ناو ئاو وون دەبێت؟ 📄😂",
        "answers": ["کاغەز", "کلێنس", "پەڕە", "kaghaz", "tissue"],
        "display_answer": "کاغەز یان کلێنس! 🧻😂"
    },
    {
        "question": "چییە لە دایک دەبێت بە ڕەشی، بەکاردێت بە سووری، و فڕێدەدرێت بە خۆڵەمێشی؟ 🔥😂",
        "answers": ["خەڵووز", "خەڵوز", "پشکۆ", "xaluz", "coal"],
        "display_answer": "خەڵووزی نێرگەلە و کەباب! 🪵🔥😂"
    },
    {
        "question": "بۆچی ئەستێرەکان تەنها بە شەودا دەردەکەون؟ ⭐😂",
        "answers": ["خەو", "ڕۆژ", "خۆر", "شەرم", "ڕۆژدا کار دەکەن"],
        "display_answer": "چونکە بە ڕۆژدا خەریکی خەوتن و پشوودانن! 😴⭐😂"
    },
    {
        "question": "چییە لە ناو چێشتخانەدا هەموو کەسێک دەترسێنێت ئەگەر پەنجەی لێ بدەیت؟ 🌶️😂",
        "answers": ["بیبەر", "بیبەری توند", "چەقۆ", "bebar", "pepper"],
        "display_answer": "بیبەری تووند کە دەستت دەسوتێنێت! 🌶️🔥😂"
    },
    {
        "question": "بۆچی فیل ناتوانێت پایسکل لێبخوڕێت؟ 🚲🐘😂",
        "answers": ["قاچ", "قورسە", "پەنجە", "پایسکلی نییە", "زەنگ"],
        "display_answer": "چونکە زەنگی پایسکلەکە بە خرتی فیل لێنادرێت! 🔔🐘😂"
    },
    {
        "question": "چییە کاتێک لەگەڵ هاوڕێکانت دەخۆیت زۆر خۆشە بەڵام کاتێک بە تەنیا دەیخۆیت زوو تەواو دەبێت؟ 🍕😂",
        "answers": ["پیتزا", "شیرینی", "کێک", "pizza", "xwardn"],
        "display_answer": "پیتزای گەورەی هاوڕێیانە! 🍕😋😂"
    },
    {
        "question": "چییە هەموو بەیانییەک بانگت دەکات و دەڵێت هەستە، بەڵام خۆی قاچی نییە و ناڕوات بۆ دەوام؟ ⏰😂",
        "answers": ["مۆبایل", "ئاڵارم", "کاتژمێر", "alarm", "clock"],
        "display_answer": "ئاڵارمی مۆبایل و کاتژمێر! ⏰😴😂"
    },
    {
        "question": "چییە لە باخچەدا سەوزە، لە دوکاندا ڕەشە، و لە ماڵەوە کاتێک دەیخۆیتەوە سوورە؟ ☕😂",
        "answers": ["چا", "چای", "چایە", "cha", "tea"],
        "display_answer": "چای کوردی! 🫖☕😂"
    },
    {
        "question": "چییە ڕووخساری هەیە و دوو دەستی هەیە، بەڵام نە چاوی هەیە نە پەنجە؟",
        "answers": ["کاتژمێر", "سەعات", "کاتژمێرە", "clock", "saat"],
        "display_answer": "کاتژمێر ⏰"
    },
    {
        "question": "چییە کاتێک تۆ وشک دەکاتەوە، خۆی تەڕتر دەبێت؟",
        "answers": ["خاولی", "دەستەسڕ", "حەولە", "towel", "xawli"],
        "display_answer": "خاولی یان دەستەسڕ 🧻"
    },
    {
        "question": "چییە تەنها بە ناوهێنانی، دەیشکێنیت؟",
        "answers": ["بێدەنگی", "سکوت", "بێ دەنگی", "silence", "bedangi"],
        "display_answer": "بێدەنگی 🤫"
    },
    {
        "question": "چییە دەمی هەیە و جێگای خەوتنی هەیە، بەڵام نە قسە دەکات نە دەخەوێت؟",
        "answers": ["ڕووبار", "رودخانە", "ڕووبارە", "river", "rubar"],
        "display_answer": "ڕووبار؛ دەمی ڕووبار و جێگای ڕووبار هەیە 🌊"
    },
    {
        "question": "چییە بەردەوام زیاد دەبێت، بەڵام هەرگیز کەم نابێتەوە؟",
        "answers": ["تەمەن", "عومر", "ساڵ", "age", "taman"],
        "display_answer": "تەمەنی مرۆڤ 🎂"
    },
    {
        "question": "چییە هەموو جیهان دەگەڕێت، بەڵام هەمیشە لە سووچی نامەیەکدا دەمێنێتەوە؟",
        "answers": ["مۆر", "تمبەر", "مۆری پۆستە", "stamp", "mor"],
        "display_answer": "مۆری پۆستە ✉️"
    },
    {
        "question": "چییە ملێکی هەیە بەڵام سەری نییە، سکێکی هەیە بەڵام قاچی نییە؟",
        "answers": ["بوتڵ", "شووشە", "بوتری", "bottle", "butll"],
        "display_answer": "بوتڵ یان شووشە 🍾"
    },
    {
        "question": "چییە چوار قاچی هەیە، بەڵام ناتوانێت هەنگاو بنێت؟",
        "answers": ["مێز", "کورسی", "تەخت", "table", "mez"],
        "display_answer": "مێز 🪑"
    },
    {
        "question": "چییە پێنج پەنجەی هەیە، بەڵام نە گۆشتی هەیە نە ئێسک؟",
        "answers": ["دەستکێش", "دەستکێشە", "glove", "dastkesh"],
        "display_answer": "دەستکێش 🧤"
    },
    {
        "question": "چییە زمانی هەیە بەڵام قسە ناکات، لە پێشداش دەژی؟",
        "answers": ["پێڵاو", "کەوش", "پێلاو", "shoe", "pelaw"],
        "display_answer": "پێڵاو؛ زمانی پێڵاو 👟"
    },
    {
        "question": "چییە فیشەکی نییە بەڵام وێنەت دەگرێت؟",
        "answers": ["کامێرا", "کامەرا", "مۆبایل", "camera", "kamera"],
        "display_answer": "کامێرا 📷"
    },
    {
        "question": "چییە دەمی نییە بەڵام کاتێک ئاوەکەی گەرم دەبێت فیکە دەکات؟",
        "answers": ["کتری", "چايدان", "کتڵ", "kettle", "kitri"],
        "display_answer": "کتریی چای 🫖"
    },
    {
        "question": "چییە پڕە لە پەڕە، بەڵام نە دارە نە باڵندە؟",
        "answers": ["ڕۆژژمێر", "ساڵنامە", "کتێب", "calendar", "rozhmer"],
        "display_answer": "ڕۆژژمێر یان ساڵنامە 📅"
    },
    {
        "question": "چییە بەبێ پێ لە شارێکەوە بۆ شارێکی تر دەڕوات؟",
        "answers": ["ڕێگا", "جادە", "رێگا", "road", "rega"],
        "display_answer": "ڕێگا 🛣️"
    },
    {
        "question": "چییە سەرەتای هەموو شەوێکە و کۆتایی هەموو ڕۆژێکە؟",
        "answers": ["پیتی ش", "ش", "پیت ش", "letter sh"],
        "display_answer": "پیتی «ش»؛ سەرەتای شەو و کۆتایی ڕۆژ 🌙"
    },
    {
        "question": "چییە هەرگیز نایەت، چونکە کاتێک بێت ناوی دەبێتە ئەمڕۆ؟",
        "answers": ["سبەی", "سبەینێ", "بەیانی", "tomorrow", "sbey"],
        "display_answer": "سبەینێ ⏳"
    },
    {
        "question": "چییە هیچ کێشێکی نییە، بەڵام دەتوانێت ژوورێکی تەواو پڕ بکات؟",
        "answers": ["ڕووناکی", "تاریکی", "نور", "light", "runaki"],
        "display_answer": "ڕووناکی 💡"
    },
    {
        "question": "چییە بەبێ دەرگا دێتە ژوورەوە و بەبێ پەنجەرە دەچێتە دەرەوە؟",
        "answers": ["هەوا", "با", "ھەوا", "air", "hawa"],
        "display_answer": "هەوا یان با 🌬️"
    },
    {
        "question": "چییە کاتێک لێی دەڕوانیت تۆ دەبینێت، بەڵام چاوی نییە؟",
        "answers": ["ئاوێنە", "ئاوێنه", "ئاوی نەجوڵاو", "mirror", "awena"],
        "display_answer": "ئاوێنە 🪞"
    },
    {
        "question": "چییە بەبێ قاچ هەڵدەکشێت و بەبێ باڵ بەرەو ئاسمان دەڕوات؟",
        "answers": ["دووکەڵ", "دود", "هەڵم", "smoke", "dukal"],
        "display_answer": "دووکەڵ 💨"
    },
    {
        "question": "چییە پێش باران دێت و دوای باران دەردەکەوێت، بەڵام تەڕ نابێت؟",
        "answers": ["هەور", "کەوانەی باران", "ڕەنگینکەوان", "rainbow", "hawr"],
        "display_answer": "هەور پێش باران و ڕەنگینکەوان دوای باران؛ وەڵامی سەرەکی: هەور ☁️"
    },
    {
        "question": "چییە هەزاران دەنکی هەیە، بەڵام ناتوانێت یەک وشەش بڵێت؟",
        "answers": ["هەنار", "گوێز", "گەنم", "pomegranate", "hanar"],
        "display_answer": "هەنار؛ پڕە لە دەنک 🍎"
    },
    {
        "question": "چییە هەرچی زیاتر بەکاری بهێنیت، کورتتر دەبێتەوە؟",
        "answers": ["قەڵەم", "پەنسڵ", "مۆم", "pencil", "qalam"],
        "display_answer": "پەنسڵ ✏️"
    },
    {
        "question": "چییە دەتوانیت بیگریت بەڵام ناتوانیت فڕێی بدەیت؟",
        "answers": ["هەناسە", "سەرما", "نەخۆشی", "breath", "hanasa"],
        "display_answer": "هەناسەت؛ دەتوانیت ڕایبگریت 😮‍💨"
    },
    {
        "question": "چییە هەرچی زیاتر لێی بنووسیت، خۆی کەمتر دەبێتەوە؟",
        "answers": ["تەباشیر", "گچ", "قەڵەم", "chalk", "tabashir"],
        "display_answer": "تەباشیر 🧑‍🏫"
    },
    {
        "question": "چییە بە دەیان کلیلی هەیە، بەڵام تەنها دەنگ و مۆسیقا دەکاتەوە؟",
        "answers": ["پیانۆ", "ئۆرگ", "کیبۆرد", "piano", "pyano"],
        "display_answer": "پیانۆ 🎹"
    },
    {
        "question": "چییە دوو برا هەمیشە لە تەنیشت یەکترن، بەڵام هەرگیز یەکتر نابینن؟",
        "answers": ["چاو", "دوو چاو", "چاوەکان", "eyes", "chaw"],
        "display_answer": "دوو چاوەکان 👀"
    },
    {
        "question": "چییە کاتێک دەیکڕیت ڕەشە، کاتێک بەکاری دەهێنیت سوورە، کاتێک فڕێی دەدەیت خۆڵەمێشییە؟",
        "answers": ["خەڵووز", "خەڵوز", "پشکۆ", "coal", "xaluz"],
        "display_answer": "خەڵووز 🔥"
    },
    {
        "question": "چییە یەک خانووی سپییە، نە دەرگای هەیە نە پەنجەرە، لە ناویدا زەردێکی زێڕینە؟",
        "answers": ["هێلکە", "هێلکه", "هیلکە", "egg", "helka"],
        "display_answer": "هێلکە 🥚"
    },
    {
        "question": "چییە بە سەر پەنجەرەدا دەکەوێت، بەڵام هەرگیز ناچێتە ناو ژوورەوە؟",
        "answers": ["تیشکی خۆر", "سێبەر", "باران", "sunlight", "tishk"],
        "display_answer": "تیشکی خۆر ☀️"
    }
]

def parse_ai_json(raw_text: str):
    """وەرگرتنی JSON لە وەڵامی Groq/Gemini تەنانەت ئەگەر code fenceی تێدابێت."""
    if not raw_text:
        return None
    clean = re.sub(r"^```(?:json)?|```$", "", raw_text.strip(), flags=re.IGNORECASE).strip()
    start, end = clean.find("{"), clean.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(clean[start:end + 1])
    except Exception:
        return None

def request_game_ai_json(prompt: str, max_tokens: int = 300, temperature: float = 0.9):
    """دروستکردنی ناوەڕۆکی یاری بە Groq و، ئەگەر نەکرا، بە Gemini."""
    if GROQ_API_KEY:
        for model_name in groq_model_candidates():
            # هەندێک مۆدێل response_format وەرناگرن؛ بۆیە بە هەردوو شێوەکە هەوڵ دەدرێت.
            for use_json_mode in [True, False]:
                raw = request_groq_text(
                    [{"role": "user", "content": prompt}],
                    model_name,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    json_mode=use_json_mode,
                )
                parsed = parse_ai_json(raw)
                if parsed:
                    return parsed

    if GEMINI_API_KEY:
        for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
                for use_json_mode in [True, False]:
                    generation_config = {"maxOutputTokens": max_tokens, "temperature": temperature}
                    if use_json_mode:
                        generation_config["responseMimeType"] = "application/json"
                    body = {
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": generation_config
                    }
                    response = requests.post(url, json=body, timeout=20)
                    if response.status_code == 200:
                        candidates = response.json().get("candidates", [])
                        if candidates:
                            raw = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                            parsed = parse_ai_json(raw)
                            if parsed:
                                return parsed
                    elif response.status_code not in [400, 429]:
                        break
            except Exception as e:
                print(f"Game AI Gemini Notice ({model_name}): {e}")
    return None

def game_history_hint(used_items, limit: int = 80) -> str:
    recent = list(used_items or [])[-limit:]
    return "\n".join(f"- {item}" for item in recent) if recent else "- هیچ پرسیارێک هێشتا بەکارنەهاتووە"

def game_content_is_new(value: str, used_items, similarity_limit: float = 0.91) -> bool:
    """ڕێگری لە دووبارەبوونەوەی تەواو و پرسیاری زۆر هاوشێوە."""
    candidate = re.sub(r"\W+", "", str(value or "").lower(), flags=re.UNICODE)
    if not candidate:
        return False
    for old_value in used_items or []:
        old = re.sub(r"\W+", "", str(old_value or "").lower(), flags=re.UNICODE)
        if candidate == old:
            return False
        if len(candidate) > 12 and difflib.SequenceMatcher(None, candidate, old).ratio() >= similarity_limit:
            return False
    return True

GAME_EMOJI_PATTERN = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]+",
    flags=re.UNICODE
)

def strip_game_emojis(value: str) -> str:
    """لابردنی ئیمۆجی لە پرسیار و ڕێنمایی تا وەڵامەکە ئاشکرا نەکات."""
    clean = GAME_EMOJI_PATTERN.sub("", str(value or ""))
    return re.sub(r"\s+", " ", clean).strip()

GAME_DIFFICULTY_CONFIG = {
    "easy": ("ئاسان", "پرسیارەکە زۆر ڕوون و سادە بێت و وەڵامەکە بە ئاسانی بدۆزرێتەوە"),
    "medium": ("مامناوەند", "پرسیارەکە پێویستی بە کەمێک بیرکردنەوە هەبێت، بەڵام گومڕاکەر نەبێت"),
    "hard": ("قورس", "پرسیارەکە ورد و بیرخەرەوە بێت و وەڵامەکە بە ئاسانی ئاشکرا نەبێت"),
    "expert": ("زۆر قورس", "پرسیارەکە زۆر زیرەکانە، لۆژیکی و گومڕاکەر بێت و دۆزینەوەی وەڵامەکە زەحمەت بێت")
}

def reset_game_difficulty(chat_id: int, game_type: int):
    c_key = str(chat_id)
    sessions = state_data.setdefault("game_session_rounds", {})
    sessions.setdefault(c_key, {})[str(game_type)] = 0
    state_data.setdefault("game_session_players", {})[c_key] = []
    state_data.setdefault("game_session_scores", {})[c_key] = {}
    clear_game_generation_retry(chat_id, game_type)
    save_state()

def get_game_difficulty(chat_id: int, game_type: int):
    c_key = str(chat_id)
    rounds = int(state_data.get("game_session_rounds", {}).get(c_key, {}).get(str(game_type), 0))
    if rounds < 3:
        level = "easy"
    elif rounds < 7:
        level = "medium"
    elif rounds < 12:
        level = "hard"
    else:
        level = "expert"
    label, instruction = GAME_DIFFICULTY_CONFIG[level]
    return level, label, instruction, rounds + 1

def advance_game_difficulty(chat_id: int, game_type: int):
    c_key = str(chat_id)
    sessions = state_data.setdefault("game_session_rounds", {})
    game_rounds = sessions.setdefault(c_key, {})
    game_rounds[str(game_type)] = int(game_rounds.get(str(game_type), 0)) + 1

def choose_by_game_difficulty(candidates: list, difficulty: str, text_field: str):
    """کۆگای offlineیش بە پێی درێژی و ئاڵۆزیی ناوەڕۆک ئاستبەندی دەکات."""
    if not candidates:
        return None
    ordered = sorted(candidates, key=lambda item: len(strip_game_emojis(item.get(text_field, ""))))
    count = len(ordered)
    if difficulty == "easy":
        pool = ordered[:max(1, count // 3)]
    elif difficulty == "medium":
        start, end = count // 4, max(count // 4 + 1, (count * 3) // 4)
        pool = ordered[start:end]
    elif difficulty == "hard":
        pool = ordered[max(0, count // 2):]
    else:
        pool = ordered[max(0, (count * 3) // 4):]
    return random.choice(pool or ordered)

def generate_ai_kurdish_unscramble(used_words=None, difficulty: str = "easy") -> dict:
    """دروستکردنی وشەی نوێی تێکئاڵاو بە Groq/Gemini و ڕێگری لە دووبارەبوونەوە."""
    _, difficulty_instruction = GAME_DIFFICULTY_CONFIG.get(difficulty, GAME_DIFFICULTY_CONFIG["easy"])
    prompt = (
        "وەک پسپۆڕێکی زمانی کوردی، یەک وشەی ناوداری دروست و باوی کوردی سۆرانی دروست بکە؛ "
        "بابەتەکان بگۆڕە: کوردستان، سروشت، زانست، ئاژەڵ، میوە، شار، پیشە، کەلەپوور و شتومەک.\n"
        f"ئاستی ئەم خولە: {difficulty_instruction}.\n"
        "لە category و هەموو ڕێنماییەکاندا هیچ ئیمۆجییەک مەخە، چونکە ئیمۆجی نابێت وەڵامەکە ئاشکرا بکات.\n"
        "وشەکە نابێت لە لیستی بەکارهاتووی خوارەوە بێت و نابێت هاوشێوەی ئەوان بێت:\n"
        f"{game_history_hint(used_words)}\n"
        "تەنها JSON بگەڕێنەرەوە: "
        '{"word":"وشە", "scrambled":"پ • ی • ت", "category":"ڕێنماییەکی کورت", '
        '"answers":["وەڵامی سەرەکی","شێوازی نووسینی تر","لاتینی"]}'
    )
    data = request_game_ai_json(prompt, 260, 1.0)
    if not isinstance(data, dict):
        return None
    word = strip_game_emojis(data.get("word", ""))
    answers = data.get("answers")
    if not word or not isinstance(answers, list) or not answers or not game_content_is_new(word, used_words, 1.0):
        return None
    word_length = len([char for char in word if not char.isspace()])
    if ((difficulty == "easy" and word_length > 6)
            or (difficulty == "medium" and not 5 <= word_length <= 9)
            or (difficulty == "hard" and word_length < 7)
            or (difficulty == "expert" and word_length < 9)):
        return None
    data["answers"] = [strip_game_emojis(a) for a in answers if strip_game_emojis(a)]
    if word not in data["answers"]:
        data["answers"].insert(0, word)
    data["category"] = strip_game_emojis(data.get("category")) or "وشەیەکی کوردییە"
    letters = [char for char in word if not char.isspace()]
    if len(letters) > 1:
        original_letters = list(letters)
        for _ in range(5):
            random.shuffle(letters)
            if letters != original_letters:
                break
    data["scrambled"] = " • ".join(letters)
    return data

def generate_ai_kurdish_truefalse(used_questions=None, difficulty: str = "easy") -> dict:
    """دروستکردنی پرسیاری تازەی ڕاست/هەڵە بە Groq/Gemini."""
    _, difficulty_instruction = GAME_DIFFICULTY_CONFIG.get(difficulty, GAME_DIFFICULTY_CONFIG["easy"])
    prompt = (
        "پرسیارێکی نوێ، ڕوون و سەرنجڕاکێشی ڕاست یان هەڵە بە کوردی سۆرانی دروست بکە. "
        "لە نێوان زانست، مێژوو، جوگرافیا، تەکنەلۆجیا، سروشت، تەندروستیی گشتی و کەلتووردا بابەتەکە بگۆڕە. "
        f"ئاستی ئەم خولە: {difficulty_instruction}. "
        "لە پرسیارەکەدا هیچ ئیمۆجییەک مەخە و هیچ نیشانەیەک مەدە کە وەڵام ئاشکرا بکات. "
        "زانیارییەکە دەبێت دڵنیابێت و پرسیارەکە نابێت دووبارە یان هاوشێوەی لیستی خوارەوە بێت:\n"
        f"{game_history_hint(used_questions)}\n"
        "تەنها JSON بگەڕێنەرەوە: "
        '{"question":"پرسیار؟", "answer":"ڕاست یان هەڵە", "info":"ڕوونکردنەوەی کورتی دروست"}'
    )
    data = request_game_ai_json(prompt, 280, 0.95)
    if not isinstance(data, dict):
        return None
    question = strip_game_emojis(data.get("question", ""))
    raw_answer = str(data.get("answer", "")).strip()
    answer = "هەڵە" if "هەڵ" in raw_answer or raw_answer.lower() in ["false", "0"] else "ڕاست"
    if not question or not data.get("info") or not game_content_is_new(question, used_questions):
        return None
    data["question"] = question
    data["info"] = strip_game_emojis(data.get("info"))
    if not data["info"]:
        return None
    data["answer"] = answer
    data["aliases"] = (["ڕاست", "راست", "rast", "true", "t", "1"] if answer == "ڕاست"
                       else ["هەڵە", "هەلە", "hala", "false", "f", "0"])
    return data

def generate_ai_number_challenge(used_challenges=None, difficulty: str = "easy") -> dict:
    """دروستکردنی خولی تازەی یاریی ژمارە بە AI، بە مەودا و ڕێنماییی جیاواز."""
    _, difficulty_instruction = GAME_DIFFICULTY_CONFIG.get(difficulty, GAME_DIFFICULTY_CONFIG["easy"])
    range_instruction = {
        "easy": "مەوداکە نزیکەی 50 ژمارە بێت و clue زۆر یارمەتیدەر بێت",
        "medium": "مەوداکە نزیکەی 150 ژمارە بێت و clue مامناوەند بێت",
        "hard": "مەوداکە 300 تا 400 ژمارە بێت و clue تەنها ئاماژەیەکی بچووک بدات",
        "expert": "مەوداکە 500 تا 1000 ژمارە بێت و clue زۆر نهێنی و لۆژیکی بێت"
    }.get(difficulty, "مەوداکە نزیکەی 50 ژمارە بێت")
    prompt = (
        "خولێکی نوێی یاریی دۆزینەوەی ژمارە بە کوردی سۆرانی دروست بکە. "
        "min و max و ژمارەی نهێنی secret دیاری بکە؛ جیاوازی max و min لە 50 کەمتر و لە 500 زیاتر نەبێت. "
        "clue ڕێنماییەکی کورت و دروست بێت (وەک تاک/جووت، نزیکبوونەوە، یان تایبەتمەندییەکی ژمارەیی)، "
        f"ئاستی ئەم خولە: {difficulty_instruction}؛ {range_instruction}. "
        "بەڵام ژمارە نهێنییەکە ئاشکرا مەکە و لە clueدا هیچ ئیمۆجییەک مەخە. خولەکە نابێت دووبارەی ئەمانە بێت:\n"
        f"{game_history_hint(used_challenges)}\n"
        "تەنها JSON بگەڕێنەرەوە: "
        '{"min":1,"max":200,"secret":137,"clue":"ڕێنماییەکی کورت"}'
    )
    data = request_game_ai_json(prompt, 240, 0.95)
    if not isinstance(data, dict):
        return None
    try:
        minimum = int(data.get("min"))
        maximum = int(data.get("max"))
        secret = int(data.get("secret"))
    except (TypeError, ValueError):
        return None
    clue = strip_game_emojis(data.get("clue", ""))
    if minimum >= maximum or maximum - minimum < 20 or maximum - minimum > 1000:
        return None
    if secret < minimum or secret > maximum or str(secret) in clue:
        return None
    challenge_key = f"{minimum}:{maximum}:{secret}:{clue}"
    if not game_content_is_new(challenge_key, used_challenges, 1.0):
        return None
    return {"min": minimum, "max": maximum, "secret": secret, "clue": clue, "key": challenge_key}

def generate_ai_kurdish_riddle(is_comedy: bool = False, used_questions=None, used_answers=None, difficulty: str = "easy") -> dict:
    """دروستکردنی مەتەڵی نوێ و بێکۆتایی بە Groq/Gemini و مێژووی بێ-دووبارەبوونەوە."""
    _, difficulty_instruction = GAME_DIFFICULTY_CONFIG.get(difficulty, GAME_DIFFICULTY_CONFIG["easy"])
    topic_hint = ("مەتەڵێکی کۆمیدی و پێکەنیناوی پاک" if is_comedy
                  else "مەتەڵێکی فیکری، کەلتووری، لۆژیکی یان زانستی")
    prompt = (
        f"وەک مەتەڵسازێکی کورد، {topic_hint} بە زمانی شیرینی کوردی سۆرانی دروست بکە. "
        "مەتەڵەکە دەبێت وەڵامێکی ڕوون و دادپەروەرانەی هەبێت. "
        f"ئاستی ئەم خولە: {difficulty_instruction}. "
        "لە دەقی مەتەڵەکەدا هیچ ئیمۆجییەک مەخە و هیچ نیشانەیەک مەدە کە وەڵامەکە ئاشکرا بکات. "
        "نابێت دووبارە یان زۆر هاوشێوەی هیچ مەتەڵێکی لیستی خوارەوە بێت:\n"
        f"{game_history_hint(used_questions)}\n"
        "هەروەها وەڵامی سەرەکی نابێت هیچ یەکێک لەم وەڵامە بەکارهاتووانە بێت:\n"
        f"{game_history_hint(used_answers, 50)}\n"
        "تەنها JSON بگەڕێنەرەوە: "
        '{"question":"مەتەڵ", "answers":["وەڵامی سەرەکی","شێوازی تر","لاتینی"], '
        '"display_answer":"وەڵامی تەواو"}'
    )
    data = request_game_ai_json(prompt, 320, 1.0)
    if not isinstance(data, dict):
        return None
    question = strip_game_emojis(data.get("question", ""))
    answers = data.get("answers")
    normalized_question = re.sub(r"\W+", "", question.lower(), flags=re.UNICODE)
    placeholder_questions = {
        "مەتەڵ", "riddle", "question", "پرسیار", "نمونەی مەتەڵ", "مەتەڵی تازە"
    }
    if normalized_question in placeholder_questions or len(question) < 10:
        return None
    if (not question or not isinstance(answers, list) or not answers
            or not data.get("display_answer") or not game_content_is_new(question, used_questions)):
        return None
    data["question"] = question
    data["display_answer"] = strip_game_emojis(data.get("display_answer"))
    data["answers"] = [strip_game_emojis(a) for a in answers if strip_game_emojis(a)]
    normalized_answers = {
        re.sub(r"\W+", "", str(answer).lower(), flags=re.UNICODE)
        for answer in data["answers"]
    }
    invalid_answers = {
        re.sub(r"\W+", "", value.lower(), flags=re.UNICODE)
        for value in {"وەڵامی سەرەکی", "شێوازی تر", "لاتینی", "answer", "نمونە"}
    }
    if (not data["answers"] or not data["display_answer"]
            or normalized_answers & invalid_answers
            or re.sub(r"\W+", "", data["display_answer"].lower(), flags=re.UNICODE) in {"وەڵامی تەواو", "answer"}):
        return None
    return data

# هەوڵدانەوەی خۆکار ئەگەر هەردوو خزمەتگوزاریی AI کاتییەک وەڵام نەدەن
game_generation_retries = {}

def clear_game_generation_retry(chat_id: int, game_type: int):
    game_generation_retries.pop(f"{chat_id}_{game_type}", None)

def cancel_game_generation_retries(chat_id: int):
    prefix = f"{chat_id}_"
    for retry_key in list(game_generation_retries):
        if retry_key.startswith(prefix):
            game_generation_retries.pop(retry_key, None)

def schedule_game_generation_retry(chat_id: int, game_type: int, thread_id: int = 0):
    """بە backoffـی ئارام هەوڵ دەداتەوە تا AI خولێکی تازە دروست دەکات."""
    retry_key = f"{chat_id}_{game_type}"
    previous = game_generation_retries.get(retry_key, {})
    attempt = int(previous.get("attempt", 0)) + 1
    token = f"{time.time()}_{random.random()}"
    delay = min(10 * attempt, 120)
    game_generation_retries[retry_key] = {"attempt": attempt, "token": token}

    def retry_later():
        time.sleep(delay)
        current = game_generation_retries.get(retry_key, {})
        if current.get("token") != token:
            return
        send_next_game_round(chat_id, game_type, thread_id)

    threading.Thread(target=retry_later, daemon=True).start()
    return attempt, delay

def wait_for_fresh_ai_round(chat_id: int, game_type: int, thread_id: int = 0):
    """یاری ناوەستێنێت؛ بە بێ دووبارەکردنەوە خۆکار چاوەڕێی AI دەکات."""
    c_key = str(chat_id)
    if c_key in state_data.get("active_game", {}):
        state_data["active_game"][c_key]["generating"] = True
        save_state()
    attempt, delay = schedule_game_generation_retry(chat_id, game_type, thread_id)
    if attempt == 1:
        send_message(
            chat_id,
            f"⏳ AI خەریکی دروستکردنی خولێکی تەواو تازەیە؛ خۆکار دوای {delay} چرکە دووبارە هەوڵ دەداتەوە و یاری ناوەستێت 🌸🤖",
            0,
            thread_id
        )

def send_next_game_round(chat_id: int, game_type: int, thread_id: int = 0):
    """بەڕێوەبردنی خولەکانی ٤ جۆری یارییە بەکۆمەڵەکان بە سیستەمی زیرەکی بێ-دووبارەبوونەوە و ژیریی دەستکرد"""
    c_key = str(chat_id)
    if "active_game" not in state_data:
        state_data["active_game"] = {}
    difficulty, difficulty_label, _, round_number = get_game_difficulty(chat_id, game_type)
        
    if game_type == 1:
        # 🧩 ۱. یاریی وشە تێکئاڵاوەکان (Unscramble) - تێکەڵەی ئۆفلاین و دروستکردنی AI
        if "used_unscramble" not in state_data:
            state_data["used_unscramble"] = {}
        if c_key not in state_data["used_unscramble"]:
            state_data["used_unscramble"][c_key] = []
            
        used_set = set(state_data["used_unscramble"][c_key])
        
        item = None
        # AI سەرەکییە؛ ئەگەر پرسیاری دووبارە دروست کرد جارێکی تر هەوڵ دەدات
        for _ in range(2):
            ai_item = generate_ai_kurdish_unscramble(state_data["used_unscramble"][c_key], difficulty)
            if ai_item and game_content_is_new(ai_item.get("word"), used_set, 1.0):
                item = ai_item
                break
                
        if not item:
            candidates = [
                it for it in KURDISH_UNSCRAMBLE_WORDS
                if game_content_is_new(it["word"], used_set, 1.0)
            ]
            if candidates:
                item = choose_by_game_difficulty(candidates, difficulty, "word")

        if not item:
            wait_for_fresh_ai_round(chat_id, game_type, thread_id)
            return

        clear_game_generation_retry(chat_id, game_type)
        state_data["used_unscramble"][c_key].append(item["word"])
        safe_category = html.escape(strip_game_emojis(item.get("category", "")))
        
        msg = (
            "🧩 <b>یاریی وشە تێکئاڵاوەکان (Game 1):</b>\n\n"
            f"❓ پیتەکان ڕێکبخە بۆ دۆزینەوەی وشەکە:\n"
            f"<b>[ {item['scrambled']} ]</b>\n\n"
            f"<b>ئاست:</b> {difficulty_label} | <b>خول:</b> {round_number}\n"
            f"🏷️ <b>ڕێنمایی:</b> {safe_category}\n\n"
            f"💡 <b>بۆ وەڵامدانەوە، ڕیپڵای (Reply) ئەم پەیامە بکە!</b> 🏆✨\n\n"
            f"<i>(بۆ ڕاگرتنی یاری ئەدمین دەتوانێت بنووسێت: <code>/stop</code>)</i>"
        )
        res = send_message(chat_id, msg, 0, thread_id)
        g_mid = res.get("result", {}).get("message_id", 0) if res else 0
        
        state_data["active_game"][c_key] = {
            "game_type": 1,
            "word": item["word"],
            "answers": [a.lower() for a in item["answers"]],
            "display": item["word"],
            "difficulty": difficulty,
            "msg_id": g_mid,
            "time": time.time()
        }
        advance_game_difficulty(chat_id, game_type)
        save_state()
        
    elif game_type == 2:
        # ⚡ ۲. یاریی ڕاستە یان هەڵەیە (True or False) - تێکەڵەی ئۆفلاین و دروستکردنی AI
        if "used_truefalse" not in state_data:
            state_data["used_truefalse"] = {}
        if c_key not in state_data["used_truefalse"]:
            state_data["used_truefalse"][c_key] = []
            
        used_set = set(state_data["used_truefalse"][c_key])
        
        item = None
        for _ in range(2):
            ai_tf = generate_ai_kurdish_truefalse(state_data["used_truefalse"][c_key], difficulty)
            if ai_tf and game_content_is_new(ai_tf.get("question"), used_set):
                item = ai_tf
                break
                
        if not item:
            candidates = [
                it for it in KURDISH_TRUE_FALSE
                if game_content_is_new(it["question"], used_set)
            ]
            if candidates:
                item = choose_by_game_difficulty(candidates, difficulty, "question")

        if not item:
            wait_for_fresh_ai_round(chat_id, game_type, thread_id)
            return

        clear_game_generation_retry(chat_id, game_type)
        safe_question = strip_game_emojis(item["question"])
        state_data["used_truefalse"][c_key].append(safe_question)
        
        msg = (
            "⚡ <b>یاریی ڕاستە یان هەڵەیە؟ (Game 2):</b>\n\n"
            f"<b>ئاست:</b> {difficulty_label} | <b>خول:</b> {round_number}\n\n"
            f"❓ <b>{html.escape(safe_question)}</b>\n\n"
            f"💡 <b>بۆ وەڵامدانەوە، ڕیپڵای (Reply) ئەم پەیامە بکە و بنووسە ڕاست یان هەڵە!</b> 🏆✨\n\n"
            f"<i>(بۆ ڕاگرتنی یاری ئەدمین دەتوانێت بنووسێت: <code>/stop</code>)</i>"
        )
        res = send_message(chat_id, msg, 0, thread_id)
        g_mid = res.get("result", {}).get("message_id", 0) if res else 0
        
        state_data["active_game"][c_key] = {
            "game_type": 2,
            "question": safe_question,
            "correct_ans": item["answer"],
            "aliases": [a.lower() for a in item["aliases"]],
            "info": strip_game_emojis(item["info"]),
            "difficulty": difficulty,
            "msg_id": g_mid,
            "time": time.time()
        }
        advance_game_difficulty(chat_id, game_type)
        save_state()

    elif game_type == 3:
        # 🎯 ۳. یاریی ژمارەی نهێنی بە مەودا و ڕێنماییی نوێی AI
        if "used_number_challenges" not in state_data:
            state_data["used_number_challenges"] = {}
        if c_key not in state_data["used_number_challenges"]:
            state_data["used_number_challenges"][c_key] = []

        used_challenges = state_data["used_number_challenges"][c_key]
        challenge = None
        for _ in range(2):
            ai_challenge = generate_ai_number_challenge(used_challenges, difficulty)
            if ai_challenge and game_content_is_new(ai_challenge.get("key"), used_challenges, 1.0):
                challenge = ai_challenge
                break

        # fallbackـێکی بێسنووری ناوخۆیی؛ تەنها ئەگەر AI کاتییەک وەڵام نەدات
        if not challenge:
            round_no = len(used_challenges) + 1
            span_by_difficulty = {"easy": 50, "medium": 150, "hard": 350, "expert": 800}
            minimum = 1 + ((round_no - 1) // 100) * 100
            maximum = minimum + span_by_difficulty[difficulty]
            for _ in range(100):
                secret = random.randint(minimum, maximum)
                if difficulty == "easy":
                    clue = f"لە {max(minimum, secret - 5)} گەورەتر و لە {min(maximum, secret + 5)} بچووکترە"
                elif difficulty == "medium":
                    clue = "ژمارەکە جووتە" if secret % 2 == 0 else "ژمارەکە تاکە"
                elif difficulty == "hard":
                    clue = f"کۆی ژمارەکانی ناوی ژمارەکە {sum(int(digit) for digit in str(secret))} دەبێت"
                else:
                    clue = "ڕێنماییی زیادە نییە؛ بە لۆژیک و هەوڵ دۆزییەوە"
                challenge_key = f"round-{round_no}:{minimum}:{maximum}:{secret}:{clue}"
                if game_content_is_new(challenge_key, used_challenges, 1.0):
                    challenge = {
                        "min": minimum,
                        "max": maximum,
                        "secret": secret,
                        "clue": clue,
                        "key": challenge_key
                    }
                    break

        if not challenge:
            wait_for_fresh_ai_round(chat_id, game_type, thread_id)
            return

        clear_game_generation_retry(chat_id, game_type)
        state_data["used_number_challenges"][c_key].append(challenge["key"])
        minimum = challenge["min"]
        maximum = challenge["max"]
        secret = challenge["secret"]
        clue = challenge["clue"]
        msg = (
            "🎯 <b>یاریی دۆزینەوەی ژمارەی نهێنی (Game 3):</b>\n\n"
            f"<b>ئاست:</b> {difficulty_label} | <b>خول:</b> {round_number}\n\n"
            f"🔢 AI ژمارەیەکی نهێنی لە نێوان <b>({minimum} تا {maximum})</b> هەڵبژاردووە!\n"
            f"🧠 <b>ڕێنمایی:</b> {html.escape(strip_game_emojis(clue))}\n\n"
            "💡 <b>بۆ وەڵامدانەوە، ڕیپڵای (Reply) ئەم پەیامە بکە و ژمارەکەت بنووسە!</b> 🏆✨\n\n"
            "<i>(بۆ ڕاگرتنی یاری ئەدمین دەتوانێت بنووسێت: <code>/stop</code>)</i>"
        )
        res = send_message(chat_id, msg, 0, thread_id)
        g_mid = res.get("result", {}).get("message_id", 0) if res else 0
        
        state_data["active_game"][c_key] = {
            "game_type": 3,
            "secret": secret,
            "min": minimum,
            "max": maximum,
            "challenge_key": challenge["key"],
            "difficulty": difficulty,
            "attempts": 0,
            "msg_id": g_mid,
            "time": time.time()
        }
        advance_game_difficulty(chat_id, game_type)
        save_state()

    elif game_type == 4:
        # ❓ ٤. یاریی مەتەڵی کوردی (Riddles) - تێکەڵەی سەدان مەتەڵی ئۆفلاین و دروستکردنی بێسنووری AI
        if "used_quizzes" not in state_data:
            state_data["used_quizzes"] = {}
        if c_key not in state_data["used_quizzes"]:
            state_data["used_quizzes"][c_key] = []
        if "used_quiz_answers" not in state_data:
            state_data["used_quiz_answers"] = {}
        if c_key not in state_data["used_quiz_answers"]:
            state_data["used_quiz_answers"][c_key] = []

        used_set = set(state_data["used_quizzes"][c_key])
        used_answer_set = set(state_data["used_quiz_answers"][c_key])
        
        q = None
        is_comedy_turn = len(used_set) % 2 == 1
        for _ in range(2):
            ai_q = generate_ai_kurdish_riddle(
                is_comedy=is_comedy_turn,
                used_questions=state_data["used_quizzes"][c_key],
                used_answers=state_data["used_quiz_answers"][c_key],
                difficulty=difficulty
            )
            ai_primary_answer = str((ai_q or {}).get("answers", [""])[0]).strip().lower()
            if (ai_q and game_content_is_new(ai_q.get("question"), used_set)
                    and game_content_is_new(ai_primary_answer, used_answer_set, 1.0)):
                q = ai_q
                break
                
        if not q:
            candidates = [
                item for item in KURDISH_QUIZZES
                if game_content_is_new(item["question"], used_set)
                and game_content_is_new(str(item["answers"][0]).lower(), used_answer_set, 1.0)
            ]
            if candidates:
                q = choose_by_game_difficulty(candidates, difficulty, "question")

        if not q:
            wait_for_fresh_ai_round(chat_id, game_type, thread_id)
            return

        clear_game_generation_retry(chat_id, game_type)
        safe_question = strip_game_emojis(q["question"])
        # پاراستنی کۆتایی: هیچ placeholder ـێک نابێت بگاتە گروپ، تەنانەت
        # ئەگەر لە داتای کۆن یان وەڵامی نادروستی AI ـەوە هاتبێت.
        safe_question_key = re.sub(r"\W+", "", safe_question.lower(), flags=re.UNICODE)
        if len(safe_question) < 10 or safe_question_key in {"مەتەڵ", "riddle", "question", "پرسیار"}:
            wait_for_fresh_ai_round(chat_id, game_type, thread_id)
            return
        state_data["used_quizzes"][c_key].append(safe_question)
        state_data["used_quiz_answers"][c_key].append(str(q["answers"][0]).strip().lower())
        
        msg = (
            "❓ <b>مەتەڵی کوردی (Game 4):</b>\n\n"
            f"<b>ئاست:</b> {difficulty_label} | <b>خول:</b> {round_number}\n\n"
            f"❓ <b>{html.escape(safe_question)}</b>\n\n"
            f"💡 <b>بۆ وەڵامدانەوە، ڕیپڵای (Reply) ئەم پەیامە بکە و وەڵامەکەت بنووسە!</b> 🏆✨\n\n"
            f"<i>(بۆ ڕاگرتنی یاری ئەدمین دەتوانێت بنووسێت: <code>/stop</code>)</i>"
        )
        res = send_message(chat_id, msg, 0, thread_id)
        g_mid = res.get("result", {}).get("message_id", 0) if res else 0
        
        state_data["active_game"][c_key] = {
            "game_type": 4,
            "question": safe_question,
            "answers": [a.lower() for a in q["answers"]],
            "display_answer": strip_game_emojis(q["display_answer"]),
            "difficulty": difficulty,
            "msg_id": g_mid,
            "time": time.time()
        }
        advance_game_difficulty(chat_id, game_type)
        save_state()

def register_group(chat_id: int):
    if "groups" not in state_data:
        state_data["groups"] = []
    if chat_id not in state_data["groups"]:
        state_data["groups"].append(chat_id)
        save_state()

def clean_ai_text(text: str) -> str:
    if not text:
        return ""
    # لابردنی تاگی بیرکردنەوە لە مۆدێلە ڕیزنینگەکان
    text = re.sub(r'(?is)<think>.*?</think>', '', text)
    clean = re.sub(r'(?im)^\s*@?[a-zA-Z0-9_]+:\s*', '', text)
    clean = re.sub(r'(?im)^\s*(system note|translation note|note|translation)\s*[::-].*$', '', clean)
    if re.search(r'[\u0900-\u097F]', clean):
        return ""
    return clean.strip()

ai_conversation_memory = {}

AI_CONVERSATION_RULES = """
Answer the user's actual question directly in natural, everyday Sorani Kurdish. Talk like a smart,
kind friend, not like a professor or a formal customer-service bot. Use the previous conversation only
when it helps. Do not respond with generic phrases such as 'I am here to help' when the user asked a
real question. If the question is unclear, ask one short clarifying question. Prefer familiar Sorani
words and short sentences; never translate word-for-word from English or Arabic. In casual conversation,
you may add a small tasteful joke and 1-3 fitting emojis. Do not force jokes into serious subjects.
Be accurate, warm and respectful. Never invent facts.
"""

def get_ai_conversation(chat_id: int, user_id: int):
    return list(ai_conversation_memory.get(f"{chat_id}_{user_id}", []))[-8:]

def remember_ai_conversation(chat_id: int, user_id: int, question: str, answer: str):
    key = f"{chat_id}_{user_id}"
    history = ai_conversation_memory.setdefault(key, [])
    history.extend([
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer}
    ])
    ai_conversation_memory[key] = history[-8:]

def get_smart_reply(text: str):
    lower = text.strip().lower()
    for entry in SMART_REPLIES:
        for p in entry["patterns"]:
            if p in lower:
                return random.choice(entry["replies"])
    return None

def get_ai_reply(chat_id: int, user_id: int, question: str) -> str:
    history = get_ai_conversation(chat_id, user_id)
    system_prompt = f"{AI_SYSTEM_PROMPT}\n\n{AI_CONVERSATION_RULES}"

    # 🌟 ١. AIی سەرەکی: Groq، لەگەڵ مێژووی کورتەی گفتوگۆ
    if GROQ_API_KEY:
        messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": question}]
        for g_model in groq_model_candidates():
            answer = request_groq_text(messages, g_model, max_tokens=800, temperature=0.75)
            answer = clean_ai_text(answer)
            if answer:
                remember_ai_conversation(chat_id, user_id, question, answer)
                return answer

    # 🌟 ۲. پشتیوانی دووەم: Gemini، بە هەمان مێژووی گفتوگۆ
    if GEMINI_API_KEY:
        for gem_model in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{gem_model}:generateContent?key={GEMINI_API_KEY}"
                contents = [
                    {"role": "model" if item["role"] == "assistant" else "user", "parts": [{"text": item["content"]}]}
                    for item in history
                ]
                contents.append({"role": "user", "parts": [{"text": question}]})
                body = {
                    "contents": contents,
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "generationConfig": {"maxOutputTokens": 800, "temperature": 0.75}
                }
                r = requests.post(url, json=body, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        answer = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        answer = clean_ai_text(answer)
                        if answer:
                            remember_ai_conversation(chat_id, user_id, question, answer)
                            return answer
                elif r.status_code == 429:
                    continue
            except Exception as e:
                print(f"Gemini Error ({gem_model}): {e}")

    # تەنها کاتێک AI بەردەست نەبوو، وەڵامی ئامادە بەکاربهێنە
    smart = get_smart_reply(question)
    if smart:
        return smart

    fallbacks = [
        "گیان لە خزمەتتدام! چۆن یارمەتیت بدەم؟ 🌸😊",
        "فەرموو گوڵم، بە دڵ گوێم لێتە! ✨❤️",
        "سەرچاوم ئازیزم، هەموو کات لە خزمەتتاندام! 💐🥰",
        "گیانەکەم هەر پرسیار یان داواکارییەکت هەبێت لێرەم! 💖🌸"
    ]
    return random.choice(fallbacks)

def contains_bad_word(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    for p in BAD_WORDS_LIST:
        if re.search(r'\b' + re.escape(p) + r'\b' if p.isalnum() else re.escape(p), lower):
            return True
    for phrase in BAD_PHRASES_LIST:
        if re.search(phrase, lower):
            return True
    return False

def download_telegram_file(file_id: str):
    """Download a file from Telegram servers and return (raw_bytes, mime_type)."""
    try:
        telegram_media_status["stage"] = "داواکاری getFile"
        res = tg_call("getFile", {"file_id": file_id})
        if not res or not res.get("ok"):
            description = (res or {}).get("description") or "پەیوەندی Telegram سەرکەوتوو نەبوو"
            telegram_media_status["stage"] = f"getFile: {description}"
            return None, "image/jpeg"
        file_path = res.get("result", {}).get("file_path")
        if not file_path:
            telegram_media_status["stage"] = "getFile: file_path نەگەڕایەوە"
            return None, "image/jpeg"
        ext = file_path.split(".")[-1].lower() if "." in file_path else "jpg"
        mime = "image/jpeg"
        if ext in ["png"]:
            mime = "image/png"
        elif ext in ["webp"]:
            mime = "image/webp"
        elif ext in ["gif"]:
            mime = "image/gif"
        elif ext in ["mp4", "m4v"]:
            mime = "video/mp4"
        elif ext in ["webm"]:
            mime = "video/webm"
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        telegram_media_status["stage"] = "داگرتنی فایل لە Telegram"
        r = telegram_session.get(url, timeout=(15, 30))
        if r.status_code == 200:
            if not r.content:
                telegram_media_status["stage"] = "Telegram فایلێکی بەتاڵی گەڕاندەوە"
                return None, mime
            telegram_media_status["stage"] = f"داگرتن سەرکەوتوو بوو ({len(r.content)} bytes, {mime})"
            return r.content, mime
        telegram_media_status["stage"] = f"داگرتنی Telegram: HTTP {r.status_code}"
    except Exception as exc:
        # هەڵەکە کلیل/تۆکنی بۆت لە کۆنسۆڵدا پیشان نەدات.
        telegram_media_status["stage"] = f"داگرتنی Telegram: {type(exc).__name__}"
        print("Download file error: Telegram file server is temporarily unavailable")
    return None, "image/jpeg"

def get_local_nsfw_detector():
    """NudeNet تەنها یەک جار بار بکە؛ None واتە پەکەج/مۆدێل بەردەست نییە."""
    global local_nsfw_detector, local_nsfw_detector_failed
    if local_nsfw_detector is not None:
        return local_nsfw_detector
    if local_nsfw_detector_failed:
        return None

    with local_nsfw_detector_lock:
        if local_nsfw_detector is not None:
            return local_nsfw_detector
        if local_nsfw_detector_failed:
            return None
        try:
            from nudenet import NudeDetector
            local_nsfw_detector = NudeDetector()
            print("Local NSFW detector loaded: NudeNet")
        except Exception as exc:
            local_nsfw_detector_failed = True
            print(f"Local NSFW detector unavailable ({type(exc).__name__}); install requirements.txt")
            return None
    return local_nsfw_detector

def check_nsfw_with_local_model(img_bytes: bytes, mime_type: str):
    """True=نەشیاو، False=پاک، None=نەتوانرا پشکنین بکرێت."""
    if not img_bytes or not (mime_type or "").startswith("image/"):
        return None

    detector = get_local_nsfw_detector()
    if detector is None:
        return None

    try:
        # NudeDetector مۆدێلەکە thread-safe نییە؛ پشکنینەکان یەک بە یەک بکە.
        with local_nsfw_detector_lock:
            detections = detector.detect(img_bytes) or []
        for item in detections:
            label = str(item.get("class", "")).upper()
            score = float(item.get("score", 0.0) or 0.0)
            threshold = LOCAL_NSFW_THRESHOLDS.get(label)
            if threshold is not None and score >= threshold:
                print(f"Local NSFW detector matched {label} ({score:.2f})")
                return True
        return False
    except Exception as exc:
        # fail-open: لە کاتی هەڵەدا میدیای پاک بە گومان مەسڕەوە.
        print(f"Local NSFW scan skipped ({type(exc).__name__})")
        return None

def check_nsfw_with_google_vision(img_bytes: bytes, mime_type: str):
    """Google Cloud Vision SafeSearch: True=نەشیاو، False=پاک، None=هەڵە/بەردەست نییە."""
    api_key = live_config_secret(
        "googleVisionApiKey",
        "GOOGLE_VISION_API_KEY",
        "googleVisionAPIKey",
        "visionApiKey",
    )
    if not api_key:
        google_vision_status["result"] = "کلیلی Vision لە ~/gardnya-bot/config.json دانەنراوە"
        return None
    if not img_bytes:
        return None
    if not (mime_type or "").startswith("image/"):
        google_vision_status["result"] = f"جۆری فایل بۆ Vision ناگونجێت: {mime_type or 'unknown'}"
        return None

    body = {
        "requests": [{
            "image": {"content": base64.b64encode(img_bytes).decode("ascii")},
            "features": [{"type": "SAFE_SEARCH_DETECTION", "maxResults": 1}],
        }]
    }
    try:
        google_vision_status["last_check"] = time.time()
        response = telegram_session.post(
            "https://vision.googleapis.com/v1/images:annotate",
            params={"key": api_key},
            json=body,
            timeout=(15, 35),
        )
        google_vision_status["http_status"] = response.status_code
        if response.status_code != 200:
            google_vision_status["result"] = f"HTTP {response.status_code}"
            print(f"Google Vision SafeSearch unavailable: HTTP {response.status_code}")
            return None

        responses = response.json().get("responses", [])
        if not responses:
            return None
        result = responses[0]
        if result.get("error"):
            error_code = result["error"].get("code", "unknown")
            google_vision_status["result"] = f"API error {error_code}"
            print(f"Google Vision SafeSearch error: {error_code}")
            return None

        safe = result.get("safeSearchAnnotation", {})
        likelihood = {
            "UNKNOWN": 0,
            "VERY_UNLIKELY": 1,
            "UNLIKELY": 2,
            "POSSIBLE": 3,
            "LIKELY": 4,
            "VERY_LIKELY": 5,
        }
        adult_score = likelihood.get(str(safe.get("adult", "UNKNOWN")), 0)
        racy_score = likelihood.get(str(safe.get("racy", "UNKNOWN")), 0)
        # پاراستنی توند: adult لە POSSIBLE بەسەرەوە، یان racy لە LIKELY بەسەرەوە.
        # ئەمە هەندێک false-positive زیاد دەکات، بەڵام میدیای گوماناوی کەمتر تێدەپەڕێت.
        blocked = adult_score >= likelihood["POSSIBLE"] or racy_score >= likelihood["LIKELY"]
        google_vision_status["result"] = "نەشیاو دۆزرایەوە" if blocked else "میدیا پاک بوو"
        print(
            "Google Vision SafeSearch: "
            f"adult={safe.get('adult', 'UNKNOWN')}, racy={safe.get('racy', 'UNKNOWN')}, "
            f"blocked={blocked}"
        )
        return blocked
    except Exception as exc:
        google_vision_status["result"] = type(exc).__name__
        print(f"Google Vision SafeSearch skipped ({type(exc).__name__})")
        return None

def video_frame_for_vision(video_bytes: bytes, mime_type: str):
    """یەک وێنە لە video sticker/GIF ـەکە وەربگرە تا Google Vision بتوانێت بیبینێت."""
    if not video_bytes:
        return None, mime_type
    if (mime_type or "").startswith("image/"):
        return video_bytes, mime_type

    # Cloud Vision ڤیدیۆی webm/mp4 ناوەردەگرێت. ffmpeg ـی سیستەم تەنها یەک frame
    # دەردەهێنێت؛ هیچ فایلێکی جێگیر یان پەکەجی Pythonی قورس دروست ناکات.
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        google_vision_status["result"] = "video/webm ـە؛ ffmpeg لە ڕاژە بەردەست نییە"
        return None, mime_type

    suffix = ".webm" if "webm" in (mime_type or "") else ".mp4"
    try:
        with tempfile.TemporaryDirectory(prefix="gardnya_vision_") as temp_dir:
            source = Path(temp_dir) / f"media{suffix}"
            frame = Path(temp_dir) / "frame.jpg"
            source.write_bytes(video_bytes)
            process = subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                 "-frames:v", "1", "-vf", "scale=960:-2", str(frame)],
                capture_output=True,
                timeout=20,
                check=False,
            )
            if process.returncode != 0 or not frame.exists() or frame.stat().st_size < 300:
                google_vision_status["result"] = "نەتوانرا وێنە لە ڤیدیۆکە وەربگیرێت"
                return None, mime_type
            telegram_media_status["stage"] = "وێنەیەک لە ستیکەری ڤیدیۆیی وەرگیرا"
            return frame.read_bytes(), "image/jpeg"
    except Exception as exc:
        google_vision_status["result"] = f"frame extraction: {type(exc).__name__}"
        return None, mime_type

def check_nsfw_with_ai_vision(file_id: str):
    """گەڕاندنەوەی True (نەشیاو)، False (پاک)، یان None (نەتوانرا پشکنین بکرێت)."""
    img_bytes, mime_type = download_telegram_file(file_id)
    if not img_bytes or len(img_bytes) < 300:
        google_vision_status["result"] = telegram_media_status.get("stage", "فایل دانەگیرا")
        return None

    img_bytes, mime_type = video_frame_for_vision(img_bytes, mime_type)
    if not img_bytes:
        return None

    # سەرەتا مۆدێلی خۆجێیی و بێ‌بەرامبەر بەکاربهێنە.
    local_result = check_nsfw_with_local_model(img_bytes, mime_type)
    if local_result is True:
        return True

    # Google Cloud Vision SafeSearch هیچ پەکەجی قورسێکی خۆجێیی پێویست نییە و
    # بۆ PythonAnywhere ـی quota کەم گونجاوە.
    google_result = check_nsfw_with_google_vision(img_bytes, mime_type)
    if google_result is not None:
        return google_result

    if local_result is False and not GEMINI_API_KEY:
        return False

    # Gemini تەنها ئەگەر خاوەن بۆت خۆی کلیلێکی بەردەستی دانابێت، وەک پشتیوانی دووەم.
    if GEMINI_API_KEY:
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        for gem_model in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{gem_model}:generateContent?key={GEMINI_API_KEY}"
                body = {
                    "contents": [{
                        "parts": [
                            {"text": "Carefully inspect this sticker or image. Does it contain nudity, pornography, sexual acts, erotic poses, lingerie, exposed breasts, buttocks, genitalia, sexualized anime/hentai, or explicit sexual content? Answer strictly YES or NO."},
                            {"inline_data": {"mime_type": mime_type, "data": b64}}
                        ]
                    }],
                    "generationConfig": {
                        "maxOutputTokens": 100,
                        "temperature": 0.0
                    },
                    "safetySettings": [
                        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_LOW_AND_ABOVE"}
                    ]
                }
                r = requests.post(url, json=body, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    # 1. Blocked by Google Safety filters -> 100% NSFW
                    pf = data.get("promptFeedback", {})
                    if pf.get("blockReason"):
                        print(f"🔞 Gemini Safety Filter BLOCKED image: {pf.get('blockReason')}")
                        return True
                    candidates = data.get("candidates", [])
                    if candidates:
                        cand = candidates[0]
                        if cand.get("finishReason") == "SAFETY":
                            print("🔞 Gemini finishReason is SAFETY violation")
                            return True
                        # 2. Check safety ratings
                        safety = cand.get("safetyRatings", [])
                        for s in safety:
                            if s.get("category") == "HARM_CATEGORY_SEXUALLY_EXPLICIT":
                                if s.get("probability") in ["HIGH", "MEDIUM"]:
                                    print(f"🔞 Gemini safety probability: {s.get('probability')}")
                                    return True
                        # 3. Check text output
                        parts = cand.get("content", {}).get("parts", [])
                        for part in parts:
                            txt = (part.get("text") or "").strip().upper()
                            if "YES" in txt:
                                print(f"🔞 Gemini Vision answered YES (NSFW detected): {txt}")
                                return True
                    print(f"✅ Gemini Vision ({gem_model}): Content is clean")
                    return False
                elif r.status_code == 429:
                    print(f"Gemini {gem_model} 429, switching to next...")
                    continue
                else:
                    print(f"Gemini Vision {gem_model} status: {r.status_code}")
            except Exception as e:
                print(f"Gemini Vision error ({gem_model}): {e}")

    # لە کاتی هەڵەی ڕاژە، ئەنجامی پاک مەگەڕێنەوە؛ بانگەوازکەر دەتوانێت
    # بە thumbnail یان فایلی جێگرەوە جارێکی تر هەوڵ بدات.
    return None

def is_nsfw_sticker(sticker_obj: dict) -> bool:
    if not sticker_obj:
        return False
    set_name = (sticker_obj.get("set_name") or "").lower()
    emoji = sticker_obj.get("emoji") or ""
    
    # نیشانەکانی دەق و ناوی ستیکەر تەنها یارمەتیدەرن؛ بەڵام AI Vision هەر جار بانگ دەکرێت
    metadata_nsfw = "🔞" in emoji

    nsfw_keywords = [
        "sex", "sexy", "porn", "xxx", "nude", "naked", "nsfw", "18+", "18plus", "adult",
        "erotic", "hentai", "boobs", "dick", "pussy", "tits", "vagina", "brazzers",
        "onlyfans", "xvideo", "ass", "milf", "blowjob", "fuck", "horny", "bitch",
        "lewd", "ecchi", "taboo", "fetish", "bdsm", "kinky", "butt", "sensual", "strip",
        "masturbat", "orgasm", "penis", "cum", "cock", "cunt", "slut", "whore", "boob", "tit", "breast",
        "hot_girl", "hot_babe", "hotgirl", "hotbabe", "bikini", "lingerie",
        "سێکس", "پۆرن", "قن", "قوز", "کیر", "حیز", "گواو", "سۆزانی", "ڕووت", "قەحبە",
        "گەواد", "سێکسی", "شەهوەت", "جماع", "نيك", "طيز", "زب", "كس", "شرموطة", "بورن", "سكس"
    ]
    
    for kw in nsfw_keywords:
        if kw in set_name:
            metadata_nsfw = True
            break
    
    # 🧠 AI Vision fallback: check actual sticker image content
    thumb = sticker_obj.get("thumbnail") or sticker_obj.get("thumb") or {}
    # ستیکەری جێگیر: خودی فایل (نەک وێنەی بچووک) پشکنین بکرێت.
    # ستیکەری animated/video: thumbnail وێنەیەکی گونجاوە بۆ Vision ـە.
    is_motion_sticker = sticker_obj.get("is_animated") or sticker_obj.get("is_video")
    primary_id = (thumb.get("file_id") if is_motion_sticker else sticker_obj.get("file_id")) or ""
    fallback_id = (sticker_obj.get("file_id") if is_motion_sticker else thumb.get("file_id")) or ""
    vision_result = check_nsfw_with_ai_vision(primary_id) if primary_id else None
    if vision_result is None and fallback_id and fallback_id != primary_id:
        vision_result = check_nsfw_with_ai_vision(fallback_id)
    vision_nsfw = vision_result is True
    if vision_nsfw:
        print(f"🔞 AI Vision detected NSFW sticker: set={set_name}")

    return metadata_nsfw or vision_nsfw

def is_nsfw_photo(msg: dict) -> bool:
    """Check if a photo message contains NSFW content using AI Vision."""
    photos = msg.get("photo")
    if not photos:
        return False
    # Telegram قەبارەکان لە بچووکەوە بۆ گەورە دەنێرێت؛ وێنەی گەورە وردترە.
    file_id = photos[-1].get("file_id") or ""
    if file_id and check_nsfw_with_ai_vision(file_id):
        return True
    return False

def is_nsfw_animation_or_media(msg: dict, text: str) -> bool:
    if contains_bad_word(text):
        return True
    
    # Check caption
    caption = (msg.get("caption") or "").lower()
    if contains_bad_word(caption):
        return True

    anim = msg.get("animation") or msg.get("document") or {}
    file_name = (anim.get("file_name") or "").lower()
    
    nsfw_keywords = [
        "sex", "sexy", "porn", "xxx", "nude", "naked", "nsfw", "18+", "adult",
        "erotic", "hentai", "boobs", "dick", "pussy", "tits", "vagina", "brazzers",
        "onlyfans", "xvideo", "ass", "milf", "blowjob", "fuck", "horny", "bitch",
        "سێکس", "پۆرن", "سێکسی", "قحبة", "طيز", "زب", "كس", "شرموطة", "بورن", "سكس"
    ]
    for kw in nsfw_keywords:
        if kw in file_name or kw in caption:
            return True
    
    # 🧠 بۆ GIF، خودی فایل پشکنین بکرێت؛ تەنها لە کاتی هەڵە thumbnail بەکاربێت.
    # ئەمە وێنەی بچووک و نادیاریی Telegram ناگرێتە سەرەتا.
    thumb = anim.get("thumbnail") or anim.get("thumb") or {}
    file_id = anim.get("file_id") or ""
    vision_result = check_nsfw_with_ai_vision(file_id) if file_id else None
    if vision_result is None:
        thumb_id = thumb.get("file_id") or ""
        if thumb_id and thumb_id != file_id:
            vision_result = check_nsfw_with_ai_vision(thumb_id)
    if vision_result is True:
        print(f"🔞 AI Vision detected NSFW animation/GIF")
        return True
            
    return False

def security_media_file_candidates(msg: dict) -> list:
    """File ID ـی وێنەی گونجاو بۆ Vision لە ستیکەر/GIF/وێنە/ڤیدیۆ کۆبکەرەوە."""
    candidates = []
    sticker = msg.get("sticker") or {}
    if sticker:
        thumb = sticker.get("thumbnail") or sticker.get("thumb") or {}
        if sticker.get("is_animated") or sticker.get("is_video"):
            candidates.extend([thumb.get("file_id"), sticker.get("file_id")])
        else:
            candidates.extend([sticker.get("file_id"), thumb.get("file_id")])

    photos = msg.get("photo") or []
    if photos:
        candidates.append(photos[-1].get("file_id"))

    media = msg.get("animation") or msg.get("video") or msg.get("video_note") or msg.get("document") or {}
    if media:
        thumb = media.get("thumbnail") or media.get("thumb") or {}
        # Google Vision وێنە وەردەگرێت؛ بۆ GIF/ڤیدیۆ thumbnail سەرەتا.
        candidates.extend([thumb.get("file_id"), media.get("file_id")])

    return list(dict.fromkeys(file_id for file_id in candidates if file_id))

def contains_link_or_spam(msg: dict, text: str) -> bool:
    if text and re.search(r'(?i)\bhttps?://|\bt\.me/|\btelegram\.me/|\bwww\.|@[a-zA-Z0-9_]{4,}', text):
        return True
    if msg.get("entities"):
        for e in msg["entities"]:
            if e.get("type") in ["url", "text_link", "mention"]:
                return True
    if msg.get("caption_entities"):
        for e in msg["caption_entities"]:
            if e.get("type") in ["url", "text_link", "mention"]:
                return True
    if msg.get("reply_markup"):
        return True
    return False

def record_group_member(chat_id: int, user_obj: dict):
    """تۆمارکردنی ئەندامانی چالاکی گروپ بۆ سیستەمی تاگکردن"""
    if not user_obj or user_obj.get("is_bot"):
        return
    u_id = user_obj.get("id")
    if not u_id or u_id == chat_id:
        return
    c_key = str(chat_id)
    if "members" not in state_data:
        state_data["members"] = {}
    if c_key not in state_data["members"]:
        state_data["members"][c_key] = {}
    
    first = user_obj.get("first_name") or "هاوڕێ"
    username = user_obj.get("username")
    state_data["members"][c_key][str(u_id)] = {
        "id": u_id,
        "first_name": first,
        "username": username,
        "last_seen": int(time.time())
    }
    if "user_names" not in state_data:
        state_data["user_names"] = {}
    state_data["user_names"][str(u_id)] = first
    save_state()

def send_voice_chat_notification(chat_id: int, thread_id: int = 0):
    """ناردنی تەنها یەک نامەی ئاگاداری کاتی دەستپێکردنی کاڵ بە بێ تاگکردنی کەس"""
    tag_text = (
        "🎙️ <b>پەیوەندی دەنگی (Voice Chat) دەستی پێکرد! 🌸✨</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📢 هاوڕێیانی ئازیز، کاڵی گروپ دەستی پێکرد! وەرن بەشداربن لەگەڵمان بۆ کاتێکی زۆر خۆش و بەجۆش ☕🎧💖\n\n"
        "⏳ <i>(ئەم پەیامە پاش ۳۰ خولەک بە خۆکاری دەسڕدرێتەوە)</i>"
    )
    res = send_message(chat_id, tag_text, 0, thread_id)
    mid = res.get("result", {}).get("message_id") if res and isinstance(res, dict) else 0
    if mid:
        def auto_del_single(cid, m_id):
            time.sleep(1800)
            try:
                delete_message(cid, m_id)
            except Exception:
                pass
        threading.Thread(target=auto_del_single, args=(chat_id, mid), daemon=True).start()
        print(f"🎙️ Sent single voice chat notification in {chat_id}. Auto-delete in 30m.")

def tag_all_members_batches(chat_id: int, custom_text: str = "", thread_id: int = 0):
    """تاگکردنی میمبەرەکان بە گروپی ٥ کەسی تەنها کاتێک ئەدمین بنووسێت @all"""
    c_key = str(chat_id)
    known_members = {}
    if "members" in state_data and c_key in state_data["members"]:
        known_members = dict(state_data["members"][c_key])
    
    # دۆزینەوەی تەواوی ئەدمینەکان بۆ ئەوەی تاگ نەکرێن
    admin_ids = set()
    admins_res = tg_call("getChatAdministrators", {"chat_id": chat_id})
    if admins_res and admins_res.get("ok"):
        for admin in admins_res.get("result", []):
            u = admin.get("user", {})
            if u:
                admin_ids.add(u["id"])
    if BOT_ID:
        admin_ids.add(BOT_ID)

    # فلتەرکردن: تەنها ئەو میمبەرانەی کە ئەدمین نین
    non_admin_members = [
        udata for udata in known_members.values()
        if udata.get("id") not in admin_ids
    ]

    sent_msg_ids = []
    
    header_text = custom_text.strip() if custom_text.strip() else "🎙️ وەرن بەشداربن لە چات و کاڵ 🌸✨"
    if "@all" not in header_text.lower():
        header_text = f"{header_text} @all"

    if not non_admin_members:
        tag_text = (
            f"<b>{header_text}</b>\n\n"
            "📢 هاوڕێیانی ئازیز، وەرن بەشداربن لەگەڵمان بۆ کاتێکی زۆر خۆش و بەجۆش ☕🎧💖\n\n"
            "⏳ <i>(ئەم پەیامە پاش ۳۰ خولەک بە خۆکاری دەسڕدرێتەوە)</i>"
        )
        res = send_message(chat_id, tag_text, 0, thread_id)
        if res and isinstance(res, dict) and res.get("result", {}).get("message_id"):
            sent_msg_ids.append(res["result"]["message_id"])
    else:
        mentions = []
        for udata in non_admin_members:
            first = html.escape(udata.get("first_name", "هاوڕێ"))
            uid = udata.get("id")
            mentions.append(f'<a href="tg://user?id={uid}">{first}</a>')

        # دابەشکردنی تاگەکان بۆ ٥ ئەندام لە هەر پەیامێکدا
        chunks = [mentions[i:i + 5] for i in range(0, len(mentions), 5)]
        for chunk in chunks:
            tags_str = " , ".join(chunk)
            msg_content = f"<b>{header_text}</b>\n{tags_str}"
            res = send_message(chat_id, msg_content, 0, thread_id)
            if res and isinstance(res, dict) and res.get("result", {}).get("message_id"):
                sent_msg_ids.append(res["result"]["message_id"])
            time.sleep(1.5)

    # سڕینەوەی خۆکاری نامەی تاگ دوای ۳۰ خولەک (1800 چرکە)
    if sent_msg_ids:
        def auto_delete_tags(cid, mids):
            time.sleep(1800)
            for mid in mids:
                try:
                    delete_message(cid, mid)
                except Exception:
                    pass
        threading.Thread(target=auto_delete_tags, args=(chat_id, sent_msg_ids), daemon=True).start()
        print(f"🎙️ Auto-tagged {len(non_admin_members)} members in 5-user batches in {chat_id}. Auto-delete in 30m.")

def get_sticker_comment(sticker_obj: dict) -> str:
    if not sticker_obj:
        return ""
    emoji = sticker_obj.get("emoji") or ""
    set_name = (sticker_obj.get("set_name") or "").lower()
    
    # 🐱 Cats (پشیلە)
    if any(c in emoji for c in ["🐱", "😸", "😻", "😽", "🐈", "🐾"]) or "cat" in set_name or "pishila" in set_name:
        return random.choice([
            "واو چەند پشیلەیەکی کیوت و نازدارە! 😻🐾🌸",
            "چەند جوان و شیرینە ئەم پشیلەیە دەستت خۆش بێت! 🐱✨❤️",
            "ئای چەند کیوت و جوانە، خۆم فیدای بم! 🐾🥰💐"
        ])
    
    # 🐶 Dogs (سەگ)
    if any(c in emoji for c in ["🐶", "🐕", "🦮", "🐩", "🐕‍🦺"]) or "dog" in set_name:
        return random.choice([
            "واو چەند سەگێکی کیوت و دڵسۆزە! 🐶❤️✨",
            "دەستخۆش زۆر شیرین و نازدارە! 🐕🌸🥰"
        ])
        
    # 😂 Laughing / Funny (پێکەنین)
    if any(c in emoji for c in ["😂", "🤣", "😹", "😆", "😅"]):
        return random.choice([
            "ههههه هەمیشە دەمتان بە پێکەنین و شاد بێت گوڵم! 😂🌸❤️",
            "هههه زۆر بەلەزەت و پێکەنیناوی بوو، هەمیشە بە کەیف بن! 🤣🎉✨",
            "خوایە هەمیشە دڵتان پڕ لە پێکەنین و خۆشی بێت ههههه! 😊🥰💖"
        ])
        
    # ❤️ Love / Hearts (خۆشەویستی)
    if any(c in emoji for c in ["❤️", "💖", "💕", "💞", "💓", "😍", "🥰", "😘"]):
        return random.choice([
            "فیدای ئەو دڵە پاک و پڕ لە خۆشەویستییە بم گوڵم! ❤️🥰✨",
            "چەند جوانە! هەمیشە پڕ بن لە خۆشەویستی و دڵخۆشی 💖🌸💐",
            "قوربانی ئەو پەیام و ستیکەرە جوانەت بم! 🌸❤️🤗"
        ])

    # 🌸 Flowers (گوڵ)
    if any(c in emoji for c in ["🌸", "🌹", "🌺", "🌻", "💐", "🌷"]):
        return random.choice([
            "گوڵ بۆ گوڵ! چەند دڵڕفێن و جوانە دەستت خۆش بێت 🌸💐✨",
            "گوڵبەخش بیت گوڵم! زۆر زۆر جوانە 🌺❤️🥰"
        ])
        
    # ☕ Coffee / Tea (چای و قاوە)
    if any(c in emoji for c in ["☕", "🫖", "🍵"]):
        return random.choice([
            "نۆشی گیانتان بێت! عافیەتبێت قاوە و چایەکی بەتام ☕😋✨",
            "عافیەتی گیانت بێت گوڵم! کاتێکی زۆر خۆش و ئارام 🫖🌸💖"
        ])

    # 🔥 Cool / Thumbs Up / Fire (شاز و بەهێز)
    if any(c in emoji for c in ["👍", "🔥", "💪", "😎", "👑", "⚡"]):
        return random.choice([
            "دەستخۆش زۆر کەشخە و ناوازەیە! هەمیشە لە لوتکە بن 💪😎🔥",
            "شازە براکەم! هەر بژین بە بەرزی و سەرکەوتوویی 👑✨🚀"
        ])

    # 🥺 Sad / Cry (خەمبار)
    if any(c in emoji for c in ["😢", "😭", "🥺", "😞", "💔"]):
        return random.choice([
            "خەمت نەبێت گیانەکەم، هەموو شتێک بە باشترین شێوە چاک دەبێت! دڵت ئارام بێت 🥺🌸❤️",
            "هەمیشە دەمت بە خەندە بێت و هیچ خەمێک لە دڵتدا نەمێنێت گیان! 💖🤗"
        ])

    # 🍰 Food / Drinks (خواردن)
    if any(c in emoji for c in ["🍕", "🍔", "🎂", "🍫", "🍰", "🍩", "🍦", "🍎"]):
        return random.choice([
            "بە عافیەتی گیانتان بێت! زۆر بەلەزەت و شیرین دیارە 😋🍰🎉",
            "نۆشی گیانت بێت گوڵم! هەمیشە سفرەتان ئاوەدان بێت 🍕✨🌸"
        ])

    # Default friendly cute response
    return random.choice([
        "ستیکەرێکی زۆر جوان و کیوتە! دەستت خۆش گوڵم 🌸✨🥰",
        "واو چەند نازدار و تایبەتە! هەمیشە شاد بن 😊💖💐",
        "زۆر شازە! هەمیشە دڵخۆش و دەم بە خەندە بن 🌺✨🎉"
    ])

def parse_duration_minutes(text: str) -> int:
    if not text:
        return 60
    m = re.match(r'^(\d+)([mhd])?$', text.strip().lower())
    if not m:
        return 60
    val = int(m.group(1))
    unit = m.group(2)
    if unit == 'h':
        return val * 60
    elif unit == 'd':
        return val * 1440
    return val

def format_12h_kurdistan(time_str: str) -> str:
    """کاتی ۲۴ دەگۆڕێت بۆ کاتی ۱۲ بە دیاریکردنی (بەیانی، نیوەڕۆ، عەسر، ئێوارە، شەو)"""
    try:
        hh, mm = map(int, time_str.split(":"))
        if 5 <= hh < 12:
            period = "بەیانی ☀️"
        elif 12 <= hh < 15:
            period = "نیوەڕۆ 🌞"
        elif 15 <= hh < 18:
            period = "عەسر 🌤️"
        elif 18 <= hh < 21:
            period = "ئێوارە 🌇"
        else:
            period = "شەو 🌙"
        
        hh_12 = hh % 12
        if hh_12 == 0:
            hh_12 = 12
        
        return f"{hh_12:02d}:{mm:02d}ی {period}"
    except Exception:
        return time_str

def build_health_report(chat_id: int) -> str:
    """ڕاپۆرتێکی پارێزراو لە بەش و مۆڵەتە گرنگەکان؛ هیچ کلیلێک پیشان نادات."""
    checks = []
    bot_member = tg_call("getChatMember", {"chat_id": chat_id, "user_id": BOT_ID}) if BOT_ID else None
    member_info = bot_member.get("result", {}) if bot_member and bot_member.get("ok") else {}
    bot_status = member_info.get("status", "unknown")
    is_group_admin = bot_status in ["administrator", "creator"]
    is_creator = bot_status == "creator"
    ai_ready = bool(GROQ_API_KEY or GEMINI_API_KEY)

    can_send_welcome = bool(BOT_ID) and bot_status not in ["left", "kicked", "unknown"]
    if bot_status == "restricted":
        can_send_welcome = can_send_welcome and bool(member_info.get("can_send_messages"))
    checks.append(("پەیوەندی Telegram", bool(BOT_ID)))
    checks.append(("کارتی بەخێرهاتن", can_send_welcome))
    checks.append(("بۆت ئەدمینی گروپە", is_group_admin))
    checks.append(("مۆڵەتی سڕینەوەی میدیا", is_creator or bool(member_info.get("can_delete_messages"))))
    checks.append(("مۆڵەتی بێدەنگ/باند", is_creator or bool(member_info.get("can_restrict_members"))))
    local_vision_ready = importlib.util.find_spec("nudenet") is not None
    security_ai_ready = bool(GOOGLE_VISION_API_KEY or GEMINI_API_KEY or local_vision_ready)
    checks.append(("AIی سکوریتی ستیکەر/GIF/فۆروارد", security_ai_ready))
    checks.append(("AIی گفتوگۆ", ai_ready))
    checks.append(("یارییەکان بە AI و بێ دووبارە", ai_ready))
    checks.append(("مەتەڵەکان بە AI و بێ دووبارە", ai_ready))
    checks.append(("کاتژمێرە یەکسانەکان", config.get("enableMirrorHours", True)))
    checks.append(("کاتی بانگەکان", config.get("enablePrayerTimes", True)))
    scheduler_last_loop = scheduler_status.get("last_loop", 0.0)
    scheduler_age = time.time() - scheduler_last_loop if scheduler_last_loop else None
    scheduler_ok = scheduler_age is not None and scheduler_age < 90
    checks.append(("چاودێری کاتژمێر", scheduler_ok))
    checks.append(("گروپەکانی پەخشی کات", bool(state_data.get("groups", []))))

    channel_identifier = state_data.get("force_channel", {}).get(str(chat_id))
    if channel_identifier:
        channel_res = tg_call("getChat", {"chat_id": channel_identifier})
        channel_member = tg_call("getChatMember", {"chat_id": channel_identifier, "user_id": BOT_ID}) if BOT_ID else None
        channel_status = channel_member.get("result", {}).get("status") if channel_member and channel_member.get("ok") else None
        channel_ok = bool(channel_res and channel_res.get("ok") and channel_status in ["administrator", "creator"])
        checks.append(("چەناڵی جۆین و ئەدمینبوونی بۆت", channel_ok))
        channel_text = html.escape(str(channel_identifier))
    else:
        channel_text = "دانەنراوە (ئاساییە)"

    lines = ["🩺 <b>پشکنینی تەواوی بۆتی گاردنیا:</b>", ""]
    for label, ok in checks:
        lines.append(f"{'✅' if ok else '❌'} <b>{label}</b>")
    lines.extend([
        "",
        f"🔎 <b>دوایین پشکنینی Google Vision:</b> {html.escape(google_vision_status.get('result', 'هێشتا پشکنین نەکراوە'))}",
        f"🕒 <b>کاتی بۆت:</b> {datetime.datetime.now(KURDISTAN_UTC_OFFSET).strftime('%Y-%m-%d %H:%M:%S')} (UTC+3)",
        f"📡 <b>دوایین چاودێری:</b> {('کەمتر لە %d چرکە' % int(scheduler_age)) if scheduler_age is not None else 'هێشتا دەستپێنەکردووە'}",
        f"📤 <b>دوایین پەخش:</b> {html.escape(scheduler_status.get('last_delivery') or 'هیچ پەخشێک تۆمار نەکراوە')}",
        f"⚠️ <b>دوایین هەڵەی scheduler:</b> {html.escape(scheduler_status.get('last_error') or 'نییە')}",
        f"📢 <b>چەناڵ:</b> {channel_text}",
        "",
        "ℹ️ ئەگەر مۆڵەتی سڕینەوە یان بێدەنگکردن ❌ بوو، لە Admin Permissions ـی گروپ چالاکی بکە.",
        "🛡️ میدیای ئەدمین و ئۆنەر بە داواکاری پارێزراوە و ناسڕدرێتەوە؛ تاقیکردنەوە بە ئەکاونتی نا-ئەدمین بکە.",
    ])
    if not ai_ready:
        lines.append("🔑 بۆ چالاککردنی سێ بەشی AI، کلیلی Groq لە <code>groqApiKey</code> ـی config.json دابنێ.")
    return "\n".join(lines)

# ═══════════════════════════════════════════════════════════════════════════════
#  تایبەتمەندی پەخشی کاتژمێرە یەکسانەکان و کاتی بانگەکان (Background Scheduler)
# ═══════════════════════════════════════════════════════════════════════════════

scheduler_status = {
    "started_at": 0.0,
    "last_loop": 0.0,
    "last_delivery": "",
    "last_error": "",
}

def background_scheduler():
    """هەموو چەند چرکەیەک پشکنین دەکات بۆ کاتژمێرە یەکسانەکان و کاتی بانگەکان بە کاتی تەواو دروست"""
    print("⏰ Background Clock & Prayer Scheduler Started!")
    scheduler_status["started_at"] = time.time()
    last_sent_minute = ""
    delivered_schedule_groups = {}

    while True:
        try:
            now = datetime.datetime.now(KURDISTAN_UTC_OFFSET)
            current_time = now.strftime("%H:%M")
            scheduler_status["last_loop"] = time.time()

            if current_time != last_sent_minute:
                # ١. کاتژمێرە یەکسانەکان (Mirror Hours بە کاتی ۱۰۰٪ یەکسان و قۆناغەکانی ڕۆژ)
                if config.get("enableMirrorHours", True) and current_time in MIRROR_HOURS_CONFIG:
                    # گەرەنتی کردنی ئەوەی پەیامەکە لە ناوەڕاستی ئەو خولەکەدا دەگات بۆ نەهێشتنی جیاوازی کاتی مۆبایلەکان
                    if now.second < 15:
                        time.sleep(15 - now.second)
                    
                    item = MIRROR_HOURS_CONFIG[current_time]
                    time_label = item["time_label"]
                    quote = item["quote"]
                    msg_text = (
                        f"✨ <b>کاتژمێری یەکسان: {time_label}</b> 💫\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"❝ {quote} ❞"
                    )
                    group_ids = list(dict.fromkeys(state_data.get("groups", [])))
                    schedule_key = f"{now.date().isoformat()}:{current_time}"
                    delivered = delivered_schedule_groups.setdefault(schedule_key, set())
                    for gid in group_ids:
                        if gid in delivered:
                            continue
                        result = send_message(gid, msg_text)
                        if result and result.get("ok"):
                            delivered.add(gid)
                    if not group_ids or all(gid in delivered for gid in group_ids):
                        print(f"✨ Broadcasted mirror hour {current_time} ({time_label}) to groups")
                        scheduler_status["last_delivery"] = f"{schedule_key} mirror {len(delivered)}/{len(group_ids)}"
                        scheduler_status["last_error"] = ""
                        last_sent_minute = current_time
                    else:
                        print(f"⏳ Mirror hour {current_time} delivery incomplete; retrying")

                # ۲. کاتی بانگەکان و زیکر (Prayer Times)
                elif config.get("enablePrayerTimes", True) and current_time in PRAYER_SCHEDULE:
                    if now.second < 10:
                        time.sleep(10 - now.second)

                    p_info = PRAYER_SCHEDULE[current_time]
                    p_msg = (
                        f"🕌 **کاتی {p_info['name']} بە کاتی کوردستان** 🕋\n\n"
                        f"📿 **زیکر و نزای ئەم کاتە:**\n{p_info['zikr']}\n\n"
                        f"اللَّهُمَّ صَلِّ عَلَىٰ مُحَمَّدٍ وَعَلَىٰ آلِ مُحَمَّدٍ 🌸"
                    )
                    group_ids = list(dict.fromkeys(state_data.get("groups", [])))
                    schedule_key = f"{now.date().isoformat()}:{current_time}"
                    delivered = delivered_schedule_groups.setdefault(schedule_key, set())
                    for gid in group_ids:
                        if gid in delivered:
                            continue
                        result = send_message(gid, p_msg)
                        if result and result.get("ok"):
                            delivered.add(gid)
                    if not group_ids or all(gid in delivered for gid in group_ids):
                        print(f"🕌 Broadcasted prayer time {current_time} ({p_info['name']}) to groups")
                        scheduler_status["last_delivery"] = f"{schedule_key} prayer {len(delivered)}/{len(group_ids)}"
                        scheduler_status["last_error"] = ""
                        last_sent_minute = current_time
                    else:
                        print(f"⏳ Prayer time {current_time} delivery incomplete; retrying")

            # کۆگای ڕۆژانە زۆر مەگۆرێت ئەگەر بۆت ماوەی زۆر بەردەوام بێت.
            if len(delivered_schedule_groups) > 80:
                for old_key in list(delivered_schedule_groups)[:-40]:
                    delivered_schedule_groups.pop(old_key, None)
            time.sleep(10)
        except Exception as e:
            print("Scheduler Exception:", e)
            scheduler_status["last_error"] = type(e).__name__
            time.sleep(15)

# ═══════════════════════════════════════════════════════════════════════════════
#  فرمانە سەرەکییەکان (Admin & User Commands)
# ═══════════════════════════════════════════════════════════════════════════════

def handle_command(msg: dict, text: str):
    chat = msg["chat"]
    chat_id = chat["id"]
    msg_id = msg.get("message_id", 0)
    thread_id = msg.get("message_thread_id", 0)
    from_user = msg.get("from") or msg.get("sender_chat") or {"id": chat_id, "title": chat.get("title", "Admin")}
    user_id = from_user.get("id", chat_id)
    display_name = get_display_name(from_user)
    is_user_admin = chat.get("type") in ["group", "supergroup"] and is_message_from_admin(chat_id, user_id, msg)

    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].split("@")[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    # 🛡️ لە گروپەکاندا: تەواوی فرمانەکان (یاری، مەتەڵ، ئاسایش، ڕێکخستن) تەنها لە ئەدمین وەردەگیرێن
    if chat.get("type") in ["group", "supergroup"]:
        if not is_user_admin:
            print(f"🚫 Ignored command '{cmd}' from non-admin member: {display_name} ({user_id})")
            return

    if cmd in ["/start", "/setup"]:
        if chat.get("type") in ["group", "supergroup"]:
            register_group(chat_id)
            send_message(chat_id, f"🌸 سڵاو {display_name} گیان! من بوتی گاردنیام 🤖❤️\n\nئەم گروپە بە سەرکەوتوویی تۆمارکرا بۆ پەخشی خۆکاری کاتژمێرە یەکسانەکان، کاتی بانگەکان، پاراستنی ئاسایش و وەڵامدانەوەی AI! ✨🥰", msg_id, thread_id)
        else:
            send_message(chat_id, f"🌸 سڵاو {display_name} گیان! من بوتی گاردنیام 🤖❤️\n\nئەرکی من پاراستنی ئاسایشی گروپ، پێشوازی لە ئەندامان، پەخشی کاتژمێرە یەکسانەکان، کاتی بانگەکان و وەڵامدانەوەی پرسیارەکانە بە ژیریی دەستکرد! ✨🥰", msg_id, thread_id)
        return
    elif cmd == "/help":
        help_text = (
            "📋 <b>لیستی تەواوی فرمانەکانی بوتی گاردنیا (تەنها بۆ ئەدمین):</b>\n\n"
            "🎮 <b>یاری و مەتەڵ:</b>\n"
            "• <code>/game</code> یان <code>/quiz</code> - دانانی مەتەڵی نوێ بۆ گروپ 🎮\n"
            "• <code>/answer</code> - ئاشکراکردنی وەڵامی دروستی مەتەڵەکە 💡\n"
            "• <code>/points</code> - پیشاندانی خاڵەکانی یاری و ڕیزبەندی 🏆\n\n"
            "🛡️ <b>پاراستن و بەڕێوەبردن:</b>\n"
            "• <code>/tagall</code> - بانگهێشت و تاگکردنی هەموو ئەندامان (بۆ کاتی کاڵ) 🎙️\n"
            "• <code>/lock</code> - قوفڵکردنی گروپ (بۆ کاتی خەو) 🔒\n"
            "• <code>/unlock</code> - کردنەوەی قوفڵی گروپ 🔓\n"
            "• <code>/purge 20</code> - پاککردنەوەی چات بە کۆمەڵ 🧹\n"
            "• <code>/del</code> - سڕینەوەی پەیامی دیاریکراو (بە ڕیپڵای) 🗑️\n"
            "• <code>/warn</code> - ئاگادارکردنەوەی بەکارهێنەر (بە ڕیپڵای)\n"
            "• <code>/warnings</code> - پیشاندانی ژمارەی ئاگادارییەکان\n"
            "• <code>/clearwarnings</code> - سڕینەوەی ئاگادارییەکان\n"
            "• <code>/mute 10m</code> - بێدەنگکردن بۆ ماوەیەک (10m, 1h, 1d)\n"
            "• <code>/unmute</code> - لادانی بێدەنگی لەسەر بەکارهێنەر\n"
            "• <code>/ban</code> - باندکردنی بەکارهێنەر لە گروپ\n"
            "• <code>/unban &lt;user_id&gt;</code> - لادانی باند بە پێدانی ئایدی\n"
            "• <code>/setrules &lt;دەق&gt;</code> - دانانی یاساکانی گروپ 🌸\n"
            "• <code>/health</code> - پشکنینی AI، سکوریتی و مۆڵەتەکانی بۆت 🩺\n"
            "• <code>/visiontest</code> - بە ڕیپلای لە میدیا، تاقیکردنەوەی Google Vision 🔎"
        )
        send_message(chat_id, help_text, msg_id, thread_id)
        return
    elif cmd == "/id":
        send_message(chat_id, f"🆔 ئایدی ئەم چاتە: <code>{chat_id}</code>\n👤 ئایدی تۆ: <code>{user_id}</code> ✨", msg_id, thread_id)
        return
    elif cmd in ["/health", "/check", "/status"]:
        if chat.get("type") not in ["group", "supergroup"]:
            send_message(chat_id, "ℹ️ ئەم پشکنینە لە ناو گروپ بەکاربهێنە تا مۆڵەتەکان بزانرێن.", msg_id, thread_id)
        else:
            send_message(chat_id, build_health_report(chat_id), msg_id, thread_id)
        return
    elif cmd in ["/visiontest", "/securitytest", "/scanmedia"]:
        replied = msg.get("reply_to_message") or {}
        file_ids = security_media_file_candidates(replied)
        if not file_ids:
            send_message(
                chat_id,
                "ℹ️ لەسەر ستیکەر، GIF، وێنە یان ڤیدیۆیەک ڕیپلای بکە و <code>/visiontest</code> بنووسە.",
                msg_id,
                thread_id,
            )
            return

        scan_results = []
        for file_id in file_ids:
            result = check_nsfw_with_ai_vision(file_id)
            scan_results.append(result)
            if result is True:
                break

        if True in scan_results:
            test_text = "🔞 <b>AI ئەم میدیایەی بە ناوەڕۆکی سێکسی/نەشیاو ناساند.</b>"
        elif False in scan_results:
            test_text = "✅ <b>AI ئەم میدیایەی بە پاک ناساند.</b>"
        else:
            last_result = html.escape(google_vision_status.get("result", "هەڵەی نادیار"))
            test_text = f"❌ <b>Google Vision نەتوانی پشکنین بکات:</b> {last_result}"
            if not live_config_secret("googleVisionApiKey", "GOOGLE_VISION_API_KEY", "googleVisionAPIKey", "visionApiKey"):
                test_text += "\n\n💡 کلیلی خۆت تەنها لە <code>~/gardnya-bot/config.json</code> بە ناوی <code>googleVisionApiKey</code> دابنێ."
        send_message(chat_id, test_text, msg_id, thread_id)
        return
    elif cmd in ["/setowner", "/owner"]:
        state_data["owner_id"] = user_id
        save_state()
        send_message(chat_id, f"👑 <b>{display_name} گیان!</b> تۆ بە سەرکەوتوویی وەک ئۆنەری فەرمی بۆت دیاریکرایت.\n\nلە ئێستاوە هەر کەسێک لە شەخسی (PV) نامە بنێرێت، دەستبەجێ ڕاپۆرت و کۆپییەکی نامەکەت بۆ فۆروارد دەکرێت! 🌸✨🥰", msg_id, thread_id)
        return
    elif cmd in ["/tagall", "/calltag", "/tag", "/all", "@all"]:
        tag_all_members_batches(chat_id, arg, thread_id)
        return
    elif cmd == "/rules":
        c_key = str(chat_id)
        rules = state_data.get("rules", {}).get(c_key)
        if rules:
            send_message(chat_id, f"📜 <b>یاساکانی گروپ:</b>\n\n{rules} 🌸", msg_id, thread_id)
        else:
            send_message(chat_id, "ℹ️ یاسایەکی تایبەت بۆ ئەم گروپە دانەنراوە ✨", msg_id, thread_id)
        return
    elif cmd in ["/game", "/games"]:
        games_menu = (
            "🎮 <b>لیستی یارییە بەکۆمەڵەکانی گاردنیا:</b>\n\n"
            "• <code>/game1</code> - یاریی وشە تێکئاڵاوەکان 🧩\n"
            "• <code>/game2</code> - یاریی ڕاستە یان هەڵەیە؟ ⚡\n"
            "• <code>/game3</code> - یاریی دۆزینەوەی ژمارەی نهێنی 🎯\n"
            "• <code>/game4</code> یان <code>/quiz</code> - یاریی مەتەڵی کوردی ❓\n\n"
            "🏆 <code>/points</code> - بینینی خاڵ و ڕیزبەندیی پاڵەوانان\n"
            "💡 <code>/answer</code> - ئاشکراکردنی وەڵامی خولی ئێستا\n"
            "🛑 <code>/stop</code> - ڕاگرتنی هەر یارییەکی چالاک 🌸"
        )
        send_message(chat_id, games_menu, msg_id, thread_id)
        return
    elif cmd in ["/game1", "/unscramble", "/wsha"]:
        reset_game_difficulty(chat_id, 1)
        send_next_game_round(chat_id, 1, thread_id)
        return
    elif cmd in ["/game2", "/truefalse", "/rast"]:
        reset_game_difficulty(chat_id, 2)
        send_next_game_round(chat_id, 2, thread_id)
        return
    elif cmd in ["/game3", "/guess", "/number"]:
        reset_game_difficulty(chat_id, 3)
        send_next_game_round(chat_id, 3, thread_id)
        return
    elif cmd in ["/game4", "/quiz"]:
        reset_game_difficulty(chat_id, 4)
        send_next_game_round(chat_id, 4, thread_id)
        return
    elif cmd in ["/stop", "/cancel", "/closequiz", "/closegame"]:
        c_key = str(chat_id)
        cancel_game_generation_retries(chat_id)
        if "active_game" in state_data and c_key in state_data["active_game"]:
            del state_data["active_game"][c_key]
            save_state()
            stop_msg = (
                "🛑 <b>یارییەکە ڕاگیرا لەلایەن ئەدمینەوە!</b> ✨\n\n"
                "دەستخۆشی لە هەموو بەشداربووان دەکەین 🌸🏆 بۆ بینینی خاڵەکان بنووسە: <code>/points</code> 👑"
            )
            send_message(chat_id, stop_msg, msg_id, thread_id)
            send_message(chat_id, build_current_game_scoreboard(chat_id), 0, thread_id)
        elif "active_quiz" in state_data and c_key in state_data["active_quiz"]:
            del state_data["active_quiz"][c_key]
            save_state()
            send_message(chat_id, "🛑 یارییەکە ڕاگیرا! دەستخۆش بۆ هەمووان 🌸", msg_id, thread_id)
        else:
            send_message(chat_id, "ℹ️ لە ئێستادا هیچ یارییەکی چالاک دانەنراوە تا ڕابگیرێت! 🎮🌸", msg_id, thread_id)
        return
    elif cmd in ["/answer", "/ans", "/hal", "/next"]:
        c_key = str(chat_id)
        if "active_game" in state_data and c_key in state_data["active_game"]:
            g = state_data["active_game"][c_key]
            if g.get("generating"):
                send_message(chat_id, "⏳ AI هێشتا خەریکی دروستکردنی خولێکی تازەیە و خۆکار بەردەوام دەبێت 🌸🤖", msg_id, thread_id)
                return
            gt = g.get("game_type", 1)
            ans = ""
            if gt == 1:
                ans = g.get("display", "")
            elif gt == 2:
                ans = f"{g.get('correct_ans')} ({g.get('info')})"
            elif gt == 3:
                ans = f"ژمارەی نهێنی {g.get('secret')} بوو!"
            elif gt == 4:
                ans = g.get("display_answer", "")
            ans_msg = (
                f"💡 <b>وەڵامی دروست:</b> {ans} ✨\n\n"
                f"⏳ <i>خولی نوێ لە چەند چرکەیەکی تردا دێت...</i> 🎮🌸"
            )
            send_message(chat_id, ans_msg, msg_id, thread_id)
            
            def answer_next_game_thread():
                time.sleep(3)
                if "active_game" in state_data and c_key in state_data["active_game"]:
                    send_next_game_round(chat_id, gt, thread_id)
            
            state_data["active_game"][c_key]["answers"] = []
            save_state()
            threading.Thread(target=answer_next_game_thread, daemon=True).start()
        else:
            send_message(chat_id, "ℹ️ لە ئێستادا هیچ یارییەکی چالاک دانەنراوە! دەتوانیت بە <code>/game1</code> تا <code>/game4</code> یاری دەستپێبکەیت 🎮🌸", msg_id, thread_id)
        return
    elif cmd in ["/points", "/score", "/scores", "/top"]:
        c_key = str(chat_id)
        scores = state_data.get("quiz_scores", {}).get(c_key, {})
        my_pts = scores.get(str(user_id), 0)
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
        board = "🏆 <b>ڕیزبەندیی پاڵەوانانی یاری لەم گروپەدا:</b>\n\n"
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        
        user_names = state_data.get("user_names", {})
        members_map = state_data.get("members", {}).get(c_key, {})
        
        if sorted_scores:
            for idx, (uid, pts) in enumerate(sorted_scores):
                medal_icon = medals[idx] if idx < len(medals) else f"#{idx+1}"
                u_name = user_names.get(str(uid))
                if not u_name and str(uid) in members_map:
                    u_name = members_map[str(uid)].get("first_name")
                    
                if not u_name:
                    try:
                        cm_res = tg_call("getChatMember", {"chat_id": chat_id, "user_id": int(uid)})
                        if cm_res and cm_res.get("ok"):
                            cm_user = cm_res.get("result", {}).get("user", {})
                            u_name = get_display_name(cm_user)
                            if "user_names" not in state_data:
                                state_data["user_names"] = {}
                            state_data["user_names"][str(uid)] = u_name
                            save_state()
                    except Exception:
                        pass
                
                if not u_name:
                    u_name = f"پاڵەوان {idx+1}"
                    
                board += f"{medal_icon} <b>{html.escape(u_name)}</b>: <b>{pts} خاڵ</b> 🌟\n"
        else:
            board += "تائێستا کەس خاڵی تۆمار نەکردووە! یەکەم کەس بە بە فەرمانی <code>/game1</code> تا <code>/game4</code> 🎮\n"
            
        board += f"\n👤 <b>خاڵەکانی تۆ ({html.escape(display_name)}):</b> <b>{my_pts} خاڵ</b> ✨"
        send_message(chat_id, board, msg_id, thread_id)
        return

    reply_to = msg.get("reply_to_message")
    target_user = reply_to.get("from") if reply_to else None

    if cmd == "/lock":
        ok = set_chat_locked(chat_id, True)
        if ok:
            send_message(chat_id, "🔒 **گروپ بە سەرکەوتوویی قوفڵ کرا!** 😴\n\nئەندامانی ئازیز، چاتکردن بە شێوەیەکی کاتی داخرا بۆ کاتی پشوو و خەو. شەوتان شاد 🌙✨", 0, thread_id)
        else:
            send_message(chat_id, "⚠️ نەتوانرا گروپ قوفڵ بکرێت. دڵنیابە بوتەکە مۆڵەتی ئەدمینی (Change Group Info / Restrict Members)ی هەیە! 🌸", msg_id, thread_id)

    elif cmd == "/unlock":
        ok = set_chat_locked(chat_id, False)
        if ok:
            send_message(chat_id, "🔓 **گروپ کرایەوە!** 🌸\n\nبەیانیتان باش و ڕۆژێکی پڕ لە خێر و کامەرانی بۆ هەمووان! ئێستا دەتوانن بە ئازادی چات بکەن ✨🎉", 0, thread_id)
        else:
            send_message(chat_id, "⚠️ نەتوانرا قوفڵی گروپ بکرێتەوە! 🌸", msg_id, thread_id)

    elif cmd == "/purge":
        count = 20
        if arg and arg.isdigit():
            count = int(arg)
        elif reply_to:
            r_id = reply_to.get("message_id", msg_id - 20)
            count = max(msg_id - r_id + 1, 1)
        delete_message(chat_id, msg_id)
        purge_chat_messages(chat_id, msg_id, count)
        print(f"🧹 Purged {count} messages in chat {chat_id}")

    elif cmd == "/del":
        if not reply_to:
            send_message(chat_id, "تکایە ڕیپڵای ئەو پەیامە بکە کە دەتەوێت بسڕدرێتەوە! 🗑️", msg_id, thread_id)
            return
        delete_message(chat_id, reply_to["message_id"])
        delete_message(chat_id, msg_id)

    if cmd == "/setrules":
        if not arg:
            send_message(chat_id, "تکایە دەقی یاساکان بنووسە: `/setrules دەق...`", msg_id, thread_id)
            return
        if "rules" not in state_data:
            state_data["rules"] = {}
        state_data["rules"][str(chat_id)] = arg
        save_state()
        send_message(chat_id, "✅ یاساکانی گروپ بە سەرکەوتوویی نوێکرانەوە! 🌸", msg_id, thread_id)

    elif cmd == "/warn":
        if not target_user:
            send_message(chat_id, "تکایە ڕیپڵای پەیامی بەکارهێنەرەکە بکە بۆ ئاگادارکردنەوە! ⚠️", msg_id, thread_id)
            return
        t_id = target_user["id"]
        t_name = get_display_name(target_user)
        cnt = add_user_warning(chat_id, t_id)
        send_message(chat_id, f"⚠️ {t_name} ئاگادار کرایەوە! ({cnt}/{MAX_WARNINGS})", msg_id, thread_id)
        if cnt >= MAX_WARNINGS:
            set_user_mute(chat_id, t_id, AUTO_MUTE_MINUTES)
            send_message(chat_id, f"🚫 {t_name} بەهۆی گەیشتن بە ئەوپەڕی ئاگاداری بۆ ماوەی {AUTO_MUTE_MINUTES} خولەک بێدەنگ کرا! 🔇", 0, thread_id)

    elif cmd == "/warnings":
        if not target_user:
            send_message(chat_id, "تکایە ڕیپڵای بەکارهێنەر بکە! 📊", msg_id, thread_id)
            return
        t_id = target_user["id"]
        t_name = get_display_name(target_user)
        cnt = state_data.get("warnings", {}).get(str(chat_id), {}).get(str(t_id), 0)
        send_message(chat_id, f"📊 ژمارەی ئاگادارییەکانی {t_name}: ({cnt}/{MAX_WARNINGS}) ⚠️", msg_id, thread_id)

    elif cmd == "/clearwarnings":
        if not target_user:
            send_message(chat_id, "تکایە ڕیپڵای بەکارهێنەر بکە! ✨", msg_id, thread_id)
            return
        t_id = target_user["id"]
        t_name = get_display_name(target_user)
        reset_user_warnings(chat_id, t_id)
        send_message(chat_id, f"✅ هەموو ئاگادارییەکانی {t_name} سڕانەوە 🌸", msg_id, thread_id)

    elif cmd == "/mute":
        if not target_user:
            send_message(chat_id, "تکایە ڕیپڵای پەیامی بەکارهێنەرەکە بکە! 🔇", msg_id, thread_id)
            return
        t_id = target_user["id"]
        t_name = get_display_name(target_user)
        mins = parse_duration_minutes(arg)
        set_user_mute(chat_id, t_id, mins)
        send_message(chat_id, f"🚫 {t_name} بۆ ماوەی {mins} خولەک لە چاتکردن بێدەنگ کرا 🔇", msg_id, thread_id)

    elif cmd == "/unmute":
        if not target_user:
            send_message(chat_id, "تکایە ڕیپڵای پەیامی بەکارهێنەرەکە بکە! 🔊", msg_id, thread_id)
            return
        t_id = target_user["id"]
        t_name = get_display_name(target_user)
        unmute_user(chat_id, t_id)
        send_message(chat_id, f"🔊 بێدەنگی لەسەر {t_name} لادرا و دەتوانێت نامە بنێرێت 🌸", msg_id, thread_id)

    elif cmd == "/ban":
        if not target_user:
            send_message(chat_id, "تکایە ڕیپڵای بەکارهێنەر بکە! 🚫", msg_id, thread_id)
            return
        t_id = target_user["id"]
        t_name = get_display_name(target_user)
        ban_user(chat_id, t_id)
        send_message(chat_id, f"🚫 {t_name} لە گروپ دەرکرا و باند کرا ⛔", msg_id, thread_id)

    elif cmd == "/unban":
        if not arg or not arg.isdigit():
            send_message(chat_id, "تکایە ئایدی بەکارهێنەر بنووسە: `/unban 123456789`", msg_id, thread_id)
            return
        target_uid = int(arg)
        unban_user(chat_id, target_uid)
        send_message(chat_id, f"✅ بەکارهێنەر بە ئایدی `{target_uid}` ئازاد کرا 🌸", msg_id, thread_id)

    elif cmd in ["/setchannel", "/setchanal", "/setchanel", "/set_channel", "/channel_set"]:
        if not is_admin(chat_id, user_id):
            send_message(chat_id, "⚠️ ئەم فەرمانە تەنها بۆ ئەدمینەکانی گروپە! 🌸", msg_id, thread_id)
            return
        if not arg:
            help_txt = (
                "📢 <b>ڕێنمایی پەیوەستکردنی چەناڵ بۆ ئیجباری جۆین:</b>\n\n"
                "تکایە یوزەرنەیمی چەناڵەکە لەگەڵ فەرمانەکە بنووسە:\n"
                "نموونە: <code>/setchannel @mshell9</code>\n\n"
                "<i>تێبینی: پێویستە بۆتەکە لەناو چەناڵەکەدا ئەدمین (Admin) بێت بۆ پشکنینی ئەندامەکان.</i> 🌸"
            )
            send_message(chat_id, help_txt, msg_id, thread_id)
            return
        
        ch_target = arg.strip().split()[0]
        if not ch_target.startswith("@") and not ch_target.startswith("-100"):
            ch_target = f"@{ch_target}"
            
        test_res = tg_call("getChat", {"chat_id": ch_target})
        if not test_res or not test_res.get("ok"):
            send_message(chat_id, f"⚠️ نەتوانرا زانیاریی چەناڵی <code>{html.escape(ch_target)}</code> وەربگیرێت!\nتکایە دڵنیابە لە ڕاستیی یوزەرنەیم و بۆتەکە لە چەناڵەکە ئەدمین کراوە 🌸", msg_id, thread_id)
            return
            
        ch_title = test_res.get("result", {}).get("title", ch_target)
        if "force_channel" not in state_data:
            state_data["force_channel"] = {}
        state_data["force_channel"][str(chat_id)] = ch_target
        save_state()
        
        succ_msg = (
            f"✅ <b>چەناڵی گروپ بە سەرکەوتوویی پەیوەست کرا!</b> 🎉\n\n"
            f"📢 <b>ناوی چەناڵ:</b> {html.escape(ch_title)}\n"
            f"🏷️ <b>یوزەرنەیم:</b> {html.escape(ch_target)}\n\n"
            f"🔒 <i>لە ئێستاوە هەموو ئەندامێکی نا-ئەدمین دەبێت جۆینی ئەم چەناڵە بکات تا بتوانێت لە گروپ چات بکات.</i> 🌸"
        )
        send_message(chat_id, succ_msg, msg_id, thread_id)
        return

    elif cmd in ["/delchannel", "/delchanal", "/delchanel", "/unsetchannel", "/removechannel"]:
        if not is_admin(chat_id, user_id):
            send_message(chat_id, "⚠️ ئەم فەرمانە تەنها بۆ ئەدمینەکانی گروپە! 🌸", msg_id, thread_id)
            return
        c_key = str(chat_id)
        if "force_channel" in state_data and c_key in state_data["force_channel"]:
            del state_data["force_channel"][c_key]
            save_state()
            send_message(chat_id, "✅ مەرجی ئیجباری جۆینکردنی چەناڵ بۆ ئەم گروپە بە سەرکەوتوویی ناچالاک کرا! 🔓🌸", msg_id, thread_id)
        else:
            send_message(chat_id, "ℹ️ لە ئێستادا هیچ چەناڵێک بۆ ئەم گروپە دانەنراوە! 🌸", msg_id, thread_id)
        return

    elif cmd in ["/channel", "/getchannel"]:
        c_key = str(chat_id)
        current_ch = state_data.get("force_channel", {}).get(c_key)
        if current_ch:
            send_message(chat_id, f"📢 <b>چەناڵی پەیوەستکراوی ئەم گروپە:</b> <code>{html.escape(current_ch)}</code> 🌸\nبۆ سڕینەوە: <code>/delchannel</code>", msg_id, thread_id)
        else:
            send_message(chat_id, "ℹ️ هیچ چەناڵێک بۆ ئیجباری جۆین لەم گروپە دانەنراوە.\nبۆ دانان ئەدمین دەتوانێت بنووسێت: <code>/setchannel @username</code> 🌸", msg_id, thread_id)
        return

def claim_welcome_event(chat_id: int, user_id: int, cooldown_seconds: int = 90) -> bool:
    """True تەنها بۆ یەکەم update ـی جۆین؛ دووبارەی Telegram پشتگوێ دەخات."""
    if not chat_id or not user_id:
        return True
    now = time.time()
    event_key = f"{chat_id}_{user_id}"
    with recent_welcome_lock:
        previous = recent_welcome_events.get(event_key, 0)
        if now - previous < cooldown_seconds:
            return False
        recent_welcome_events[event_key] = now
        if len(recent_welcome_events) > 1000:
            cutoff = now - cooldown_seconds
            for key, created_at in list(recent_welcome_events.items()):
                if created_at < cutoff:
                    recent_welcome_events.pop(key, None)
    return True

def handle_new_member(chat_id: int, user: dict, msg_id: int = 0, thread_id: int = 0):
    if not user or user.get("is_bot"):
        return
    if not claim_welcome_event(chat_id, user.get("id", 0)):
        print(f"Skipped duplicate welcome event for user {user.get('id')} in chat {chat_id}")
        return
    
    m_first = html.escape(user.get("first_name", "ئازیز"))
    m_user = user.get("username")
    username_display = f"@{html.escape(m_user)}" if m_user else "یوزەری نییە"
    
    # 🏰 وەگرتنی زانیاری خۆکاری گروپ (ناوی گروپ، وێنەی پڕۆفایلی گروپ، ئۆنەر، چەناڵ)
    chat_res = tg_call("getChat", {"chat_id": chat_id})
    chat_info = chat_res.get("result", {}) if chat_res else {}
    raw_title = chat_info.get("title", "گروپ")
    group_title = html.escape(raw_title)
    group_photo_id = chat_info.get("photo", {}).get("big_file_id")
    group_username = chat_info.get("username")

    is_pat_mat = "پات" in raw_title or "mat" in raw_title.lower() or chat_id == -1002230635631

    if is_pat_mat:
        channel_text = "@mshell9 ✨"
        owner_text = "<b>خـاتـوو گـاردنـیـا</b> 🌸"
    else:
        # بۆ گروپەکانی تر: بە شێوەیەکی زیرەکانە ئۆنەری ڕاستەقینەی گروپ دەدۆزێتەوە
        admins_res = tg_call("getChatAdministrators", {"chat_id": chat_id})
        creator_user = None
        if admins_res and admins_res.get("ok"):
            for admin_item in admins_res.get("result", []):
                if admin_item.get("status") == "creator":
                    creator_user = admin_item.get("user", {})
                    break
        if creator_user:
            c_first = html.escape(creator_user.get("first_name", "بەڕێوەبەر"))
            c_u = creator_user.get("username")
            owner_text = f"<b>{c_first}</b>" + (f" (@{html.escape(c_u)})" if c_u else "") + " 👑"
        else:
            owner_text = "بەڕێوەبەری گروپ 👑"
            
        channel_text = f"@{html.escape(group_username)} ✨" if group_username else f"تایبەت بە گروپی {group_title} ✨"

    welcome_caption = (
        f"<b>بەخێربێیت بۆ گروپی {group_title}، دووربە لە هەموو کێشەیەک</b> 🌸\n"
        f"<b>گروپەکەمان بە بوونی تۆ ئاوەدانە</b> 🏡\n"
        f"<b>بەشداری چات بە لەگەڵمان تا پێکەوە شاد بین</b> 🥰\n\n"
        f"👤 <b>ناوت: {m_first}</b>\n"
        f"🏷️ <b>یوزەرت: {username_display}</b>\n"
        f"📢 <b>چەناڵی {group_title}: {channel_text}</b>\n"
        f"👑 <b>ئۆنەری {group_title}:</b>\n"
        f"{owner_text}"
    )
    
    # ١. تۆمارکردنی ئەندام لە داتابەیس
    record_group_member(chat_id, user)
    
    # ۲. ئەگەر بەکارهێنەرەکە وێنەی پڕۆفایلی هەبوو وێنەی پڕۆفایلی خۆی دادەنێت
    user_photo_bytes = None
    try:
        u_res = tg_call("getUserProfilePhotos", {"user_id": user.get("id", 0), "limit": 1})
        if u_res and u_res.get("ok"):
            u_photos = u_res.get("result", {}).get("photos", [])
            if u_photos and len(u_photos) > 0:
                sizes = u_photos[0]
                if sizes:
                    f_id = sizes[-1].get("file_id") or sizes[0].get("file_id")
                    user_photo_bytes, _ = download_telegram_file(f_id)
    except Exception as e:
        print(f"Error fetching user profile photo: {e}")

    if user_photo_bytes:
        send_photo(chat_id, user_photo_bytes, welcome_caption, msg_id, thread_id)
        print(f"👋 Sent dynamic welcome card with USER photo to: {m_first} ({username_display})")
    else:
        # ۳. ئەگەر بەکارهێنەر وێنەی پڕۆفایلی دانەنابوو، وێنەی نوێ و ڕاستەقینەی سەر گروپەکە دادەنێت
        group_photo_bytes = get_chat_latest_photo_bytes(chat_id, chat_info)
        if group_photo_bytes:
            send_photo(chat_id, group_photo_bytes, welcome_caption, msg_id, thread_id)
            print(f"👋 Sent dynamic welcome card with LIVE GROUP photo to: {m_first} ({username_display})")
        else:
            send_message(chat_id, welcome_caption, msg_id, thread_id)
            print(f"👋 Sent dynamic welcome card (text) to: {m_first} ({username_display})")

def handle_chat_member_update(data: dict):
    if not data:
        return
    chat = data.get("chat", {})
    chat_id = chat.get("id")
    if not chat_id:
        return
    
    if chat.get("type") in ["group", "supergroup"]:
        register_group(chat_id)
        
    old_member_obj = data.get("old_chat_member", {})
    old_status = old_member_obj.get("status")
    new_member_obj = data.get("new_chat_member", {})
    new_status = new_member_obj.get("status")
    user = new_member_obj.get("user", {})
    user_id = user.get("id")

    # کاتێک بەکارهێنەر جۆینی چەناڵی داواکراو دەکات، کارتی جۆینەکەی لە گروپ بسڕەوە
    if (
        chat.get("type") == "channel"
        and user_id
        and old_status in ["left", "kicked"]
        and new_status in ["member", "administrator", "creator"]
    ):
        for group_id, required_channel in state_data.get("force_channel", {}).items():
            if channel_update_matches_identifier(chat, required_channel):
                delete_force_join_card(int(group_id), user_id)
        return
    
    # User joined the group via link, invite, or direct join
    joined_group = new_status in ["member", "administrator", "creator"] or (
        new_status == "restricted" and new_member_obj.get("is_member") is True
    )
    if old_status in ["left", "kicked"] and joined_group:
        record_group_member(chat_id, user)
        print(f"👋 chat_member join detected in {chat_id}: {user.get('first_name')}")
        handle_new_member(chat_id, user)

# ═══════════════════════════════════════════════════════════════════════════════
#  چاودێری و پاراستنی نامەکان (Message Handling & Security Engine)
# ═══════════════════════════════════════════════════════════════════════════════

def forward_pv_to_owner(sender_user: dict, user_text: str, bot_reply: str = ""):
    """ناردنی کۆپییەکی چاتی شەخسی بۆ ئۆنەری بۆت بە شێوازێکی جوان"""
    owner_id = state_data.get("owner_id") or config.get("ownerId")
    
    # ئەگەر owner_id دیاری نەکرابوو، لە ئەدمینی سەرەکی (creator)ی گروپەکان دەیهێنێت
    if not owner_id and state_data.get("groups"):
        for gid in state_data["groups"]:
            admins_res = tg_call("getChatAdministrators", {"chat_id": gid})
            if admins_res and admins_res.get("ok"):
                for a in admins_res.get("result", []):
                    if a.get("status") == "creator":
                        owner_id = a.get("user", {}).get("id")
                        if owner_id:
                            state_data["owner_id"] = owner_id
                            save_state()
                            break
            if owner_id:
                break
                
    if not owner_id:
        return
        
    s_name = html.escape(get_display_name(sender_user))
    s_id = sender_user.get("id", 0)
    s_username = sender_user.get("username")
    s_user_txt = f"@{html.escape(s_username)}" if s_username else "یوزەری نییە"
    
    # ئەگەر خودی ئۆنەر قسە لەگەڵ بۆت بکات، پەیامەکەی بۆ خۆی نانێرێتەوە
    if s_id == owner_id:
        return
        
    report = (
        "📩 <b>پەیامێکی نوێ لە چاتی شەخسی (PV):</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>نێرەر:</b> {s_name}\n"
        f"🆔 <b>ئایدی:</b> <code>{s_id}</code>\n"
        f"🏷️ <b>یوزەر:</b> {s_user_txt}\n\n"
        f"💬 <b>دەقی پەیام:</b>\n{html.escape(user_text)}\n\n"
        f"🤖 <b>وەڵامی بۆت:</b>\n{html.escape(bot_reply)}"
    )
    send_message(owner_id, report)
    print(f"📬 Forwarded PV chat from {s_name} to owner ({owner_id})")

def normalize_kurdish(s: str) -> str:
    """ڕێکخستن و یەکسانکردنی پیت و دەنگە کوردی و عەرەبییەکان بۆ لێکتێگەیشتنی تەواوی وەڵامەکان"""
    if not s:
        return ""
    s = s.strip().lower()
    # Remove zero-width characters and tatweel
    s = re.sub(r'[\u200b\u200c\u200d\u200e\u200f\ufeffـ]', '', s)
    # Remove arabic diacritics
    s = re.sub(r'[\u064b-\u065f\u0670]', '', s)
    # Normalize common Kurdish/Arabic glyph variants (وەک مۆبایل / موبایل، ئەسپ / ئەسب، هتد)
    s = s.replace("ك", "ک").replace("ي", "ی").replace("ى", "ی").replace("ھ", "ه").replace("ە", "ه").replace("ێ", "ی").replace("ة", "ه")
    s = s.replace("ۆ", "و").replace("وو", "و").replace("ڕ", "ر").replace("ڵ", "ل").replace("ڤ", "ف")
    # Remove punctuation and special symbols
    s = re.sub(r'[^\w\s]', '', s)
    return re.sub(r'\s+', ' ', s).strip()

def get_word_stems(w: str) -> list:
    """وەرگرتنی ڕەگی وشە بە لابردنی پاشگرە باوەکانی کوردی وەک (ە، ەکە، ێک، ێکە، ان، مان، تان، یان، ی)"""
    if not w:
        return []
    stems = [w]
    suffixes = ["هکه", "یکه", "یان", "مان", "تان", "ان", "یک", "که", "ه", "ی", "دا", "را"]
    for suf in suffixes:
        if len(w) > len(suf) + 2 and w.endswith(suf):
            stems.append(w[:-len(suf)])
    return list(set(stems))

def evaluate_quiz_answer(user_text: str, valid_answers: list) -> str:
    """
    پشکنینی پێشکەوتووی وەڵامی بەکارهێنەر:
    دەگەڕێنێتەوە:
    - 'exact': وەڵامی تەواو ڕاست (یاخود لێکچوونی زۆر زۆر بەرز یان پیتێکی کەم فەرق)
    - 'close': زۆر لێی نزیک بووەتەوە بەڵام کەمێکی مابوو (نزیکت کردەوە)
    - 'wrong': وەڵامی هەڵە
    """
    if not user_text or not valid_answers:
        return "wrong"
        
    norm_user = normalize_kurdish(user_text)
    if not norm_user:
        return "wrong"
        
    user_words = norm_user.split()
    user_stems = []
    for uw in user_words:
        user_stems.extend(get_word_stems(uw))
        
    max_similarity = 0.0
    is_partially_contained = False
    
    for ans in valid_answers:
        norm_ans = normalize_kurdish(ans)
        if not norm_ans:
            continue
            
        ans_words = norm_ans.split()
        ans_stems = []
        for aw in ans_words:
            ans_stems.extend(get_word_stems(aw))
            
        # ١. پشکنینی یەکسانیی تەواو
        if norm_ans == norm_user:
            return "exact"
            
        # ۲. پشکنینی ڕەگی وشەکان (Stems)
        if any(us in ans_stems for us in user_stems) or any(as_ in user_stems for as_ in ans_stems):
            return "exact"
            
        # ۳. پشکنینی وشە لەناو ڕستە یان ڕیپڵای
        if norm_ans in user_words:
            return "exact"
            
        if re.search(r'\b' + re.escape(norm_ans) + r'\b', norm_user):
            return "exact"
            
        if len(norm_ans) >= 3 and norm_ans in norm_user:
            return "exact"
            
        # ٤. پشکنینی ڕێژەی لێکچوونی پیتەکان (Similarity Ratio)
        sim = difflib.SequenceMatcher(None, norm_user, norm_ans).ratio()
        if sim > max_similarity:
            max_similarity = sim
            
        # ئەگەر وشەکە درێژ بوو و تەنها ۱ پیت جیاواز بوو ➔ ڕاست دادەنرێت
        if len(norm_ans) >= 4 and sim >= 0.80:
            return "exact"
            
        # پشکنینی وشەکانی ناو وەڵام
        for uw in user_words:
            for aw in ans_words:
                w_sim = difflib.SequenceMatcher(None, uw, aw).ratio()
                if w_sim > max_similarity:
                    max_similarity = w_sim
                if len(aw) >= 4 and w_sim >= 0.80:
                    return "exact"
                if len(aw) >= 3 and (uw in aw or aw in uw):
                    is_partially_contained = True

    # ٥. ئەگەر بەکارهێنەر زۆر نزیک بووبێتەوە (نێوان 0.52 تا 0.79 یان پیتەکانی لەیەک چوو بن)
    if max_similarity >= 0.52 or is_partially_contained:
        return "close"
        
    return "wrong"

def is_quiz_answer_match(user_text: str, valid_answers: list) -> bool:
    return evaluate_quiz_answer(user_text, valid_answers) == "exact"

def handle_message(msg: dict):
    if not msg or "chat" not in msg:
        return
    chat = msg["chat"]
    chat_type = chat.get("type", "")
    if chat_type not in ["group", "supergroup", "private"]:
        return

    chat_id = chat["id"]
    msg_id = msg.get("message_id", 0)
    thread_id = msg.get("message_thread_id", 0)
    from_user = msg.get("from") or msg.get("sender_chat") or {"id": chat_id, "title": chat.get("title", "Admin")}
    user_id = from_user.get("id", chat_id)
    display_name = get_display_name(from_user)
    is_user_admin = chat_type in ["group", "supergroup"] and is_message_from_admin(chat_id, user_id, msg)

    # Register group for broadcasts and record active member
    if chat_type in ["group", "supergroup"]:
        register_group(chat_id)
        record_group_member(chat_id, from_user)

    # 🎙️ پەیوەندی دەنگی (Voice / Video Chat Started Notification - بێ تاگکردن تەنها ١ پەیام)
    if any(k in msg for k in ["video_chat_started", "voice_chat_started"]):
        print(f"🎙️ Voice chat started detected in {chat_id}! Sending single notification...")
        send_voice_chat_notification(chat_id, thread_id)
        return

    text = msg.get("text") or msg.get("caption") or ""
    print(f"📩 [{chat_type.upper()}] {display_name} (ID: {user_id}): {text if text else '[Media/Sticker/Other]'}")

    # 📢 تاگکردنی هەموو میمبەرەکان ٥ بە ٥ بە نووسینی @all (تەنها بۆ ئەدمین)
    if "@all" in text.lower() and is_user_admin:
        custom_txt = re.sub(r'(?i)@all', '', text).strip()
        tag_all_members_batches(chat_id, custom_txt, thread_id)
        return

    # 🌸 بەخێرهاتنی ئەندامانی نوێ و دژە-بۆت (Anti-Bot)
    if "new_chat_members" in msg:
        for member in msg["new_chat_members"]:
            if member.get("is_bot"):
                # ئەگەر بۆت بوو و ئەو کەسەی زیادی کردووە ئەدمین نەبوو ➔ دەرکردنی بۆت
                if not is_user_admin:
                    ban_user(chat_id, member["id"])
                    unban_user(chat_id, member["id"])
                    delete_message(chat_id, msg_id)
                    send_message(chat_id, f"🚫 {display_name} ناتوانیت بۆت زیاد بکەیت! تەنها ئەدمین مۆڵەتی هەیە ⚠️", 0, thread_id)
                    print(f"🤖 Anti-Bot: Kicked unauthorized bot {member.get('id')} added by {display_name}")
                continue
            
            record_group_member(chat_id, member)
            handle_new_member(chat_id, member, msg_id, thread_id)
        # پەیامی سیستەمی جۆین نابێت وەک چات/سپام دووبارە پشکنین بکرێت.
        return

    # ناسینەوەی Next بەبێ / بۆ گواستنەوە بۆ خولی نوێ (تەنها بۆ ئەدمین)
    if text.strip().lower() in ["next", "نێکست", "دواتر"] and is_user_admin:
        handle_command(msg, "/next")
        return

    # فرمانەکان
    if text.startswith("/"):
        print(f"⚡ Executing command: {text} from {display_name}")
        handle_command(msg, text)
        return

    # چاتی تایبەت (Private Chat AI & Forward to Owner)
    if chat_type == "private":
        if config.get("aiInPrivateChats", True) and text:
            reply = get_ai_reply(chat_id, user_id, text)
            if reply:
                send_message(chat_id, reply, msg_id)
                print(f"🤖 [PV] Replied to {display_name}: {reply}")
                forward_pv_to_owner(from_user, text, reply)
        return

    # 🛡️ پشکنینی سکوریتی توند بۆ هەموو نامەکان (ستیکەر، گیف، وێنە، ڤیدیۆ)
    violation = ""

    # پەیامی ئەدمین و ئۆنەر بە هیچ شێوەیەک لەلایەن پاراستنی ئۆتۆماتیکییەوە ناسڕدرێتەوە
    # ١. پشکنینی ستیکەری سێکسی بە AI Vision
    if not is_user_admin and config.get("blockNSFWStickers", True) and "sticker" in msg and is_nsfw_sticker(msg["sticker"]):
        violation = "ناردنی ستیکەری نەشیاو و سێکسی 🔞"
    # ۲. پشکنینی وێنەی سێکسی بە AI Vision
    elif not is_user_admin and "photo" in msg and is_nsfw_photo(msg):
        violation = "ناردنی وێنەی نەشیاو و سێکسی 🔞"
    # ۳. پشکنینی ڤیدیۆی سێکسی بە AI Vision
    elif not is_user_admin and ("video" in msg or "video_note" in msg):
        video_scan = False
        for check_id in security_media_file_candidates(msg):
            if check_nsfw_with_ai_vision(check_id) is True:
                video_scan = True
                break
        if video_scan:
            violation = "ناردنی ڤیدیۆی نەشیاو و سێکسی 🔞"
    # ٤. پشکنینی گیف و فایلی نەشیاو بە AI Vision
    elif not is_user_admin and config.get("blockNSFWGIFs", True) and ("animation" in msg or "document" in msg) and is_nsfw_animation_or_media(msg, text):
        violation = "ناردنی گیف یان فایلی نەشیاو 🔞"
    # ٥. پشکنینی لینک و سپام (بۆ نا-ئەدمین)
    elif not is_user_admin and config.get("blockLinks", True) and contains_link_or_spam(msg, text):
        violation = "ناردنی لینک، پۆست یان ریپڵای دوگمەدار 🔗"
    # ٦. پشکنینی جنێو و قسەی ناشرین (بۆ نا-ئەدمین)
    elif not is_user_admin and config.get("blockBadWords", True) and contains_bad_word(text):
        violation = "قسەی ناشرین و جنێو 🤬"

    if violation:
        delete_message(chat_id, msg_id)
        cnt = add_user_warning(chat_id, user_id)
        send_message(chat_id, f"⚠️ {display_name} {violation} قەدەغەیە! ئاگاداری: ({cnt}/{MAX_WARNINGS})")
        print(f"🛡️ Deleted violation from {display_name}: {violation} (Warning {cnt}/{MAX_WARNINGS})")
        if cnt >= MAX_WARNINGS:
            set_user_mute(chat_id, user_id, AUTO_MUTE_MINUTES)
            send_message(chat_id, f"🚫 {display_name} بەهۆی دووبارەکردنەوەی سەرپێچی، بۆ ماوەی {AUTO_MUTE_MINUTES} خولەک لە چاتکردن بێدەنگ کرا! 🔇")
            print(f"🚫 Muted {display_name} for {AUTO_MUTE_MINUTES} minutes")
        return

    # 📢 پشکنینی ئیجباری جۆینکردنی چەناڵ بۆ ئەندامانی نا-ئەدمین (Force Subscribe Check)
    if chat_type in ["group", "supergroup"] and not is_user_admin:
        group_req_channel = state_data.get("force_channel", {}).get(str(chat_id))
        if group_req_channel:
            is_subbed = is_user_subscribed_to_channel(group_req_channel, user_id)
            if not is_subbed:
                delete_message(chat_id, msg_id)
                cd_key = f"{chat_id}_{user_id}"
                now_t = time.time()
                last_card_t = force_join_cooldowns.get(cd_key, 0)
                if now_t - last_card_t > 25:
                    force_join_cooldowns[cd_key] = now_t
                    send_force_join_card(chat_id, user_id, display_name, group_req_channel, thread_id)
                print(f"🔒 Force-Join: Deleted message from non-subscribed user {display_name} in chat {chat_id}")
                return
            delete_force_join_card(chat_id, user_id)

    # 🎮 پشکنینی وەڵامی یارییە بەکۆمەڵەکان (تەنها کاتێک بەکارهێنەر ڕیپڵای پەیامی یارییەکە دەکات)
    c_key = str(chat_id)
    if "active_game" in state_data and c_key in state_data["active_game"] and text:
        curr_game = state_data["active_game"][c_key]
        if curr_game.get("generating"):
            return
        
        is_reply_to_game = False
        if "reply_to_message" in msg and msg["reply_to_message"]:
            replied_msg = msg["reply_to_message"]
            replied_from = replied_msg.get("from", {})
            replied_id = replied_from.get("id", 0)
            replied_mid = replied_msg.get("message_id", 0)
            game_mid = curr_game.get("msg_id", 0)
            
            if replied_id == BOT_ID or replied_from.get("is_bot") or (game_mid > 0 and replied_mid == game_mid):
                is_reply_to_game = True

        # ئەگەر بەکارهێنەر ڕیپڵای یارییەکەی کردبێت ➔ پشکنین بۆ وەڵامەکە دەکات
        if is_reply_to_game:
            g_type = curr_game.get("game_type", 1)
            clean_text = text.strip()
            record_game_participant(chat_id, user_id, display_name)
            
            # 🧩 ۱. یاریی وشە تێکئاڵاوەکان (Game 1)
            if g_type == 1:
                answers = curr_game.get("answers", [])
                target_word = curr_game.get("word", "")
                eval_res = evaluate_quiz_answer(clean_text, answers + [target_word])
                if eval_res == "exact":
                    pts = add_user_quiz_point(chat_id, user_id, display_name)
                    disp = curr_game.get("display", target_word)
                    win_msg = (
                        f"🎉 <b>ئافەرین {display_name} گیان! وشەکەت دۆزییەوە!</b> 👏🌟\n\n"
                        f"✅ <b>وشەی ڕاست:</b> {disp}\n"
                        f"🏆 <b>+١ خاڵت بەدەستهێنا!</b> کۆی خاڵەکانت: <b>{pts} خاڵ</b> ✨\n\n"
                        f"⏳ <i>وشەی نوێ لە چەند چرکەیەکی تردا دێت...</i> 🧩🌸"
                    )
                    send_message(chat_id, win_msg, msg_id, thread_id)
                    curr_game["answers"] = []
                    curr_game["word"] = ""
                    save_state()
                    def auto_next_g1():
                        time.sleep(3)
                        if "active_game" in state_data and c_key in state_data["active_game"]:
                            send_next_game_round(chat_id, 1, thread_id)
                    threading.Thread(target=auto_next_g1, daemon=True).start()
                    return
                elif eval_res == "close":
                    send_message(chat_id, f"🤏 <b>زۆر زۆر لێی نزیک بوویتەوە {display_name} گیان!</b> کەمێکی تر پیتەکان ڕێکبخە تەواو دەبێت! 🧩😃🌸", msg_id, thread_id)
                    return
                else:
                    send_message(chat_id, f"❌ <b>وشەکە دروست نییە {display_name} گیان!</b> پیتەکان جارێکی تر تاقی بکەرەوە 🧩🤔🌸", msg_id, thread_id)
                    return

            # ⚡ ۲. یاریی ڕاست یان هەڵە (Game 2)
            elif g_type == 2:
                correct_ans = curr_game.get("correct_ans", "")
                info = curr_game.get("info", "")
                norm_c = normalize_kurdish(clean_text)
                user_said_true = any(k in norm_c for k in ["ڕاست", "راست", "rast", "true", "t", "1"])
                user_said_false = any(k in norm_c for k in ["هەڵە", "هەلە", "hala", "false", "f", "0"])
                
                if user_said_true or user_said_false:
                    is_correct = (user_said_true and "ڕاست" in correct_ans) or (user_said_false and "هەڵە" in correct_ans)
                    if is_correct:
                        pts = add_user_quiz_point(chat_id, user_id, display_name)
                        win_msg = (
                            f"🎉 <b>ئافەرین {display_name} گیان! وەڵامەکەت زۆر دروستە!</b> 👏🌟\n\n"
                            f"✅ <b>وەڵامی ڕاست:</b> {correct_ans}\n"
                            f"ℹ️ <b>زانیاری:</b> {info}\n"
                            f"🏆 <b>+١ خاڵت بەدەستهێنا!</b> کۆی خاڵەکانت: <b>{pts} خاڵ</b> ✨\n\n"
                            f"⏳ <i>پرسیاری نوێ لە چەند چرکەیەکی تردا دێت...</i> ⚡🌸"
                        )
                        send_message(chat_id, win_msg, msg_id, thread_id)
                        curr_game["aliases"] = []
                        curr_game["correct_ans"] = ""
                        save_state()
                        def auto_next_g2():
                            time.sleep(3)
                            if "active_game" in state_data and c_key in state_data["active_game"]:
                                send_next_game_round(chat_id, 2, thread_id)
                        threading.Thread(target=auto_next_g2, daemon=True).start()
                        return
                    else:
                        send_message(chat_id, f"❌ <b>وەڵامەکەت هەڵەیە {display_name} گیان!</b> کێ دەتوانێت وەڵامی دروست بداتەوە؟ 🤔🌸", msg_id, thread_id)
                        return
                else:
                    send_message(chat_id, f"❌ <b>تکایە بنووسە ڕاست یان هەڵە {display_name} گیان!</b> ⚡🤔🌸", msg_id, thread_id)
                    return

            # 🎯 ۳. یاریی دۆزینەوەی ژمارەی نهێنی (Game 3)
            elif g_type == 3:
                digits = re.findall(r'\b\d+\b', text)
                if digits:
                    guess = int(digits[0])
                    secret = curr_game.get("secret", 50)
                    minimum = curr_game.get("min", 1)
                    maximum = curr_game.get("max", 100)
                    if guess < minimum or guess > maximum:
                        send_message(chat_id, f"🔢 {display_name} گیان، ژمارەیەک لە نێوان <b>{minimum} تا {maximum}</b> هەڵبژێرە 🌸", msg_id, thread_id)
                        return
                    diff = abs(guess - secret)
                    if guess == secret:
                        pts = add_user_quiz_point(chat_id, user_id, display_name)
                        win_msg = (
                            f"🎉 <b>ئافەرین {display_name} گیان! ژمارە نهێنییەکەت دۆزییەوە!</b> 👏🌟\n\n"
                            f"🎯 <b>ژمارەی نهێنی:</b> {secret}\n"
                            f"🏆 <b>+١ خاڵت بەدەستهێنا!</b> کۆی خاڵەکانت: <b>{pts} خاڵ</b> ✨\n\n"
                            f"⏳ <i>گەڕی نوێی ژمارە لە چەند چرکەیەکی تردا دەست پێدەکات...</i> 🔢🌸"
                        )
                        send_message(chat_id, win_msg, msg_id, thread_id)
                        curr_game["secret"] = -1
                        save_state()
                        def auto_next_g3():
                            time.sleep(3)
                            if "active_game" in state_data and c_key in state_data["active_game"]:
                                send_next_game_round(chat_id, 3, thread_id)
                        threading.Thread(target=auto_next_g3, daemon=True).start()
                        return
                    elif diff <= 4:
                        # زۆر زۆر نزیکە (تەنها چەند ژمارەیەکی کەم فەرقە)
                        hint_dir = "بەرزترە ⬆️" if guess < secret else "نزمترە ⬇️"
                        send_message(chat_id, f"🔥 <b>زۆر زۆر لێی نزیکی {display_name} گیان!</b> ژمارەکە تەنها کەمێک {hint_dir} لە {guess}! 🤏😃🌸", msg_id, thread_id)
                        return
                    elif guess < secret:
                        send_message(chat_id, f"⬆️ ژمارە نهێنییەکە <b>بەرزترە</b> لە {guess}! ({display_name}) 🌸", msg_id, thread_id)
                        return
                    elif guess > secret:
                        send_message(chat_id, f"⬇️ ژمارە نهێنییەکە <b>نزمترە</b> لە {guess}! ({display_name}) 🌸", msg_id, thread_id)
                        return
                else:
                    minimum = curr_game.get("min", 1)
                    maximum = curr_game.get("max", 100)
                    send_message(chat_id, f"🔢 <b>تکایە ژمارەیەک بنووسە {display_name} گیان! ({minimum} تا {maximum})</b> 🎯🌸", msg_id, thread_id)
                    return

            # ❓ ٤. یاریی مەتەڵی کوردی (Game 4 / Quiz)
            elif g_type == 4:
                answers = curr_game.get("answers", [])
                eval_res = evaluate_quiz_answer(clean_text, answers)
                if eval_res == "exact":
                    pts = add_user_quiz_point(chat_id, user_id, display_name)
                    disp_ans = curr_game.get("display_answer", "")
                    win_msg = (
                        f"🎉 <b>ئافەرین {display_name} گیان! وەڵامەکەت زۆر دروستە!</b> 👏🌟\n\n"
                        f"✅ <b>وەڵام:</b> {disp_ans}\n"
                        f"🏆 <b>+١ خاڵت بەدەستهێنا!</b> کۆی گشتی خاڵەکانت: <b>{pts} خاڵ</b> ✨\n\n"
                        f"⏳ <i>مەتەڵی نوێ لە چەند چرکەیەکی تردا دێت...</i> ❓🌸"
                    )
                    send_message(chat_id, win_msg, msg_id, thread_id)
                    curr_game["answers"] = []
                    save_state()
                    def auto_next_g4():
                        time.sleep(3)
                        if "active_game" in state_data and c_key in state_data["active_game"]:
                            send_next_game_round(chat_id, 4, thread_id)
                    threading.Thread(target=auto_next_g4, daemon=True).start()
                    return
                elif eval_res == "close":
                    send_message(chat_id, f"🤏 <b>زۆر زۆر لێی نزیک بوویتەوە {display_name} گیان!</b> کەمێکی تر تەواوی بکە یان وشەکەی ڕێک بخە! 😃🌸", msg_id, thread_id)
                    return
                else:
                    send_message(chat_id, f"❌ <b>وەڵامەکەت هەڵەیە {display_name} گیان!</b> کەمێکی تر بیری لێ بکەرەوە یان کێ دەتوانێت وەڵامی دروست بداتەوە؟ 🤔🌸", msg_id, thread_id)
                    return

    # 💬 وەڵامدانەوەی AI بە کوردییەکی زۆر ڕوخۆش و پڕ ئیمۆجی
    # مەرج: ئەگەر مرۆڤێک ڕیپڵای مرۆڤێکی تر بکات، بوتەکە بێدەنگ دەبێت و تەداخول ناکات
    if config.get("aiEnabled", True) and text:
        should_ai_reply = True
        if "reply_to_message" in msg and msg["reply_to_message"]:
            target_user = msg["reply_to_message"].get("from", {})
            target_id = target_user.get("id", 0)
            is_target_bot = target_user.get("is_bot", False)
            # ئەگەر ڕیپڵای کەسێکی مرۆڤ بێت (نەک بووتەکە) ➔ تەداخول ناکات
            if target_id != BOT_ID and not is_target_bot:
                should_ai_reply = False

        if should_ai_reply:
            reply = get_ai_reply(chat_id, user_id, text)
            if reply:
                send_message(chat_id, reply, msg_id)
                print(f"🤖 Replied to {display_name}: {reply}")

# ═══════════════════════════════════════════════════════════════════════════════
#  دەستپێکردنی مۆتۆری سەرەکی (Main Engine)
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    tg_call("deleteWebhook", {"drop_pending_updates": True})
    print("===============================================")
    print("  Gardnya Security & AI Protection Bot Started!")
    print(f"  Bot: @{config.get('botUsername', 'gardny4_bot')}")
    print(f"  AI Model: {GROQ_MODEL} (Joyful & Kurdish Persona)")
    print("  Equal Hours & Prayer Broadcasts: Active")
    print("  Smart NSFW Sticker & GIF Protection: Active")
    print("===============================================")

    # Start background scheduler thread for Mirror Hours and Prayer Times
    t = threading.Thread(target=background_scheduler, daemon=True)
    t.start()

    offset = 0
    polling_failures = 0
    while True:
        try:
            res = tg_call(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 30,
                    "allowed_updates": ["message", "chat_member", "my_chat_member"],
                },
            )
            if res and res.get("ok"):
                polling_failures = 0
                if not BOT_ID:
                    refresh_bot_identity()
                for update in res["result"]:
                    offset = update["update_id"] + 1
                    if "message" in update:
                        handle_message(update["message"])
                    elif "chat_member" in update:
                        handle_chat_member_update(update["chat_member"])
                    elif "my_chat_member" in update:
                        handle_chat_member_update(update["my_chat_member"])
            else:
                polling_failures += 1
                # کاتێک پراکسی 503 ـە، loop ـەکە بە خێرایی log پڕ نەکات و CPU بەفیڕۆ نەدات.
                time.sleep(min(30, 2 + polling_failures * 2))
        except Exception as e:
            safe_error = str(e).replace(BOT_TOKEN, "<BOT_TOKEN_REDACTED>") if BOT_TOKEN else str(e)
            print("Polling Exception:", safe_error)
            time.sleep(5)

if __name__ == "__main__":
    main()
