@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Сначала выполните установку: setup_windows.bat
  pause
  exit /b 1
)
set PY=.venv\Scripts\python.exe
set PYW=.venv\Scripts\pythonw.exe
%PY% voice_control.py
pause
