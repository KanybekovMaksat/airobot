"""Приветствие в начале урока: робот представляется, машет, танцует и объявляет начало урока."""

import random
import time

import phrases
from robert_sdk import Robert

with Robert() as robot:
    robot.eyes(3)
    robot.say(random.choice(phrases.GREETING))
    time.sleep(1)
    robot.combo()
    time.sleep(4)
    robot.eyes(1)
    robot.say(random.choice(phrases.LESSON_START))
    robot.hands()
    time.sleep(3)
