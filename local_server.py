"""Локальный мост: веб-страницы Роберта + связь с роботом через системный Bluetooth.

Запуск:  ЗАПУСК.bat   (или  python local_server.py)
Открывает http://localhost:8765 — те же страницы, что на сайте, но роботом управляет
этот сервер через Bluetooth Windows (библиотека bleak), а не Chrome. Окно выбора
устройств в Chrome не нужно: робот ищется по имени, а после первого раза —
по запомненному адресу, даже если он не «светится» в эфире.

Пути для страниц (robert.js сам их находит, когда открыт с localhost):
  GET  /api/status            {"bridge": true, "state": connected|connecting|disconnected, "error": "…"}
  POST /api/connect           начать подключение (ответ — как у status)
  POST /api/disconnect        отключить робота
  POST /api/send   <hex>      отправить пакет роботу (тело запроса — байты в hex)
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV_PY = HERE / ".venv" / "Scripts" / "python.exe"


def bootstrap():
    """Первый запуск: создать .venv рядом и поставить bleak, затем перезапуститься из него.

    ЗАПУСК.bat намеренно не содержит русских букв (cmd их ломает), поэтому вся подготовка здесь.
    """
    in_venv = Path(sys.executable).resolve() == VENV_PY.resolve()
    if not in_venv and os.name == "nt":
        if not VENV_PY.exists():
            print("Первый запуск: готовлю программу (нужен интернет, 1–2 минуты)…", flush=True)
            try:
                subprocess.check_call([sys.executable, "-m", "venv", str(HERE / ".venv")])
            except Exception as e:
                print(f"Не удалось подготовить программу: {e}")
                print("Проверьте, что Python 3.11 или 3.12 установлен с python.org, и запустите снова.")
                input("Нажмите Enter, чтобы закрыть…")
                sys.exit(1)
        sys.exit(subprocess.call([str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]]))
    try:
        import bleak  # noqa: F401
    except ImportError:
        print("Устанавливаю библиотеку Bluetooth (bleak)…", flush=True)
        r = subprocess.call([sys.executable, "-m", "pip", "install", "-q", "bleak"])
        if r != 0:
            print("Не удалось установить библиотеку. Проверьте интернет и запустите снова.")
            input("Нажмите Enter, чтобы закрыть…")
            sys.exit(1)


bootstrap()
from bleak import BleakClient, BleakScanner  # noqa: E402
WEB_DIR = HERE / "web"
ADDRESS_FILE = HERE / "robot_address.txt"   # сюда запоминаем адрес робота после первого подключения
PORT = 8765

NAME_PREFIX = "robert"                       # робот виден как Robert_ble (иногда просто Robert)
WRITE_UUID = "0000ffc1-0000-1000-8000-00805f9b34fb"
IDLE_PACKET = bytes.fromhex("aaaacc3201" + "4d4d08" + "000200" + "0202" + "0101" + "5555")  # «стоп», пульс
SCAN_SECONDS = 10
HEARTBEAT_SECONDS = 60                       # робот засыпает через ~8 минут тишины


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def plain_error(e):
    """Перевести ошибку Bluetooth на человеческий язык."""
    s = str(e)
    low = s.lower()
    if "turned off" in low or "radio" in low or "bluetooth adapter" in low or "not available" in low:
        return "на ноутбуке выключен Bluetooth — включите его в Параметрах Windows"
    if "not found" in low or "was not found" in low or "could not find" in low:
        return "робот не найден — включите его (кнопка на груди 5 секунд) и попробуйте снова"
    if "timed out" in low or "timeout" in low:
        return "робот не отвечает — скорее всего он подключён к другому устройству или спит; перезагрузите его"
    if "unreachable" in low or "failed to connect" in low or "connection" in low:
        return "робот не отвечает — скорее всего он подключён к другому устройству; выключите и включите его"
    return s or "неизвестная ошибка"


class RobotLink:
    """Связь с роботом в своём asyncio-цикле (фоновый поток), снаружи — простые методы."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.client = None
        self.state = "disconnected"
        self.error = ""
        self.name = ""
        self.address = ADDRESS_FILE.read_text().strip() if ADDRESS_FILE.exists() else ""
        self.want = False
        self.last_write = 0.0
        self._task = None
        asyncio.run_coroutine_threadsafe(self._watchdog(), self.loop)

    # --- снаружи ---
    def status(self):
        return {"bridge": True, "state": self.state, "error": self.error,
                "name": self.name, "address": self.address}

    def connect(self):
        if self.state == "connecting":
            return
        self.want = True
        self.error = ""
        self.state = "connecting"
        self._task = asyncio.run_coroutine_threadsafe(self._connect(first=True), self.loop)

    def disconnect(self):
        self.want = False
        asyncio.run_coroutine_threadsafe(self._disconnect(), self.loop).result(10)

    def send(self, data: bytes):
        if self.state != "connected" or not self.client:
            raise RuntimeError("робот не подключён")
        self.last_write = time.time()
        asyncio.run_coroutine_threadsafe(
            self.client.write_gatt_char(WRITE_UUID, data, response=False), self.loop)

    # --- внутри цикла ---
    async def _find(self):
        """Сначала ищем в эфире по имени, если не нашли — пробуем запомненный адрес."""
        log(f"Ищу робота в эфире ({SCAN_SECONDS} с)…")
        found = None
        try:
            devices = await BleakScanner.discover(timeout=SCAN_SECONDS)
        except Exception as e:
            raise RuntimeError(plain_error(e)) from e
        for d in devices:
            if (d.name or "").lower().startswith(NAME_PREFIX):
                # Robert_ble (управление) важнее, чем Robert (колонка)
                if found is None or "ble" in (d.name or "").lower():
                    found = d
        if found:
            log(f"Нашёл: {found.name} ({found.address})")
            return found
        if self.address:
            log(f"В эфире нет, пробую запомненный адрес {self.address}")
            return self.address
        raise RuntimeError("робот не найден — включите его (кнопка на груди 5 секунд), "
                           "подойдите ближе и нажмите «Подключить» ещё раз")

    async def _connect(self, first):
        try:
            target = await self._find() if first or not self.address else self.address
            client = BleakClient(target, disconnected_callback=self._on_dropped, timeout=20)
            await client.connect()
            self.client = client
            self.address = client.address
            self.name = getattr(target, "name", None) or self.name or "Robert"
            ADDRESS_FILE.write_text(self.address)
            self.last_write = time.time()
            self.state = "connected"
            self.error = ""
            log(f"Подключено: {self.name} {self.address}")
            await client.write_gatt_char(WRITE_UUID, IDLE_PACKET, response=False)
        except Exception as e:
            self.client = None
            self.state = "disconnected"
            self.error = plain_error(e)
            log(f"Не подключился: {self.error}  [{type(e).__name__}: {e}]")
            if not first:
                raise

    async def _disconnect(self):
        c, self.client = self.client, None
        self.state = "disconnected"
        if c:
            try:
                await c.write_gatt_char(WRITE_UUID, IDLE_PACKET, response=False)
                await c.disconnect()
            except Exception:
                pass
        log("Отключено")

    def _on_dropped(self, _client):
        if self.state == "connected":
            log("Связь оборвалась")
        self.client = None
        if self.want:
            self.state = "connecting"
            self.error = "связь оборвалась, переподключаюсь…"
            asyncio.run_coroutine_threadsafe(self._reattach(), self.loop)
        else:
            self.state = "disconnected"

    async def _reattach(self):
        """Переподключаемся, пока ментор не нажал «Отключить» или не выключил робота."""
        for i in range(1, 1000):
            if not self.want or self.state == "connected":
                return
            try:
                await self._connect(first=False)
                return
            except Exception:
                self.state = "connecting"
                self.error = f"связь оборвалась, переподключаюсь (попытка {i})…"
            await asyncio.sleep(min(5, 1 + i))
        self.state = "disconnected"

    async def _watchdog(self):
        while True:
            await asyncio.sleep(5)
            if self.state == "connected" and self.client and time.time() - self.last_write > HEARTBEAT_SECONDS:
                try:
                    self.last_write = time.time()
                    await self.client.write_gatt_char(WRITE_UUID, IDLE_PACKET, response=False)
                except Exception:
                    pass


