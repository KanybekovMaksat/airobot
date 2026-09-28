#!/bin/bash
# Голосовое управление
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Сначала выполните установку: bash setup_mac.command"
  read -n 1 -s -r -p "Нажмите любую клавишу…"
  exit 1
fi
.venv/bin/python voice_control.py "$@"
