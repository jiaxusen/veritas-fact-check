@echo off
rem 开机自启：后端看门狗 + 隧道看门狗
start "" /min "D:\jqw33\Documents\68\backend\.venv\Scripts\python.exe" "D:\jqw33\Documents\68\watchdog.py"
start "" /min "D:\jqw33\Documents\68\backend\.venv\Scripts\python.exe" "D:\jqw33\Documents\68\tunnel_watchdog.py"
