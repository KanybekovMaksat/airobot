"""Веб-панель ментора: пишете текст в браузере — Роберт его произносит.

Запуск:  python mentor_panel.py          → http://localhost:8000
         python mentor_panel.py --lan    → доступ с телефона в той же Wi-Fi сети
"""

import json
import os
import queue
import re
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import phrases
from robert_sdk import Robert

HERE = Path(__file__).parent
PRESETS_PATH = HERE / "mentor_presets.json"
PORT = 8000

PHRASE_GROUPS = {
    "Приветствие": phrases.GREETING,
    "Начало урока": phrases.LESSON_START,
    "Похвала": phrases.PRAISE,
    "Шутки": phrases.JOKES,
    "О себе": phrases.ABOUT,
    "Конец урока": phrases.LESSON_END,
}

robot = Robert(connect=False)
state = {"connected": False, "connecting": False, "speaking": False, "error": "", "history": []}
speech_queue = queue.Queue()
stop_speech = threading.Event()
voice_settings = {"rate": 0, "volume": 100}


# ---------- робот ----------
def connect_robot():
    if state["connected"] or state["connecting"]:
        return
    state.update(connecting=True, error="")

    def worker():
        try:
            robot._link.on_disconnect = lambda: state.update(connected=False)
            robot.connect()
            state["connected"] = True
        except Exception as e:
            state["error"] = f"Робот не найден: включите его и нажмите «Подключить» ещё раз ({e})"
        finally:
            state["connecting"] = False

    threading.Thread(target=worker, daemon=True).start()


def robot_do(fn, *args):
    if not state["connected"]:
        raise RuntimeError("робот не подключён")
    threading.Thread(target=fn, args=args, daemon=True).start()


# ---------- речь (отдельный поток, чтобы сервер не ждал, пока робот договорит) ----------
def speech_worker():
    while True:
        text, gesture = speech_queue.get()
        stop_speech.clear()
        state["speaking"] = True
        try:
            robot.say(text, gesture=gesture and state["connected"], rate=voice_settings["rate"],
                      volume=voice_settings["volume"], stop_event=stop_speech)
        except Exception as e:
            state["error"] = f"Ошибка речи: {e}"
        finally:
            state["speaking"] = speech_queue.qsize() > 0


def say(text, gesture):
    text = text.strip()
    if not text:
        return
    speech_queue.put((text, gesture))
    state["history"] = ([{"text": text, "time": time.strftime("%H:%M")}] + state["history"])[:15]


# ---------- заготовки ментора ----------
def load_presets():
    if PRESETS_PATH.exists():
        return json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    return []


def save_presets(items):
    PRESETS_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- ИИ-ответы: страница «Спроси Роберта» ----------
# Ключ кладут одной строкой в файл рядом с этой программой:
#   gemini_key.txt — бесплатный ключ Google Gemini (получить: aistudio.google.com/apikey)
#   claude_key.txt — ключ Anthropic Claude (console.anthropic.com)
# Если есть оба файла, используется Gemini.
# Алиасы «всегда актуальная модель»; если первая перегружена (503) — пробуем запасную
GEMINI_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"]
CLAUDE_MODEL = "claude-opus-5"
AI_SYSTEM = (
    "Ты — Роберт, дружелюбный танцующий робот из IT-школы Codify. "
    "Ты разговариваешь с детьми 9–14 лет на уроке по искусственному интеллекту. "
    "Твой ответ произносится вслух синтезом речи, поэтому: отвечай по-русски, коротко "
    "(1–3 предложения), без списков, без markdown, без эмодзи и без английских слов, "
    "которые сложно произнести. Объясняй просто и с теплотой, можно с лёгким юмором. "
    "Если вопрос не по теме урока — всё равно ответь коротко и по-доброму."
)
def _read_key(env_name, filename):
    key = os.environ.get(env_name, "").strip()
    path = HERE / filename
    if not key and path.exists():
        key = path.read_text(encoding="utf-8").strip()
    return key


def ai_provider():
    """Какая нейросеть настроена: ('gemini'|'claude', ключ) или ('', '')."""
    key = _read_key("GEMINI_API_KEY", "gemini_key.txt")
    if key:
        return "gemini", key
    key = _read_key("ANTHROPIC_API_KEY", "claude_key.txt")
    if key:
        return "claude", key
    return "", ""


