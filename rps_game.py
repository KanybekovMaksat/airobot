"""Урок: камень-ножницы-бумага с роботом Robert.

Камера + MediaPipe находят 21 точку руки → по выпрямленным пальцам узнаём ход игрока.
У Роберта два режима:
  • случайный — выбирает наугад;
  • умный — запоминает, какой ход игрок делает после предыдущего, и пытается угадать следующий.
Клавиши: ПРОБЕЛ — новый раунд, M — сменить режим, R — сбросить счёт, Q/Esc — выход.
"""

import math
import queue
import random
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
from PIL import Image, ImageDraw

from platform_compat import load_font, open_camera
from robert_sdk import Robert

HERE = Path(__file__).parent
MODEL_PATH = HERE / "models" / "gesture_recognizer.task"

ROCK, SCISSORS, PAPER = "камень", "ножницы", "бумага"
BEATS = {ROCK: SCISSORS, SCISSORS: PAPER, PAPER: ROCK}  # кто кого побеждает
COUNTER = {loser: winner for winner, loser in BEATS.items()}  # чем побить ход
EYE_COLOR = {ROCK: 1, SCISSORS: 3, PAPER: 2}


# ---------- 1. Как узнать ход игрока по точкам руки ----------
def distance(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def finger_is_straight(hand, tip, joint):
    """Палец выпрямлен, если его кончик дальше от запястья (точка 0), чем сустав."""
    wrist = hand[0]
    return distance(hand[tip], wrist) > distance(hand[joint], wrist) * 1.1


def recognize_move(hand):
    fingers = [finger_is_straight(hand, tip, joint)
               for tip, joint in [(8, 6), (12, 10), (16, 14), (20, 18)]]  # указательный…мизинец
    count = sum(fingers)
    if count <= 1:
        return ROCK
    if fingers[0] and fingers[1] and not fingers[2] and not fingers[3]:
        return SCISSORS
    if count >= 3:
        return PAPER
    return None


# ---------- 2. «Умный» Роберт: учится на ходах игрока ----------
class Predictor:
    """Считает, какой ход игрок обычно делает после каждого своего хода (цепь Маркова)."""

    def __init__(self):
        self.after = defaultdict(Counter)  # after[прошлый ход][следующий ход] = сколько раз
        self.history = []

    def learn(self, move):
        if self.history:
            self.after[self.history[-1]][move] += 1
        self.history.append(move)

    def guess(self):
        """Угадываем следующий ход игрока; если данных мало — самый частый ход вообще."""
        if self.history and self.after[self.history[-1]]:
            return self.after[self.history[-1]].most_common(1)[0][0]
        if self.history:
            return Counter(self.history).most_common(1)[0][0]
        return None


# ---------- робот ----------
robot = Robert(connect=False)
speech = queue.Queue()


def say(text):
    speech.put(text)


def speech_worker():
    while True:
        text = speech.get()
        try:
            robot.say(text, gesture=False)
        except Exception as e:
            print("Голос:", e)


def robot_do(fn, *args):
    if robot._link.connected:
        try:
            fn(*args)
        except Exception as e:
            print("Робот:", e)


# ---------- рисование ----------
HAND_CONNECTIONS = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
                    (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16),
                    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20)]
FONT = load_font(18)
FONT_MID = load_font(26, bold=True)
FONT_HUGE = load_font(110, bold=True)


def draw_hand(frame, hand):
    h, w = frame.shape[:2]
    pts = [(int(p.x * w), int(p.y * h)) for p in hand]
    for a, b in HAND_CONNECTIONS:
        cv2.line(frame, pts[a], pts[b], (255, 255, 255), 2)
    for i, p in enumerate(pts):
        cv2.circle(frame, p, 6 if i in (4, 8, 12, 16, 20) else 4, (60, 120, 255), -1)


def render(frame, g):
    h, w = frame.shape[:2]
    pw = 340
    canvas = np.zeros((h, w + pw, 3), dtype=np.uint8)
    canvas[:, :w] = frame
    canvas[:, w:] = (32, 26, 22)
    img = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(img)
    x = w + 16

    conn = robot._link.connected
    d.text((x, 10), "Робот подключён" if conn else "Робот не подключён (демо)", font=FONT,
           fill=(90, 220, 120) if conn else (240, 150, 60))
    d.text((x, 40), f"Вы {g['score'][0]} : {g['score'][1]} Роберт", font=FONT_MID, fill=(255, 255, 255))
    d.text((x, 76), f"Ничьих: {g['score'][2]}", font=FONT, fill=(190, 190, 190))
    mode = "умный (учится)" if g["smart"] else "случайный"
    d.text((x, 108), f"Режим Роберта: {mode}", font=FONT, fill=(120, 170, 255))
    if g["smart"]:
        guess = g["predictor"].guess()
        d.text((x, 134), f"Ваших ходов в памяти: {len(g['predictor'].history)}", font=FONT, fill=(190, 190, 190))
        d.text((x, 158), f"Роберт ожидает: {guess or '— пока не знает'}", font=FONT, fill=(190, 190, 190))
    y = 200
    for line in g["log"][-6:]:
        d.text((x, y), line, font=FONT, fill=(210, 210, 210))
        y += 26
    d.text((x, h - 58), "Пробел — раунд   M — режим", font=FONT, fill=(150, 150, 150))
    d.text((x, h - 32), "R — сбросить счёт   Q — выход", font=FONT, fill=(150, 150, 150))

    # низ кадра: что видит камера
    d.rectangle((0, h - 40, w, h), fill=(0, 0, 0))
    seen = g["seen"] or "руку не видно"
    d.text((12, h - 34), f"Вижу: {seen}", font=FONT, fill=(255, 255, 255))

    # крупная надпись по центру кадра
    if g["big"]:
        tw = d.textlength(g["big"], font=FONT_HUGE if len(g["big"]) < 4 else FONT_MID)
        font = FONT_HUGE if len(g["big"]) < 4 else FONT_MID
        d.text(((w - tw) / 2, h / 2 - (70 if font is FONT_HUGE else 20)), g["big"], font=font,
               fill=(255, 230, 80), stroke_width=3, stroke_fill=(0, 0, 0))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


