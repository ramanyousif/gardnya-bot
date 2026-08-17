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
import requests
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
#  ڕێکخستنەکان (Credentials & Configuration)
# ═══════════════════════════════════════════════════════════════════════════════

CONFIG_FILE = Path("config.json")
config = {
    "token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
    "botUsername": os.environ.get("BOT_USERNAME", "gardny4_bot"),
    "geminiApiKey": os.environ.get("GEMINI_API_KEY", ""),
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

if CONFIG_FILE.exists():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            file_cfg = json.load(f)
            config.update(file_cfg)
    except Exception as e:
        print(f"Warning: Failed to load config.json: {e}")

BOT_TOKEN = config.get("token") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = config.get("geminiApiKey") or os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = config.get("groqApiKey") or os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = config.get("groqModel", "llama-3.3-70b-versatile")
MAX_WARNINGS = int(config.get("maxWarnings", 3))
AUTO_MUTE_MINUTES = int(config.get("autoMuteMinutes", 60))

# Kurdistan Timezone (UTC+3)
KURDISTAN_UTC_OFFSET = datetime.timezone(datetime.timedelta(hours=3))

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Initialize Groq AI Client (fallback)
groq_client = None
if GROQ_API_KEY:
    try:
        import groq
        groq_client = groq.Groq(api_key=GROQ_API_KEY)
    except Exception as e:
        print(f"Groq Init Warning: {e}")

print(f"🤖 AI Engine: {'Google Gemini 2.0 Flash' if GEMINI_API_KEY else 'Groq ' + GROQ_MODEL if GROQ_API_KEY else 'None'}")
print(f"🌍 Timezone: Kurdistan (UTC+3)")

STATE_FILE = Path("data/state.json")
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
You are Gardnya (گاردنیا), a super friendly, witty, cheerful, and charming young Kurdish companion in a Telegram group chat.
You speak ONLY in natural, sweet Sorani Kurdish (کوردیی سۆرانی ئاسایی چاتی ڕۆژانە).

Personality & Rules:
1. You are VERY joyful, kind, smiling, respectful, and humorous (زۆر ڕوخۆش و قسەخۆش).
2. ALWAYS use lively, colorful emojis in EVERY response (🌸, ✨, ❤️, 😊, 🥰, 🌺, 🎉, 💖, 🤗, 💐, ☕).
3. Use warm Kurdish everyday expressions: (گیانەکەم, بەسەرچاو, وەڵا, براکەم, عافیەتبیت, دەستت خۆش, قوربانت, ههههه).
4. Answer ANY question asked by the user intelligently, helpfully, and cheerfully.
5. NEVER sound like a cold machine or broken literal English translation. Sound like a true sweet Kurdish best friend in a group!
"""

WELCOME_MESSAGES = [
    "🌸 سڵاو {name} گیان! زۆر زۆر بەخێر بێیت بۆ گروپەکەمان 🎉\n\nگەرمترین بەخێرهاتنت لێ دەکەین، هیواداریین کاتێکی زۆر خۆش و بەسوود لەگەڵمان بەسەر بەریت! ✨❤️🥰",
    "👑 سڵاو لە {name} خۆشەویست! زۆر بەخێربێیت بۆ نێو خێزانە چاک و ئازیزەکەمان 🌟\n\nگروپ بە هاتنی تۆ گەشاوەتر بوو، بە هیوای کاتی زۆر خۆش و سەرکەوتووانە! 🌺💐💖",
    "✨ سڵاو و دەرەکەت خۆش {name} گیان! بەخێربێیت بەسەر چاوانمان 💐\n\nزۆر دڵخۆشین بە بینینت لە نێوماندا! 🎉🌸🤗"
]

SMART_REPLIES = [
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
    }
]

import html

# ═══════════════════════════════════════════════════════════════════════════════
#  کاتژمێرە یەکسانەکان بە سیستەمی ۱۲ کاتژمێری و قۆناغەکانی ڕۆژ (Mirror Hours)
# ═══════════════════════════════════════════════════════════════════════════════

MIRROR_HOURS_CONFIG = {
    "00:00": {"time_label": "00:00 (شەو 🌙)", "quote": "دەستپێکی ڕۆژێکی نوێ و دەرفەتێکی نوێ بۆ سەرکەوتن و ژیانێکی باشتر.\nشەوێکی ئارام و خەوێکی شیرین بۆ هەمووتان 🌙✨🌸"},
    "01:01": {"time_label": "01:01 (شەو 🌙)", "quote": "هەمیشە هیوات بە خودا هەبێت، دەرگایەکت لێ دابخرێت هەزار دەرگات بۆ دەکرێتەوە.\nشەوێکی پڕ لە ئارامی بۆ هەمووتان 🌸❤️✨"},
    "02:02": {"time_label": "02:02 (شەو 🌙)", "quote": "دڵە پاکەکان هەمیشە ئارام دەژین، چونکە هیچ ڕق و کینەیەک لە دڵیاندا جێگەی نابێتەوە.\nشەوتان شاد و پڕ لە ئارامی دڵ ✨😴💖"},
    "03:03": {"time_label": "03:03 (شەو 🌙)", "quote": "هیچ شتێک مەحاڵ نییە کاتێک باوەڕت بە خۆت و پشتیوانیی پەروەردگار هەبێت.\nکاتێکی ئارام و پڕ لە بەرەکەت 🌟🕊️🌸"},
    "04:04": {"time_label": "04:04 (بەیانی ☀️)", "quote": "سەحر و بەیانی نوێ، دەرفەتێکی زێڕینە بۆ دەستپێکردنەوە و گەیشتن بە ئامانجەکانت.\nبەیانیتان پڕ لە خێر و سەرکەوتن ☀️💐✨"},
    "05:05": {"time_label": "05:05 (بەیانی ☀️)", "quote": "ژیان بە دڵخۆشی و خەندە جوانە، هەمیشە خەندە بکە چونکە تۆ شایەنی باشترینیت.\nبەیانیت باش و ڕۆژت پڕ لە کامەرانی 🌸✨🥰"},
    "06:06": {"time_label": "06:06 (بەیانی ☀️)", "quote": "ڕۆژێکی نوێ، هیوایەکی نوێ، سەرەتایەکی پڕ لە خێر و دەستکەوتی چاک بۆ هەمووان.\nڕۆژێکی پڕ لە وزەی ئەرێنی و شادی 🌻💖☀️"},
    "07:07": {"time_label": "07:07 (بەیانی ☀️)", "quote": "دەستپێکی ڕۆژ بە سوپاسگوزاری، بەرهەمی ڕۆژ بە بەختەوەری و کامەرانی دەڕوێنێت.\nبەیانیتان گوڵڕێژ و قاوەیەکی بەتام 🌺☕✨"},
    "08:08": {"time_label": "08:08 (بەیانی ☀️)", "quote": "هەرگیز کۆڵ مەدە لەوەی کە دڵت بەڕاستی دەیەوێت، سەرکەوتن بەردەوام چاوەڕێتە.\nڕۆژێکی پڕ لە بەرهەم و سەرکەوتن 🚀🌟💪"},
    "09:09": {"time_label": "09:09 (بەیانی ☀️)", "quote": "مرۆڤە میهرەبانەکان وەک گوڵ وان، لە هەر کوێ بن بۆن و بەرامی خێر و خۆشی دەبەخشنەوە.\nهەمیشە بدرەوشێنەوە و شاد بن 🌸👑💖"},
    "10:10": {"time_label": "10:10 (بەیانی ☀️)", "quote": "دڵت پڕ بکە لە خۆشەویستی و ئەرێنیبوون، چونکە تاکە سامانە کە هەرگیز کەم ناکات.\nکاتێکی زۆر خۆش و چاتێکی بەجۆش 💖☕✨"},
    "11:11": {"time_label": "11:11 (بەیانی 🌟)", "quote": "کاتژمێری ئاواتەکان! لە دڵەوە هیوای گەیشتن بە هەموو خەونە جوانەکانتان بۆ دەخوازم.\nخەونەکانتان ببن بە ڕاستی و ئاواتەکانتان بێنە دی ✨🌈🌸"},
    "12:12": {"time_label": "12:12 (نیوەڕۆ 🌞)", "quote": "نیوەڕۆتان باش! هەمیشە بە ئارامی و هێمنی هەنگاو بەرەو لوتکەی ئامانجەکانت بنێ.\nڕۆژێکی پڕ لە خێر و نۆشی گیانتان 🌞🍀❤️"},
    "13:13": {"time_label": "13:13 (نیوەڕۆ 🌞)", "quote": "ژیان کورتترە لەوەی بە خەم و بێزاری بەسەری بەریت، دڵت خۆش بکە بە شتە بچووکەکان.\nهەمیشە دەمتان بە خەندە و دڵتان ئارام بێت 😊🌸💐"},
    "14:14": {"time_label": "14:14 (نیوەڕۆ 🌞)", "quote": "بەهێز بە و بڕوات بە توانا و هێزی خۆت هەبێت، تۆ لەوە زۆر بەهێزتریت!\nبەردەوام بە بە تین و تاوەوە بەرەو سەرکەوتن 💪✨🔥"},
    "15:15": {"time_label": "15:15 (عەسر 🌤️)", "quote": "ئارامیی دڵ لە لێبوردەیی و خۆشەویستی و دەستباربوونی کەسانی ترەوە سەرچاوە دەگرێت.\nپڕ بن لە ئاشتی و میهرەبانی 🕊️❤️🌸"},
    "16:16": {"time_label": "16:16 (عەسر 🌤️)", "quote": "کات وەک زێڕە، لەگەڵ ئەو کەسانە بەسەری بەره کە بەنرخ و دڵسۆزن لە ژیانتدا.\nعەسرێکی دڵڕفێن و پڕ لە خۆشی ☕🍂✨"},
    "17:17": {"time_label": "17:17 (عەسر 🌤️)", "quote": "ئاوابوونی خۆر یادخەرەوەیە کە هەموو کۆتاییەک، سەرەتایەکی زۆر جوانتری بەدوادا دێت.\nئێوارەیەکی پڕ لە ئارامی و ساتەوەختی شیرین 🌇✨💐"},
    "18:18": {"time_label": "18:18 (ئێوارە 🌇)", "quote": "ڕێز و خۆشەویستی و وەفاداری گەورەترین دیارین کە دەتوانیت بە هاوڕێکانتی ببەخشیت.\nئێوارەتان باش و خوانتان پڕ لە بەرەکەت 🌸💖🍽️"},
    "19:19": {"time_label": "19:19 (ئێوارە 🌇)", "quote": "هەموو ساتێک سوپاسی خودا بکە بۆ ئەو هەزاران نیعمەت و تەندروستییەی پێت بەخشراوە.\nشەوێکی پڕ لە خێر و ئاسوودەیی دڵ 🌙🤲❤️"},
    "20:20": {"time_label": "20:20 (شەو 🌙)", "quote": "لەگەڵ خێزان و هاوڕێ ئازیزەکانتدا ساتەکانت بکە بە یادگارییەکی زێڕین و شیرین.\nکاتێکی زۆر خۆش و بەجۆش بۆ هەمووتان 🌟🎉🥰"},
    "21:21": {"time_label": "21:21 (شەو 🌙)", "quote": "مێشکت ئارام بکەرەوە و واز لە ماندووبوونی ڕۆژ بهێنە، تۆ ماندوو بوویت و هەوڵت دا.\nشەوتان شاد و چاتتان پڕ لە گەرمی 🫖🌙🌸"},
    "22:22": {"time_label": "22:22 (شەو 🌙)", "quote": "کاتژمێری ئارامیی شەوانە! هیوای خەوێکی پڕ لە خەونی شیرین و ئاسوودەیی بۆ هەمووان.\nشەوتان پڕ لە ئەستێرە و ڕووناکی بێت ✨😴💖"},
    "23:23": {"time_label": "23:23 (شەو 🌙)", "quote": "بێدەنگیی شەو باشترین دەرفەتە بۆ نزاکردن لەگەڵ پەروەردگار و دوعاکردن بۆ ئازیزانت.\nشەوتان پڕ لە بەرەکەت و نزای قبوڵکراو بێت 🤲🌌🌸"}
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
        r = requests.post(f"{API_BASE}/{method}", json=payload or {}, timeout=30)
        return r.json()
    except Exception as e:
        print(f"Telegram API Error ({method}):", e)
        return None

BOT_ID = 0
me_data = tg_call("getMe")
if me_data and me_data.get("ok"):
    BOT_ID = me_data["result"]["id"]
    print(f"Bot authenticated as: @{me_data['result'].get('username', 'bot')} (ID: {BOT_ID})")

def send_message(chat_id: int, text: str, reply_to: int = 0, thread_id: int = 0, parse_mode: str = "HTML"):
    body = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if parse_mode:
        body["parse_mode"] = parse_mode
    if reply_to > 0:
        body["reply_to_message_id"] = reply_to
        body["allow_sending_without_reply"] = True
    if thread_id > 0:
        body["message_thread_id"] = thread_id
    res = tg_call("sendMessage", body)
    if not res or not res.get("ok"):
        # Fallback without parse_mode if HTML entity formatting fails
        body.pop("parse_mode", None)
        res = tg_call("sendMessage", body)
    return res

def send_photo(chat_id: int, photo_path: str, caption: str, reply_to: int = 0, thread_id: int = 0):
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
        
        if photo_path and os.path.exists(photo_path):
            with open(photo_path, "rb") as f:
                files = {"photo": f}
                r = requests.post(f"{API_BASE}/sendPhoto", data=data, files=files, timeout=30)
                res = r.json()
                if not res.get("ok"):
                    data.pop("parse_mode", None)
                    f.seek(0)
                    r = requests.post(f"{API_BASE}/sendPhoto", data=data, files={"photo": f}, timeout=30)
                    return r.json()
                return res
        else:
            return send_message(chat_id, caption, reply_to, thread_id)
    except Exception as e:
        print(f"sendPhoto Error: {e}")
        return send_message(chat_id, caption, reply_to, thread_id)

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

def add_user_quiz_point(chat_id: int, user_id: int) -> int:
    c_key = str(chat_id)
    u_key = str(user_id)
    if "quiz_scores" not in state_data:
        state_data["quiz_scores"] = {}
    if c_key not in state_data["quiz_scores"]:
        state_data["quiz_scores"][c_key] = {}
    current = state_data["quiz_scores"][c_key].get(u_key, 0) + 1
    state_data["quiz_scores"][c_key][u_key] = current
    save_state()
    return current

# ═══════════════════════════════════════════════════════════════════════════════
#  بانکی مەتەڵ و یارییە بەکۆمەڵە کوردییەکان (Kurdish Quizzes & Games)
# ═══════════════════════════════════════════════════════════════════════════════

KURDISH_QUIZZES = [
    {
        "question": "چییە هەرچەند لێی ببەیت زۆرتر دەبێت؟",
        "answers": ["کەلێن", "چاڵ", "کون", "چال", "kelen", "chal"],
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
    }
]

def register_group(chat_id: int):
    if "groups" not in state_data:
        state_data["groups"] = []
    if chat_id not in state_data["groups"]:
        state_data["groups"].append(chat_id)
        save_state()

def clean_ai_text(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r'(?im)^\s*@?[a-zA-Z0-9_]+:\s*', '', text)
    clean = re.sub(r'(?im)^\s*(system note|translation note|note|translation)\s*[::-].*$', '', clean)
    clean = re.sub(r'\([^()\r\n]*\)', '', clean)
    if re.search(r'[\u0900-\u097F]', clean):
        return ""
    return clean.strip()

def get_smart_reply(text: str):
    lower = text.strip().lower()
    for entry in SMART_REPLIES:
        for p in entry["patterns"]:
            if p in lower:
                return random.choice(entry["replies"])
    return None

def get_ai_reply(chat_id: int, user_id: int, question: str) -> str:
    smart = get_smart_reply(question)
    if smart:
        return smart

    # 🌟 Try Google Gemini first (best Kurdish support)
    if GEMINI_API_KEY:
        for gem_model in ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-flash-lite-latest"]:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{gem_model}:generateContent?key={GEMINI_API_KEY}"
                body = {
                    "contents": [{"parts": [{"text": question}]}],
                    "systemInstruction": {"parts": [{"text": AI_SYSTEM_PROMPT}]},
                    "generationConfig": {"maxOutputTokens": 200, "temperature": 0.8}
                }
                r = requests.post(url, json=body, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        answer = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        answer = clean_ai_text(answer)
                        if answer:
                            return answer
                elif r.status_code == 429:
                    continue
            except Exception as e:
                print(f"Gemini Error ({gem_model}): {e}")

    # 🔄 Fallback to Groq
    if groq_client:
        try:
            res = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": AI_SYSTEM_PROMPT},
                    {"role": "user", "content": question}
                ],
                max_tokens=150,
                temperature=0.7
            )
            answer = res.choices[0].message.content
            answer = clean_ai_text(answer)
            if answer:
                return answer
        except Exception as e:
            print("Groq Error:", e)

    return "گیان دەتوانیت دووبارە ڕوونی بکەیتەوە؟ لە خزمەتدام! 🌸😊"

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
        res = tg_call("getFile", {"file_id": file_id})
        if not res or not res.get("ok"):
            return None, "image/jpeg"
        file_path = res["result"]["file_path"]
        ext = file_path.split(".")[-1].lower() if "." in file_path else "jpg"
        mime = "image/jpeg"
        if ext in ["png"]:
            mime = "image/png"
        elif ext in ["webp"]:
            mime = "image/webp"
        elif ext in ["gif"]:
            mime = "image/gif"
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return r.content, mime
    except Exception as e:
        print(f"Download file error: {e}")
    return None, "image/jpeg"

def check_nsfw_with_ai_vision(file_id: str) -> bool:
    """Use Gemini Vision to check if an image is NSFW."""
    img_bytes, mime_type = download_telegram_file(file_id)
    if not img_bytes or len(img_bytes) < 300:
        return False
    b64 = base64.b64encode(img_bytes).decode("utf-8")

    # 🌟 Try Google Gemini Vision (gemini-3.5-flash / gemini-3.5-flash-lite have full quota)
    if GEMINI_API_KEY:
        for gem_model in ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-flash-lite-latest"]:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{gem_model}:generateContent?key={GEMINI_API_KEY}"
                body = {
                    "contents": [{
                        "parts": [
                            {"text": "Analyze this image. Does it contain nudity, pornography, sexual acts, lingerie, exposed breasts, buttocks, genitalia, or explicit sexual content? Answer strictly with YES or NO in one word."},
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

    return False

def is_nsfw_sticker(sticker_obj: dict) -> bool:
    if not sticker_obj:
        return False
    set_name = (sticker_obj.get("set_name") or "").lower()
    emoji = sticker_obj.get("emoji") or ""
    
    # Check explicit 18+ emoji
    if "🔞" in emoji:
        return True

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
            return True
    
    # 🧠 AI Vision fallback: check actual sticker image content
    file_id = sticker_obj.get("file_id") or ""
    thumb = sticker_obj.get("thumbnail") or sticker_obj.get("thumb") or {}
    check_id = thumb.get("file_id") or file_id
    if check_id:
        if check_nsfw_with_ai_vision(check_id):
            print(f"🔞 AI Vision detected NSFW sticker: set={set_name}")
            return True
            
    return False

def is_nsfw_photo(msg: dict) -> bool:
    """Check if a photo message contains NSFW content using AI Vision."""
    photos = msg.get("photo")
    if not photos:
        return False
    # Use smallest photo size for faster download
    file_id = photos[0].get("file_id") or ""
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
    
    # 🧠 AI Vision fallback for GIFs/animations
    thumb = anim.get("thumbnail") or anim.get("thumb") or {}
    check_id = thumb.get("file_id") or anim.get("file_id") or ""
    if check_id:
        if check_nsfw_with_ai_vision(check_id):
            print(f"🔞 AI Vision detected NSFW animation/GIF")
            return True
            
    return False

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
    if any(k in msg for k in ["forward_date", "forward_from", "forward_from_chat", "forward_sender_name"]):
        return True
    return False

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

# ═══════════════════════════════════════════════════════════════════════════════
#  تایبەتمەندی پەخشی کاتژمێرە یەکسانەکان و کاتی بانگەکان (Background Scheduler)
# ═══════════════════════════════════════════════════════════════════════════════

def background_scheduler():
    """هەموو خولەکێک پشکنین دەکات بۆ کاتژمێرە یەکسانەکان و کاتی بانگەکان"""
    print("⏰ Background Clock & Prayer Scheduler Started!")
    last_sent_minute = ""

    while True:
        try:
            now = datetime.datetime.now(KURDISTAN_UTC_OFFSET)
            current_time = now.strftime("%H:%M")

            if current_time != last_sent_minute:
                # ١. کاتژمێرە یەکسانەکان (Mirror Hours بە کاتی ۱۰۰٪ یەکسان و قۆناغەکانی ڕۆژ)
                if config.get("enableMirrorHours", True) and current_time in MIRROR_HOURS_CONFIG:
                    item = MIRROR_HOURS_CONFIG[current_time]
                    time_label = item["time_label"]
                    quote = item["quote"]
                    msg_text = (
                        f"✨ <b>کاتژمێری یەکسان: {time_label}</b> 💫\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"❝ {quote} ❞"
                    )
                    for gid in state_data.get("groups", []):
                        send_message(gid, msg_text)
                    print(f"✨ Broadcasted mirror hour {current_time} ({time_label}) to groups")
                    last_sent_minute = current_time

                # ۲. کاتی بانگەکان و زیکر (Prayer Times)
                elif config.get("enablePrayerTimes", True) and current_time in PRAYER_SCHEDULE:
                    p_info = PRAYER_SCHEDULE[current_time]
                    p_msg = (
                        f"🕌 **کاتی {p_info['name']} بە کاتی کوردستان** 🕋\n\n"
                        f"📿 **زیکر و نزای ئەم کاتە:**\n{p_info['zikr']}\n\n"
                        f"اللَّهُمَّ صَلِّ عَلَىٰ مُحَمَّدٍ وَعَلَىٰ آلِ مُحَمَّدٍ 🌸"
                    )
                    for gid in state_data.get("groups", []):
                        send_message(gid, p_msg)
                    print(f"🕌 Broadcasted prayer time {current_time} ({p_info['name']}) to groups")
                    last_sent_minute = current_time

            time.sleep(20)
        except Exception as e:
            print("Scheduler Exception:", e)
            time.sleep(30)

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

    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].split("@")[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ["/start", "/setup"]:
        if chat.get("type") in ["group", "supergroup"]:
            register_group(chat_id)
            send_message(chat_id, f"🌸 سڵاو {display_name} گیان! من بوتی گاردنیام 🤖❤️\n\nئەم گروپە بە سەرکەوتوویی تۆمارکرا بۆ پەخشی خۆکاری کاتژمێرە یەکسانەکان، کاتی بانگەکان، پاراستنی ئاسایش و وەڵامدانەوەی AI! ✨🥰", msg_id, thread_id)
        else:
            send_message(chat_id, f"🌸 سڵاو {display_name} گیان! من بوتی گاردنیام 🤖❤️\n\nئەرکی من پاراستنی ئاسایشی گروپ، پێشوازی لە ئەندامان، پەخشی کاتژمێرە یەکسانەکان، کاتی بانگەکان و وەڵامدانەوەی پرسیارەکانە بە ژیریی دەستکرد! ✨🥰", msg_id, thread_id)
        return
    elif cmd == "/help":
        help_text = (
            "📋 **لیستی تەواوی فرمانەکانی بوتی گاردنیا:**\n\n"
            "🔹 **فرمانە گشتییەکان:**\n"
            "• `/id` - پیشاندانی ئایدی چات و بەکارهێنەر\n"
            "• `/rules` - پیشاندانی یاساکانی گروپ\n"
            "• `/game` یان `/quiz` - دەستپێکردنی مەتەڵ و یاریی بەکۆمەڵ 🎮\n"
            "• `/points` - پیشاندانی خاڵەکانی یاری و ڕیزبەندی 🏆\n\n"
            "🛡️ **فرمانەکانی ئەدمین:**\n"
            "• `/lock` - قوفڵکردنی گروپ (بۆ کاتی خەو) 🔒\n"
            "• `/unlock` - کردنەوەی قوفڵی گروپ 🔓\n"
            "• `/purge 20` - پاککردنەوەی چات بە کۆمەڵ 🧹\n"
            "• `/del` - سڕینەوەی پەیامی دیاریکراو (بە ڕیپڵای) 🗑️\n"
            "• `/warn` - ئاگادارکردنەوەی بەکارهێنەر (بە ڕیپڵای)\n"
            "• `/warnings` - پیشاندانی ژمارەی ئاگادارییەکان\n"
            "• `/clearwarnings` - سڕینەوەی ئاگادارییەکان\n"
            "• `/mute 10m` - بێدەنگکردن بۆ ماوەیەک (10m, 1h, 1d)\n"
            "• `/unmute` - لادانی بێدەنگی لەسەر بەکارهێنەر\n"
            "• `/ban` - باندکردنی بەکارهێنەر لە گروپ\n"
            "• `/unban <user_id>` - لادانی باند بە پێدانی ئایدی\n"
            "• `/setrules <دەق>` - دانانی یاساکانی گروپ 🌸"
        )
        send_message(chat_id, help_text, msg_id, thread_id)
        return
    elif cmd == "/id":
        send_message(chat_id, f"🆔 ئایدی ئەم چاتە: `{chat_id}`\n👤 ئایدی تۆ: `{user_id}` ✨", msg_id, thread_id)
        return
    elif cmd == "/rules":
        c_key = str(chat_id)
        rules = state_data.get("rules", {}).get(c_key)
        if rules:
            send_message(chat_id, f"📜 **یاساکانی گروپ:**\n\n{rules} 🌸", msg_id, thread_id)
        else:
            send_message(chat_id, "ℹ️ یاسایەکی تایبەت بۆ ئەم گروپە دانەنراوە ✨", msg_id, thread_id)
        return
    elif cmd in ["/game", "/quiz"]:
        q = random.choice(KURDISH_QUIZZES)
        if "active_quiz" not in state_data:
            state_data["active_quiz"] = {}
        state_data["active_quiz"][str(chat_id)] = {
            "question": q["question"],
            "answers": [a.lower() for a in q["answers"]],
            "display_answer": q["display_answer"],
            "time": time.time()
        }
        save_state()
        quiz_msg = (
            f"🎮 **مەتەڵ و یاریی گاردنیا:**\n\n"
            f"❓ **{q['question']}**\n\n"
            f"💡 کێ یەکەم کەس دەتوانێت وەڵامەکەی لە چات بنووسێت بۆ بەدەستهێنانی خاڵ؟ 🏆✨"
        )
        send_message(chat_id, quiz_msg, 0, thread_id)
        return
    elif cmd in ["/points", "/score", "/scores"]:
        c_key = str(chat_id)
        scores = state_data.get("quiz_scores", {}).get(c_key, {})
        my_pts = scores.get(str(user_id), 0)
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
        board = f"🏆 **ڕیزبەندیی پاڵەوانانی یاری لەم گروپەدا:**\n\n"
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        if sorted_scores:
            for idx, (uid, pts) in enumerate(sorted_scores):
                board += f"{medals[idx]} بەکارهێنەر `{uid}`: **{pts} خاڵ**\n"
        else:
            board += "تائێستا کەس خاڵی تۆمار نەکردووە! یەکەم کەس بە بە فەرمانی `/game` 🎮\n"
        board += f"\n👤 خاڵەکانی تۆ ({display_name}): **{my_pts} خاڵ** 🌟"
        send_message(chat_id, board, msg_id, thread_id)
        return

    # 🛡️ تەنها بۆ ئەدمینەکان
    if not is_admin(chat_id, user_id):
        send_message(chat_id, "⚠️ تەنها ئەدمینەکانی گروپ دەتوانن ئەم فرمانە بەکاربهێنن! 🌸", msg_id, thread_id)
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

def handle_new_member(chat_id: int, user: dict, msg_id: int = 0, thread_id: int = 0):
    if not user or user.get("is_bot"):
        return
    
    m_first = html.escape(user.get("first_name", "ئازیز"))
    m_user = user.get("username")
    username_display = f"@{html.escape(m_user)}" if m_user else "یوزەری نییە"
    
    welcome_caption = (
        f"🎉 <b>بەخێربێیت بۆ گروپی پات و مات</b> 🏰✨\n"
        f"🌸 دووربە لە هەموو کێشەیەک 🌸\n"
        f"ئازیز سەیری یاساکان بکە هەتا دووربیت لە هەر کێشەیەک 📜✨\n\n"
        f"👤 <b>ناوت:</b> {m_first} 👑\n"
        f"🏷️ <b>یوزەرت:</b> {username_display}\n\n"
        f"👇🏻👇🏻 <b>چەناڵی پات و مات:</b>\n"
        f"@mshell9 👑✨\n\n"
        f"👇🏻👇🏻 <b>ئۆنەری پات و مات:</b>\n"
        f"خاتوو <b>𝒢𝒶𝓇𝒹𝓃𝓎𝒶</b> 🌸👑"
    )
    
    pat_mat_img = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pat_mat.jpg")
    send_photo(chat_id, pat_mat_img, welcome_caption, msg_id, thread_id)
    print(f"👋 Sent Pat & Mat welcome card to: {m_first} ({username_display}) in chat {chat_id}")

def handle_chat_member_update(data: dict):
    if not data:
        return
    chat = data.get("chat", {})
    chat_id = chat.get("id")
    if not chat_id:
        return
    
    if chat.get("type") in ["group", "supergroup"]:
        register_group(chat_id)
        
    old_status = data.get("old_chat_member", {}).get("status")
    new_member_obj = data.get("new_chat_member", {})
    new_status = new_member_obj.get("status")
    user = new_member_obj.get("user", {})
    
    # User joined the group via link, invite, or direct join
    if old_status in ["left", "kicked", "restricted"] and new_status in ["member", "administrator"]:
        print(f"👋 chat_member join detected in {chat_id}: {user.get('first_name')}")
        handle_new_member(chat_id, user)

# ═══════════════════════════════════════════════════════════════════════════════
#  چاودێری و پاراستنی نامەکان (Message Handling & Security Engine)
# ═══════════════════════════════════════════════════════════════════════════════

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

    # Register group for broadcasts
    if chat_type in ["group", "supergroup"]:
        register_group(chat_id)

    text = msg.get("text") or msg.get("caption") or ""
    print(f"📩 [{chat_type.upper()}] {display_name} (ID: {user_id}): {text if text else '[Media/Sticker/Other]'}")

    # 🌸 بەخێرهاتنی ئەندامانی نوێ و دژە-بۆت (Anti-Bot)
    if "new_chat_members" in msg:
        for member in msg["new_chat_members"]:
            if member.get("is_bot"):
                # ئەگەر بۆت بوو و ئەو کەسەی زیادی کردووە ئەدمین نەبوو ➔ دەرکردنی بۆت
                if not is_admin(chat_id, user_id):
                    ban_user(chat_id, member["id"])
                    unban_user(chat_id, member["id"])
                    delete_message(chat_id, msg_id)
                    send_message(chat_id, f"🚫 {display_name} ناتوانیت بۆت زیاد بکەیت! تەنها ئەدمین مۆڵەتی هەیە ⚠️", 0, thread_id)
                    print(f"🤖 Anti-Bot: Kicked unauthorized bot {member.get('id')} added by {display_name}")
                continue
            
            handle_new_member(chat_id, member, msg_id, thread_id)

    # فرمانەکان
    if text.startswith("/"):
        print(f"⚡ Executing command: {text} from {display_name}")
        handle_command(msg, text)
        return

    # چاتی تایبەت (Private Chat AI)
    if chat_type == "private":
        if config.get("aiInPrivateChats", True) and text:
            reply = get_ai_reply(chat_id, user_id, text)
            if reply:
                send_message(chat_id, reply, msg_id)
                print(f"🤖 [PV] Replied to {display_name}: {reply}")
        return

    # 🛡️ پشکنینی سکوریتی توند بۆ هەموو نامەکان (ستیکەر، گیف، وێنە، ڤیدیۆ)
    violation = ""
    is_user_admin = is_admin(chat_id, user_id)

    # ١. پشکنینی ستیکەری سێکسی بە AI Vision (تەنانەت ئەگەر ئەدمینیش بێت)
    if config.get("blockNSFWStickers", True) and "sticker" in msg and is_nsfw_sticker(msg["sticker"]):
        violation = "ناردنی ستیکەری نەشیاو و سێکسی 🔞"
    # ۲. پشکنینی وێنەی سێکسی بە AI Vision
    elif "photo" in msg and is_nsfw_photo(msg):
        violation = "ناردنی وێنەی نەشیاو و سێکسی 🔞"
    # ۳. پشکنینی ڤیدیۆی سێکسی بە AI Vision
    elif ("video" in msg or "video_note" in msg):
        vid = msg.get("video") or msg.get("video_note") or {}
        thumb = vid.get("thumbnail") or vid.get("thumb") or {}
        check_id = thumb.get("file_id") or ""
        if check_id and check_nsfw_with_ai_vision(check_id):
            violation = "ناردنی ڤیدیۆی نەشیاو و سێکسی 🔞"
    # ٤. پشکنینی گیف و فایلی نەشیاو بە AI Vision
    elif config.get("blockNSFWGIFs", True) and ("animation" in msg or "document" in msg) and is_nsfw_animation_or_media(msg, text):
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

    # 🎭 کاتێک ئەندامێک ستیکەری ئاسایی دەنێرێت (وەڵامدانەوەی شیرین و پەیوەندیدار)
    if "sticker" in msg:
        should_stk_reply = True
        if "reply_to_message" in msg and msg["reply_to_message"]:
            target_user = msg["reply_to_message"].get("from", {})
            target_id = target_user.get("id", 0)
            is_target_bot = target_user.get("is_bot", False)
            if target_id != BOT_ID and not is_target_bot:
                should_stk_reply = False

        if should_stk_reply:
            stk_reply = get_sticker_comment(msg["sticker"])
            if stk_reply:
                send_message(chat_id, stk_reply, msg_id)
                print(f"🤖 Reacted to sticker from {display_name}: {stk_reply}")
                return

    # 🎮 پشکنینی وەڵامی مەتەڵ و یاری
    c_key = str(chat_id)
    if "active_quiz" in state_data and c_key in state_data["active_quiz"]:
        curr_quiz = state_data["active_quiz"][c_key]
        clean_ans = text.strip().lower()
        if any(ans in clean_ans for ans in curr_quiz.get("answers", [])):
            pts = add_user_quiz_point(chat_id, user_id)
            disp_ans = curr_quiz.get("display_answer", "")
            del state_data["active_quiz"][c_key]
            save_state()
            win_msg = (
                f"🎉 **ئافەرین {display_name} گیان! وەڵامەکەت دروستە!** 👏🌟\n\n"
                f"✅ **وەڵام:** {disp_ans}\n"
                f"🏆 **+١ خاڵت بەدەستهێنا!** کۆی گشتی خاڵەکانت: **{pts} خاڵ** ✨"
            )
            send_message(chat_id, win_msg, msg_id)
            print(f"🏆 Quiz winner in {chat_id}: {display_name} (Points: {pts})")
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
    while True:
        try:
            res = tg_call("getUpdates", {"offset": offset, "timeout": 30, "allowed_updates": ["message"]})
            if res and res.get("ok"):
                for update in res["result"]:
                    offset = update["update_id"] + 1
                    if "message" in update:
                        handle_message(update["message"])
        except Exception as e:
            print("Polling Exception:", e)
            time.sleep(5)

if __name__ == "__main__":
    main()
