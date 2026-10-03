@echo off
rem ASCII only: cmd misreads Cyrillic lines in UTF-8 batch files. Russian messages come from local_server.py.
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Robert local

set "PY="
if exist .venv\Scripts\python.exe set "PY=.venv\Scripts\python.exe"
if not defined PY (where py >nul 2>nul && set "PY=py -3")
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo Python not found / Python ne nayden.
  echo Install Python 3.11 or 3.12: https://www.python.org/downloads/windows/
  echo Tick "Add python.exe to PATH" during install, then run this file again.
  pause
  exit /b 1
)

%PY% local_server.py %*
pause