link = RobotLink()


class Handler(SimpleHTTPRequestHandler):
    """Статика из web/ + /api/*."""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB_DIR), **kw)

    def log_message(self, fmt, *args):
        if "/api/" not in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def end_headers(self):
        if self.path.endswith((".html", ".js", ".css")) or self.path == "/":
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/status"):
            return self._json(link.status())
        if self.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode("utf-8", "ignore").strip()
        try:
            if self.path == "/api/connect":
                link.connect()
            elif self.path == "/api/disconnect":
                link.disconnect()
            elif self.path == "/api/send":
                link.send(bytes.fromhex(body))
            else:
                return self._json({"error": "нет такого пути"}, 404)
            return self._json(link.status())
        except Exception as e:
            return self._json({**link.status(), "error": plain_error(e)}, 500)


def main():
    if not WEB_DIR.is_dir():
        print(f"Рядом с local_server.py нет папки web — распакуйте архив целиком. Искал: {WEB_DIR}")
        input("Нажмите Enter, чтобы закрыть…")
        return
    page = sys.argv[1] if len(sys.argv) > 1 else "index.html"
    url = f"http://localhost:{PORT}/{page}"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        log(f"Порт {PORT} занят — сервер уже запущен. Открываю {url}")
        webbrowser.open(url)
        return
    print("=" * 60)
    print("  РОБЕРТ — локальная версия через системный Bluetooth")
    print(f"  Страницы: {url}")
    print("  Это окно не закрывайте, пока идёт урок.")
    print("=" * 60, flush=True)
    threading.Timer(0.7, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            link.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
