@echo off
rem VERITAS 查证台后端守护脚本
rem 检测 8000 端口：已在监听则直接退出；否则拉起 uvicorn，
rem 配合「每 5 分钟」的计划任务，服务被杀后最多 5 分钟自动恢复。
cd /d "D:\jqw33\Documents\68\backend"

netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if %errorlevel%==0 exit /b 0

".venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000
