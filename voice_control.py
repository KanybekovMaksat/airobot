"""Урок: голосовое управление роботом Robert.

Микрофон ноутбука → распознавание речи (Vosk, без интернета) → команда роботу.
Чтобы добавить свою команду, допишите строку в список COMMANDS внизу.
"""

import json
import os
import queue
import random
import threading
from pathlib import Path

import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel

import phrases
from robert_sdk import Robert

# Vosk не открывает пути с русскими буквами, поэтому работаем из папки проекта
os.chdir(Path(__file__).parent)
MODEL_PATH = "models/vosk-model-small-ru-0.22"
SAMPLE_RATE = 16000
WALK_SECONDS = 3  # сколько идти по команде, если не сказали «стоп»

robot = Robert()
audio = queue.Queue()
speaking = threading.Event()
walk_timer = None
color = 2


# ---------- действия робота ----------
def walk(step):
    """Начать идти и остановиться через WALK_SECONDS секунд."""
    global walk_timer
    if walk_timer:
        walk_timer.cancel()
    step(0)  # 0 — идти, пока не придёт другая команда
    walk_timer = threading.Timer(WALK_SECONDS, robot.stop)
    walk_timer.start()


def stop():
    if walk_timer:
        walk_timer.cancel()
    robot.stop()


def next_color():
    global color
    color = color % 7 + 1
    robot.eyes(color)


def faster():
    robot.speed(min(robot._speed + 1, 3))
    say(f"Скорость {robot._speed}")


def slower():
    robot.speed(max(robot._speed - 1, 0))
    say(f"Скорость {robot._speed}")


def say(text):
    """Говорим через динамик робота, а микрофон на это время не слушаем."""
    speaking.set()
    robot.say(text)
    speaking.clear()


def say_random(options):
    say(random.choice(options))


def goodbye():
    say("Пока! Было весело.")
    raise SystemExit


# ---------- команды: (слова, которые можно сказать) → действие ----------
COMMANDS = [
    (["вперёд", "вперед", "иди"], lambda: walk(robot.forward)),
    (["назад"], lambda: walk(robot.backward)),
    (["налево", "влево"], lambda: walk(robot.left)),
    (["направо", "вправо"], lambda: walk(robot.right)),
    (["стоп", "стой", "хватит"], stop),
    (["танцуй", "потанцуй", "танец"], robot.combo),
    (["руки", "помаши"], robot.hands),
    (["ноги"], robot.legs),
    (["привет", "здравствуй"], lambda: say_random(phrases.GREETING)),
    (["как тебя зовут", "представься", "кто ты"], lambda: say_random(phrases.ABOUT)),
    (["начинаем урок", "начало урока"], lambda: say_random(phrases.LESSON_START)),
    (["молодцы", "молодец"], lambda: (robot.combo(), say_random(phrases.PRAISE))),
    (["шутка", "пошути"], lambda: say_random(phrases.JOKES)),
    (["конец урока", "урок окончен"], lambda: say_random(phrases.LESSON_END)),
    (["цвет", "смени цвет"], next_color),
    (["выключи свет"], lambda: robot.eyes(light=False)),
    (["включи свет"], lambda: robot.eyes(light=True)),
    (["быстрее"], faster),
    (["медленнее"], slower),
    (["пока", "до свидания"], goodbye),
]


def find_command(text):
    text = text.replace("ё", "е")
    # сначала длинные фразы, чтобы «выключи свет» не спутать с «свет»
    options = [(p.replace("ё", "е"), action) for phrases, action in COMMANDS for p in phrases]
    for phrase, action in sorted(options, key=lambda o: -len(o[0])):
        if phrase in text:
            return phrase, action
    return None, None


def on_audio(indata, frames, time_info, status):
    if not speaking.is_set():
        audio.put(bytes(indata))


def main():
    SetLogLevel(-1)
    model = Model(MODEL_PATH)
    # Ограничиваем словарь нашими командами — так распознавание точнее
    vocab = sorted({p for ps, _ in COMMANDS for p in ps})
    rec = KaldiRecognizer(model, SAMPLE_RATE, json.dumps(vocab + ["[unk]"], ensure_ascii=False))

    say(random.choice(phrases.GREETING) + " Я готов, говорите команды.")
    print("\nСкажите команду, например: «вперёд», «танцуй», «привет», «стоп», «пока».\n")

    with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=4000, dtype="int16",
                           channels=1, callback=on_audio):
        while True:
            data = audio.get()
            if speaking.is_set():
                continue
            if not rec.AcceptWaveform(data):
                partial = json.loads(rec.PartialResult())["partial"].replace("[unk]", "").strip()
                print(f"\r👂 слышу: {partial:<40}", end="", flush=True)
            else:
                text = json.loads(rec.Result())["text"].replace("[unk]", "").strip()
                print("\r" + " " * 55 + "\r", end="")
                if not text:
                    continue
                phrase, action = find_command(text)
                if action:
                    print(f"🎤 «{text}» → {phrase}")
                    action()
                    with audio.mutex:  # выбрасываем звук, записанный во время действия
                        audio.queue.clear()
                    rec.Reset()
                else:
                    print(f"🎤 «{text}» — не знаю такой команды")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        robot.close()
        print("Робот отключён.")
