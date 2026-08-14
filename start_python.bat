@echo off
title Gardnya Telegram Bot (Python)
echo ==============================================
echo   Gardnya Telegram Bot (Python Engine)
echo ==============================================

if exist "python\python.exe" (
    "python\python.exe" main_bot.py
) else if exist "..\bot_telegram\python\python.exe" (
    "..\bot_telegram\python\python.exe" main_bot.py
) else (
    python main_bot.py
)

pause