def ask_ai(question, personality="", history=None, key=""):
    """Спросить нейросеть от лица Роберта. history — список {role, content} с прошлыми репликами.

    key — ключ, который ученик вставил на странице; если пусто, берём ключ сервера
    (gemini_key.txt / claude_key.txt). Провайдер узнаётся по виду ключа: AIza… — Gemini.
    """
    key = (key or "").strip().strip('"\'' + "«»")
    if key:
        # Ученики иногда копируют ключ вместе с лишним текстом — вытаскиваем сам ключ.
        # У Gemini два формата ключей: старый «AIza…» и новый «AQ.…»
        gemini = re.search(r"AIza[0-9A-Za-z_\-]{10,}|AQ\.[0-9A-Za-z_\-]{20,}", key)
        claude = re.search(r"sk-ant-[0-9A-Za-z_\-]{10,}", key)
        if gemini:
            provider, key = "gemini", gemini.group(0)
        elif claude:
            provider, key = "claude", claude.group(0)
        else:
            raise RuntimeError("это не похоже на ключ: ключ Gemini начинается с «AIza…» или «AQ.…» — "
                               "скопируй его целиком на aistudio.google.com/apikey")
    else:
        provider, key = ai_provider()
    if not provider:
        raise RuntimeError("нет API-ключа: вставьте свой ключ в поле «Ключ нейросети» на странице "
                           "(бесплатно на aistudio.google.com/apikey) или положите его "
                           "в файл gemini_key.txt рядом с mentor_panel.py")
    system = AI_SYSTEM
    if personality.strip():
        system += "\n\nСегодня у тебя особый характер, играй эту роль:\n" + personality.strip()
    history = [m for m in (history or [])[-10:] if m.get("role") in ("user", "assistant")]
    if provider == "gemini":
        answer = _ask_gemini(key, system, history, question)
    else:
        answer = _ask_claude(key, system, history, question)
    if not answer:
        raise RuntimeError("нейросеть не ответила, попробуйте переформулировать вопрос")
    return answer


def _ask_gemini(key, system, history, question):
    import urllib.error
    import urllib.request
    contents = [{"role": "user" if m["role"] == "user" else "model",
                 "parts": [{"text": str(m["content"])[:2000]}]} for m in history]
    contents.append({"role": "user", "parts": [{"text": question}]})
    body = json.dumps({
        "system_instruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 2048},
    }).encode("utf-8")

    # Перегрузку (503) переживаем сами: повтор через секунду, потом запасная модель
    attempts = [(m, pause) for m in GEMINI_MODELS for pause in (0, 1.5)]
    overloaded = False
    for model, pause in attempts:
        if pause:
            time.sleep(pause)
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if e.code in (500, 502, 503, 504):
                overloaded = True
                continue
            if e.code in (400, 401, 403):
                raise RuntimeError("ключ Gemini не подошёл — проверь, что скопировал его целиком "
                                   "(выдаётся на aistudio.google.com/apikey)") from e
            if e.code == 429:
                raise RuntimeError("бесплатный лимит Gemini на минуту исчерпан — подождите немного") from e
            if e.code == 404:
                continue  # такой модели больше нет — пробуем запасную
            raise RuntimeError(f"ошибка Gemini ({e.code}): {detail[:200]}") from e
        except urllib.error.URLError as e:
            raise RuntimeError("нет соединения с нейросетью — проверьте интернет") from e
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError):
            return ""
        return "".join(p.get("text", "") for p in parts).strip()
    if overloaded:
        raise RuntimeError("нейросеть Google сейчас перегружена — подождите минуту и спросите ещё раз")
    raise RuntimeError("модели Gemini недоступны — попробуйте позже")


