"""Простая библиотека для уроков: управление роботом Robert RS01 из Python.

    from robert_sdk import Robert

    robot = Robert()            # подключается к Robert_ble
    robot.say("Привет! Я Роберт")
    robot.eyes(3)
    robot.forward(2)            # идти вперёд 2 секунды
    robot.hands()               # случайное движение руками
    robot.close()
"""

import random
import re
import sys
import time

import robot_ble as rb
from platform_compat import Speaker

# Номер цвета → название (проверено калибровкой: python robert_sdk.py colors)
COLOR_NAMES = {1: "тёмно-синий", 2: "голубой", 3: "зелёный", 4: "жёлтый",
               5: "красный", 6: "фиолетовый", 7: "белый"}


def pronounce(text):
    """Заменить слова, которые голос читает неправильно (словарь в phrases.py)."""
    try:
        from phrases import PRONUNCIATION
    except ImportError:
        return text
    for word, spoken in sorted(PRONUNCIATION.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", spoken, text, flags=re.IGNORECASE)
    return text


class Robert:
    def __init__(self, connect=True, speed=0, voice="Irina", speaker="Robert"):
        self._link = rb.BleLink(on_rx=lambda d: None, on_disconnect=lambda: None)
        self._speed = speed
        self._color = 2
        self._light = rb.LIGHT_ON
        self.speaker = Speaker(device_hint=speaker, voice_hint=voice)
        if connect:
            self.connect()

    # ---------- соединение ----------
    def connect(self):
        print("Ищу робота Robert…")
        addr = self._link.connect()
        print(f"Подключено: {addr}")
        return self

    def close(self):
        if self._link.connected:
            self.stop()
            time.sleep(0.2)
        self._link.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------- низкий уровень ----------
    def send(self, action, repeat=8):
        """Отправить действие по номеру. repeat=255 — повторять, пока не придёт другая команда."""
        self._link.write(rb.packet(action, repeat, self._speed, self._color, self._light))

    # ---------- ходьба ----------
    def _walk(self, action, seconds):
        self.send(action, 0xFF)
        if seconds:
            time.sleep(seconds)
            self.stop()

    def forward(self, seconds=1.0):
        self._walk(rb.FORWARD, seconds)

    def backward(self, seconds=1.0):
        self._walk(rb.BACKWARD, seconds)

    def left(self, seconds=1.0):
        self._walk(rb.LEFT, seconds)

    def right(self, seconds=1.0):
        self._walk(rb.RIGHT, seconds)

    def stop(self):
        self.send(rb.IDLE, 8)

    # ---------- танец ----------
    def _pick(self, rng, number):
        if number is None:
            return random.choice([n for n in rng if n != rb.IDLE])
        if number not in rng or number == rb.IDLE:
            raise ValueError(f"номер должен быть от {rng[0]} до {rng[-1]}")
        return number

    def hands(self, number=None):
        """Движение руками: 100–110, без номера — случайное."""
        n = self._pick(rb.HAND_RANGE, number)
        self.send(n)
        return n

    def legs(self, number=None):
        """Движение ногами: 200–235, без номера — случайное."""
        n = self._pick(rb.LEG_RANGE, number)
        self.send(n)
        return n

    def combo(self, number=None):
        """Комбинированное движение: 1–93, без номера — случайное."""
        n = self._pick(rb.COMBO_RANGE, number)
        self.send(n)
        return n

    def dance(self, seconds=10, step=2.0):
        """Случайный танец из разных движений."""
        end = time.time() + seconds
        while time.time() < end:
            random.choice([self.hands, self.legs, self.combo])()
            time.sleep(step)
        self.stop()

    def speed(self, level):
        """Скорость движений 0–3."""
        if level not in range(4):
            raise ValueError("скорость от 0 до 3")
        self._speed = level

    # ---------- глаза ----------
    def eyes(self, color=None, light=True):
        """Цвет глаз 1–7 (или название из COLOR_NAMES), light=False — выключить подсветку."""
        if isinstance(color, str):
            names = {v: k for k, v in COLOR_NAMES.items()}
            if color not in names:
                raise ValueError(f"неизвестный цвет «{color}», есть: {list(names)}")
            color = names[color]
        if color is not None:
            if color not in range(1, 8):
                raise ValueError("цвет от 1 до 7")
            self._color = color
        self._light = rb.LIGHT_ON if light else rb.LIGHT_OFF
        self.stop()

    def light_mode(self, mode):
        """Режим подсветки как байт протокола (0 — вкл, 4 — выкл, остальные — эксперимент)."""
        self._light = mode
        self.stop()

    # ---------- голос (Windows — Irina, Mac — русский голос macOS) ----------
    def say(self, text, gesture=True, rate=0, volume=100, stop_event=None):
        """Произнести текст через динамик робота (с жестом руками)."""
        if gesture and self._link.connected:
            self.hands()
        self.speaker.speak(pronounce(text), rate, volume, stop_event)

    def wait(self, seconds):
        time.sleep(seconds)


def _calibrate_colors():
    with Robert() as r:
        for c in range(1, 8):
            r.eyes(c)
            r.say(f"Цвет номер {c}", gesture=False)
            time.sleep(2)
        for mode in range(0, 6):
            r.light_mode(mode)
            r.say(f"Режим подсветки {mode}", gesture=False)
            time.sleep(3)
        r.light_mode(rb.LIGHT_ON)


if __name__ == "__main__":
    if sys.argv[1:] == ["colors"]:
        _calibrate_colors()
    else:
        with Robert() as r:
            r.eyes(3)
            r.say("Привет! Я робот Роберт. Давайте изучать искусственный интеллект вместе!")
            r.dance(seconds=6)
