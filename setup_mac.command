#!/bin/bash
# Установка проекта «Роберт» на Mac. Запуск один раз: bash setup_mac.command
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Нет Python 3. Установите его с https://www.python.org/downloads/macos/ (версия 3.11 или 3.12) и запустите снова."
  exit 1
fi

echo "Создаю окружение .venv…"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

chmod +x *.command
echo
echo "Готово! Теперь программы запускаются двойным щелчком по файлам .command:"
ls -1 *.command | grep -v setup_mac
echo
echo "При первом запуске macOS спросит доступ к Bluetooth, камере и микрофону — разрешите."