def _ask_claude(key, system, history, question):
    import anthropic
    # Клиент на каждый запрос: у разных учеников могут быть разные ключи
    client = anthropic.Anthropic(api_key=key)
    messages = [{"role": m["role"], "content": str(m["content"])[:2000]} for m in history]
    messages.append({"role": "user", "content": question})
    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1000,
            output_config={"effort": "low"},  # быстрые короткие ответы для урока
            system=system,
            messages=messages,
        )
    except anthropic.AuthenticationError:
        raise RuntimeError("ключ Claude не подошёл — проверьте его на console.anthropic.com")
    except anthropic.APIConnectionError:
        raise RuntimeError("нет соединения с нейросетью — проверьте интернет")
    except anthropic.RateLimitError:
        raise RuntimeError("слишком много вопросов подряд — подождите минуту")
    return "".join(b.text for b in resp.content if b.type == "text").strip()


ACTIONS = {
    "forward": lambda s: robot.forward(s),
    "backward": lambda s: robot.backward(s),
    "left": lambda s: robot.left(s),
    "right": lambda s: robot.right(s),
    "stop": lambda s: robot.stop(),
    "hands": lambda s: robot.hands(),
    "legs": lambda s: robot.legs(),
    "combo": lambda s: robot.combo(),
    "dance": lambda s: robot.dance(seconds=s or 10),
}


# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        pages = {"/": "mentor_panel.html", "/index.html": "mentor_panel.html", "/tm": "tm.html",
                 "/follow": "follow.html", "/sound": "sound.html", "/chat": "chat.html"}
        if self.path in pages:
            body = (HERE / pages[self.path]).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/static/") or self.path == "/favicon.ico":
            f = (HERE / "static" / Path(self.path).name)
            if not f.is_file():
                return self._json({"error": "not found"}, 404)
            types = {".png": "image/png", ".svg": "image/svg+xml", ".css": "text/css; charset=utf-8",
                     ".ico": "image/x-icon"}
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", types.get(f.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            self._json({**state, "voice": voice_settings, "ai": ai_provider()[0]})
        elif self.path == "/api/phrases":
            self._json({"groups": PHRASE_GROUPS, "presets": load_presets()})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        try:
            if self.path == "/api/connect":
                connect_robot()
            elif self.path == "/api/say":
                say(data.get("text", ""), data.get("gesture", True))
            elif self.path == "/api/stop_speech":
                with speech_queue.mutex:
                    speech_queue.queue.clear()
                stop_speech.set()
            elif self.path == "/api/voice":
                voice_settings["rate"] = max(-10, min(10, int(data.get("rate", 0))))
                voice_settings["volume"] = max(0, min(100, int(data.get("volume", 100))))
            elif self.path == "/api/action":
                robot_do(ACTIONS[data["kind"]], float(data.get("seconds", 1)))
            elif self.path == "/api/eyes":
                robot_do(robot.eyes, int(data["color"]), bool(data.get("light", True)))
            elif self.path == "/api/speed":
                robot.speed(int(data["level"]))
            elif self.path == "/api/log":
                line = f"[страница] {data.get('text')} | backend={data.get('backend')}\n{data.get('stack') or ''}"
                print(line)
                state["client_error"] = line[:2000]
            elif self.path == "/api/ask":
                question = str(data.get("question", "")).strip()
                if not question:
                    return self._json({"error": "пустой вопрос"}, 400)
                answer = ask_ai(question, str(data.get("personality", "")),
                                data.get("history") or [], str(data.get("key", "")))
                if data.get("speak", True):
                    say(answer, gesture=True)
                return self._json({"answer": answer})
            elif self.path == "/api/presets":
                save_presets([t for t in data.get("items", []) if t.strip()])
            else:
                return self._json({"error": "not found"}, 404)
            self._json({"ok": True})
        except Exception as e:
            self._json({"error": str(e)}, 400)


def main():
    lan = "--lan" in sys.argv
    host = "0.0.0.0" if lan else "127.0.0.1"
    threading.Thread(target=speech_worker, daemon=True).start()
    connect_robot()
    server = ThreadingHTTPServer((host, PORT), Handler)
    print(f"Панель ментора: http://localhost:{PORT}")
    if lan:
        ip = socket.gethostbyname(socket.gethostname())
        print(f"С телефона (та же Wi-Fi сеть): http://{ip}:{PORT}")
    print("Чтобы остановить — закройте это окно или нажмите Ctrl+C.")
    webbrowser.open(f"http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        robot.close()


if __name__ == "__main__":
    main()
