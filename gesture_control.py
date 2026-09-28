"""Урок: управление роботом Robert жестами (компьютерное зрение, MediaPipe).

Камера → MediaPipe находит руку (21 точка) и узнаёт жест → робот выполняет команду.
Чтобы поменять реакцию на жест, отредактируйте словарь GESTURES ниже.
Выход — клавиша Q или Esc.
"""

import queue
import random
import threading
import time
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
MIN_SCORE = 0.6  # насколько модель должна быть уверена в жесте
HOLD_FRAMES = 8  # сколько кадров подряд держать жест (~0.3 с), чтобы он сработал

robot = Robert(connect=False)
speech = queue.Queue(maxsize=1)
color = 2


# ---------- что делает робот ----------
def say(text):
    """Говорить в отдельном потоке, чтобы видео не зависало."""
    try:
        speech.put_nowait(text)
    except queue.Full:
        pass  # робот ещё говорит — пропускаем


def hello():
    robot.hands()
    say("Привет!")


def dance():
    robot.combo()
    say(random.choice(["Класс!", "Супер!", "Танцую!"]))


def love():
    global color
    color = color % 7 + 1
    robot.eyes(color)
    say("Я тоже вас люблю!")


# Жест MediaPipe → (название на экране, действие, идти пока держишь жест?)
GESTURES = {
    "Closed_Fist": ("Кулак — стоп", robot.stop, False),
    "Open_Palm": ("Ладонь — привет", hello, False),
    "Pointing_Up": ("Палец вверх — вперёд", lambda: robot.forward(0), True),
    "Thumb_Down": ("Большой палец вниз — назад", lambda: robot.backward(0), True),
    "Thumb_Up": ("Лайк — танец", dance, False),
    "Victory": ("Победа (V) — ноги", robot.legs, False),
    "ILoveYou": ("Рок-жест — цвет глаз", love, False),
}


# ---------- рисование ----------
HAND_CONNECTIONS = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
                    (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16),
                    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20)]
FONT = load_font(18)
FONT_BIG = load_font(26, bold=True)


def draw_hand(frame, landmarks):
    h, w = frame.shape[:2]
    pts = [(int(p.x * w), int(p.y * h)) for p in landmarks]
    for a, b in HAND_CONNECTIONS:
        cv2.line(frame, pts[a], pts[b], (255, 255, 255), 2)
    for i, p in enumerate(pts):
        cv2.circle(frame, p, 6 if i in (4, 8, 12, 16, 20) else 4, (60, 120, 255), -1)


def draw_panel(frame, current, score, action_text, connected):
    """Надписи по-русски (OpenCV не умеет кириллицу, поэтому через Pillow)."""
    h, w = frame.shape[:2]
    panel_w = 330
    canvas = np.zeros((h, w + panel_w, 3), dtype=np.uint8)
    canvas[:, :w] = frame
    canvas[:, w:] = (32, 26, 22)
    img = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(img)

    status = "Робот подключён" if connected else "Робот не подключён (демо)"
    d.text((w + 16, 12), status, font=FONT, fill=(90, 220, 120) if connected else (240, 150, 60))
    d.text((w + 16, 44), "Жесты:", font=FONT_BIG, fill=(230, 230, 230))
    y = 84
    for name, (label, _, _) in GESTURES.items():
        active = name == current
        if active:
            d.rounded_rectangle((w + 8, y - 4, w + panel_w - 8, y + 26), 6, fill=(60, 110, 240))
        d.text((w + 16, y), label, font=FONT, fill=(255, 255, 255) if active else (190, 190, 190))
        y += 34

    d.rectangle((0, h - 44, w, h), fill=(0, 0, 0))
    if current:
        d.text((12, h - 38), f"{current}  {score:.0%}   {action_text}", font=FONT, fill=(255, 255, 255))
    else:
        d.text((12, h - 38), "Покажите руку в камеру", font=FONT, fill=(200, 200, 200))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


# ---------- фоновые потоки ----------
def speech_worker():
    while True:
        robot.say(speech.get(), gesture=False)


def connect_worker(state):
    try:
        robot.connect()
        state["connected"] = True
    except Exception as e:
        print(f"Робот не найден, работаем в демо-режиме: {e}")


def main():
    state = {"connected": False}
    threading.Thread(target=speech_worker, daemon=True).start()
    threading.Thread(target=connect_worker, args=(state,), daemon=True).start()

    options = vision.GestureRecognizerOptions(
        base_options=mp_python.BaseOptions(model_asset_buffer=MODEL_PATH.read_bytes()),
        running_mode=vision.RunningMode.VIDEO, num_hands=1)
    recognizer = vision.GestureRecognizer.create_from_options(options)

    cap = open_camera(0)
    window = "Robert - gestures"
    cv2.namedWindow(window)
    start = time.time()
    recent = []  # последние распознанные жесты
    active = None  # жест, который сейчас сработал
    action_text = ""

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Камера не отдаёт изображение")
            break
        frame = cv2.flip(frame, 1)  # зеркально, как в зеркале

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = recognizer.recognize_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), int((time.time() - start) * 1000))

        name, score = None, 0.0
        if result.gestures:
            top = result.gestures[0][0]
            if top.score >= MIN_SCORE and top.category_name in GESTURES:
                name, score = top.category_name, top.score
            draw_hand(frame, result.hand_landmarks[0])

        # жест срабатывает, только если продержался HOLD_FRAMES кадров подряд
        recent = (recent + [name])[-HOLD_FRAMES:]
        stable = name if len(recent) == HOLD_FRAMES and recent.count(name) == HOLD_FRAMES else active
        if stable != active:
            if active and GESTURES[active][2] and state["connected"]:
                robot.stop()  # отпустили жест ходьбы — остановиться
            active = stable
            if active:
                label, action, _ = GESTURES[active]
                action_text = "→ " + label.split("— ")[-1]
                if state["connected"]:
                    try:
                        action()
                    except Exception as e:
                        action_text = f"ошибка: {e}"
            else:
                action_text = ""

        cv2.imshow(window, draw_panel(frame, name, score, action_text, state["connected"]))
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), ord("Q"), 27) or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
            break

    cap.release()
    cv2.destroyAllWindows()
    robot.close()


if __name__ == "__main__":
    main()
