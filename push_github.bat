@echo off
chcp 65001 >nul
rem ============================================
rem  VERITAS 查证台 · GitHub 一键推送
rem  用法：双击运行，粘贴你的仓库地址后回车
rem ============================================
cd /d "D:\jqw33\Documents\68"

echo.
echo   仓库已就绪：49 个文件，分支 main
echo.
echo   请先到 https://github.com/new 建好空仓库
echo   （仓库名建议 veritas-fact-check，不要勾选 README / license / .gitignore）
echo.
set /p REPO=   粘贴仓库地址（如 https://github.com/jiaxusen/veritas-fact-check.git）：

if "%REPO%"=="" (
  echo   未输入地址，已取消。
  pause
  exit /b 1
)

echo.
echo   正在推送...
git remote remove origin 2>nul
git remote add origin "%REPO%"
git push -u origin main

if errorlevel 1 (
  echo.
  echo   推送失败。常见原因：
  echo     1. 仓库地址写错，或仓库还没建
  echo     2. 没登录 —— 弹出窗口时选 Browser 登录即可
  echo     3. 仓库不是空的（勾了 README）—— 先执行 git pull --rebase origin main
  pause
  exit /b 1
)

echo.
echo   推送成功。
echo.
echo   接下来填表单的两项：
echo.
echo   代码仓库  = %REPO%
echo.
set RAW=%REPO:https://github.com/=%
set RAW=%RAW:.git=%
echo   封面直链  = https://raw.githubusercontent.com/%RAW%/main/submission/cover.png
echo.
echo   演示地址  = https://combat-bloggers-districts-nails.trycloudflare.com
echo   访问口令  = VERITAS-2026
echo.
pause
