@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Установка программы «Роберт»…
echo.

set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY (where python >nul 2>nul && set PY=python)
if not defined PY (
  echo Не найден Python. Установите Python 3.11 или 3.12 с https://www.python.org/downloads/windows/
  echo При установке поставьте галочку «Add python.exe to PATH», затем запустите этот файл снова.
  pause
  exit /b 1
)

if not exist .venv\Scripts\python.exe (
  echo Создаю окружение .venv…
  %PY% -m venv .venv || (echo Не удалось создать окружение & pause & exit /b 1)
)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt || (echo Ошибка установки библиотек — проверьте интернет и запустите снова & pause & exit /b 1)

echo.
echo Готово! Программы запускаются двойным щелчком:
echo   mentor_panel.bat  — панель ментора и Teachable Machine
echo   start.bat         — пульт управления
echo   voice.bat         — голосовое управление
echo   gestures.bat      — управление жестами
echo   rps.bat           — камень-ножницы-бумага
echo   lesson_start.bat  — приветствие перед уроком
pause