# ---------- раунд игры ----------
def robot_choice(g):
    if g["smart"]:
        guess = g["predictor"].guess()
        if guess:
            return COUNTER[guess]  # бьём ход, который ожидаем от игрока
    return random.choice([ROCK, SCISSORS, PAPER])


def finish_round(g, player):
    bot = robot_choice(g)
    g["predictor"].learn(player)
    robot_do(robot.eyes, EYE_COLOR[bot])
    if player == bot:
        g["score"][2] += 1
        result, phrase = "Ничья", f"У меня тоже {bot}. Ничья!"
        robot_do(robot.hands)
    elif BEATS[player] == bot:
        g["score"][0] += 1
        result, phrase = "Вы победили", f"У меня {bot}. Эх, вы победили!"
        robot_do(robot.legs)
    else:
        g["score"][1] += 1
        result, phrase = "Роберт победил", f"У меня {bot}! Я победил!"
        robot_do(robot.combo)
    g["log"].append(f"{player} vs {bot} — {result}")
    g["big"] = f"{player} vs {bot}: {result}"
    say(phrase)


def main():
    threading.Thread(target=speech_worker, daemon=True).start()
    threading.Thread(target=_connect, daemon=True).start()

    options = vision.GestureRecognizerOptions(
        base_options=mp_python.BaseOptions(model_asset_buffer=MODEL_PATH.read_bytes()),
        running_mode=vision.RunningMode.VIDEO, num_hands=1)
    recognizer = vision.GestureRecognizer.create_from_options(options)
    cap = open_camera(0)
    window = "Robert - rock paper scissors"
    cv2.namedWindow(window)

    g = {"score": [0, 0, 0], "smart": False, "predictor": Predictor(), "log": [],
         "seen": None, "big": "Нажмите пробел", "round_start": None, "votes": []}
    start = time.time()
    say("Сыграем в камень, ножницы, бумага? Нажмите пробел, чтобы начать.")

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Камера не отдаёт изображение")
            break
        frame = cv2.flip(frame, 1)
        result = recognizer.recognize_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)),
            int((time.time() - start) * 1000))
        move = None
        if result.hand_landmarks:
            hand = result.hand_landmarks[0]
            draw_hand(frame, hand)
            move = recognize_move(hand)
        g["seen"] = move

        # отсчёт: 3 — 2 — 1 — показывайте! Затем 0.6 с собираем «голоса» кадров
        if g["round_start"] is not None:
            t = time.time() - g["round_start"]
            if t < 3:
                g["big"] = str(3 - int(t))
            elif t < 3.6:
                g["big"] = "Показывайте!"
                if move:
                    g["votes"].append(move)
            else:
                g["round_start"] = None
                if g["votes"]:
                    finish_round(g, Counter(g["votes"]).most_common(1)[0][0])
                else:
                    g["big"] = "Не увидел руку :("
                    say("Я не увидел вашу руку. Давайте ещё раз!")

        cv2.imshow(window, render(frame, g))
        key = cv2.waitKey(1) & 0xFF
        if key == ord(" ") and g["round_start"] is None:
            g["round_start"], g["votes"] = time.time(), []
            say("Камень, ножницы, бумага!")
            robot_do(robot.hands)
        elif key in (ord("m"), ord("M")):
            g["smart"] = not g["smart"]
            say("Теперь я буду учиться на ваших ходах!" if g["smart"] else "Теперь я играю наугад.")
        elif key in (ord("r"), ord("R")):
            g.update(score=[0, 0, 0], predictor=Predictor(), log=[], big="Счёт сброшен")
        elif key in (ord("q"), ord("Q"), 27) or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
            break

    cap.release()
    cv2.destroyAllWindows()
    robot.close()


def _connect():
    try:
        robot.connect()
    except Exception as e:
        print(f"Робот не найден, играем в демо-режиме: {e}")


if __name__ == "__main__":
    main()
