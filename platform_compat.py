"""Всё, что зависит от операционной системы: голос, камера, шрифт.

Windows — голос Microsoft (Irina) через SAPI, камера через DirectShow.
macOS   — русский голос macOS (Milena и др.) через команду `say`, камера через AVFoundation.
"""

import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

HERE = Path(__file__).parent
FONT_PATH = HERE / "static" / "fonts" / "Onest.ttf"


# ---------- голос ----------
class Speaker:
    """Произносит текст через динамик робота (если он подключён как колонка), иначе через обычный звук."""

    def __init__(self, device_hint="Robert", voice_hint="Irina"):
        self.device_hint = device_hint
        self.voice_hint = voice_hint
        self._local = threading.local()  # SAPI работает только в том потоке, где создан
        self._mac_voice = None
        self._mac_device = None
        self._mac_checked = False

    def speak(self, text, rate=0, volume=100, stop_event=None):
        """Говорит и ждёт окончания. rate: -10…10, volume: 0…100. stop_event прерывает речь."""
        if not text.strip():
            return
        if IS_WINDOWS:
            self._speak_windows(text, rate, volume, stop_event)
        elif IS_MAC:
            self._speak_mac(text, rate, volume, stop_event)
        else:
            print(f"[Роберт говорит] {text}")

    # --- Windows ---
    def _sapi(self):
        voice = getattr(self._local, "voice", None)
        if voice is None:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            for v in voice.GetVoices():
                if self.voice_hint.lower() in v.GetDescription().lower():
                    voice.Voice = v
            # «Robert Stereo» — музыкальный выход; «Hands-Free» — телефонный, он хуже звучит
            outputs = [o for o in voice.GetAudioOutputs() if self.device_hint.lower() in o.GetDescription().lower()]
            outputs.sort(key=lambda o: "hands-free" in o.GetDescription().lower())
            if outputs:
                voice.AudioOutput = outputs[0]
            self._local.voice = voice
        return voice

    def _speak_windows(self, text, rate, volume, stop_event):
        voice = self._sapi()
        voice.Rate = max(-10, min(10, int(rate)))
        voice.Volume = max(0, min(100, int(volume)))
        voice.Speak(text, 1)  # 1 = асинхронно, чтобы можно было прервать
        while not voice.WaitUntilDone(100):
            if stop_event is not None and stop_event.is_set():
                voice.Speak("", 3)  # прервать и очистить очередь
                break

    # --- macOS ---
    def _mac_setup(self):
        if self._mac_checked:
            return
        self._mac_checked = True
        if not shutil.which("say"):
            return
        voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
        russian = [m.group(1).strip() for m in re.finditer(r"^(.+?)\s{2,}ru_RU\b", voices, re.M)]
        if russian:
            preferred = [v for v in russian if v.startswith("Milena")]
            self._mac_voice = (preferred or russian)[0]
        else:
            print("На Mac не установлен русский голос: Системные настройки → Универсальный доступ → "
                  "Устный контент → Системный голос → Управлять голосами → Русский (Milena).")
        devices = subprocess.run(["say", "-a", "?"], capture_output=True, text=True).stdout
        for m in re.finditer(r"^\s*(\d+)\s+(.+)$", devices, re.M):
            if self.device_hint.lower() in m.group(2).lower():
                self._mac_device = m.group(1)
                break

    def _speak_mac(self, text, rate, volume, stop_event):
        self._mac_setup()
        cmd = ["say", "-r", str(int(180 * 1.07 ** max(-10, min(10, rate))))]
        if self._mac_voice:
            cmd += ["-v", self._mac_voice]
        if self._mac_device:
            cmd += ["-a", self._mac_device]
        if volume < 100:
            text = f"[[volm {max(0, volume) / 100:.2f}]] {text}"
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        proc.stdin.write(text.encode("utf-8"))
        proc.stdin.close()
        while proc.poll() is None:
            if stop_event is not None and stop_event.is_set():
                proc.terminate()
                break
            time.sleep(0.1)


# ---------- камера ----------
def open_camera(index=0):
    import cv2
    if IS_WINDOWS:
        return cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if IS_MAC:
        return cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    return cv2.VideoCapture(index)


# ---------- шрифт (Onest лежит в проекте, поэтому одинаков на всех системах) ----------
_FALLBACK_FONTS = [
    "C:/Windows/Fonts/segoeui.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def load_font(size, bold=False):
    from PIL import ImageFont
    try:
        font = ImageFont.truetype(str(FONT_PATH), size)
        font.set_variation_by_axes([700 if bold else 400])
        return font
    except Exception:
        for path in _FALLBACK_FONTS:
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        return ImageFont.load_default()
