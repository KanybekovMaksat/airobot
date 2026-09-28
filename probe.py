"""Подбор команд робота Robert: перебор вариантов по BLE-каналу Robert_ble с отметкой реакций."""

import asyncio
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk

from robot_ble import BLE_NAME, BleLink, LinkError

LOG_PATH = Path(__file__).with_name("reactions.txt")


def _sum8(data):
    return sum(data) & 0xFF


def _xor8(data):
    x = 0
    for b in data:
        x ^= b
    return x


def build_stages():
    stages = {}

    stages["1. ASCII-символы"] = [bytes([b]) for b in range(0x20, 0x7F)]

    stages["2. Остальные байты"] = [bytes([b]) for b in range(256) if not 0x20 <= b < 0x7F]

    words = ["F", "B", "L", "R", "S", "A", "1", "dance", "DANCE", "play", "stop", "hello",
             "AT", "AT+VER", "AT+NAME?", "AT+DANCE", "CMD1", "#1", "$1#", "{1}", "<1>", "*1#",
             "A1", "A01", "M1", "M01", "D1", "D01", "L1", "LED1", "C1", "G1", "H1"]
    stages["3. Текстовые команды"] = [(w + end).encode() for w in words for end in ("", "\r\n", "\n")]

    headers = [b"\xAA\x55", b"\x55\xAA", b"\xA5\x5A", b"\x5A\xA5", b"\xFF\x55", b"\xFF\xAA",
               b"\xAA", b"\xA5", b"\x7E", b"\xFE", b"\xEB\x90", b"\xCC\xDD"]
    frames = []
    for h in headers:
        for cmd in range(1, 17):
            body = bytes([cmd])
            frames.append(h + body)
            frames.append(h + body + bytes([_sum8(body)]))
            frames.append(h + bytes([1]) + body + bytes([_sum8(bytes([1]) + body)]))
            frames.append(h + bytes([2, cmd, 1]) + bytes([_sum8(bytes([2, cmd, 1]))]))
            frames.append(h + bytes([1]) + body + bytes([_xor8(h + bytes([1]) + body)]))
    stages["4. Двоичные пакеты"] = frames

    stages["5. Команда + параметр"] = [bytes([a, b]) for a in range(1, 17) for b in range(1, 17)]
    return stages


def fmt(data):
    hexs = " ".join(f"{b:02X}" for b in data)
    txt = "".join(chr(b) if 0x20 <= b < 0x7F else "·" for b in data)
    return f"{hexs}   «{txt}»"


class Probe(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Robert — подбор команд")
        self.geometry("720x520")
        self.stages = build_stages()
        self.ser = None
        self.running = False
        self.idx = 0
        self.history = []  # (номер, этап, байты, время)
        self._build()
        self.bind_all("<space>", lambda e: self.mark())
        self.bind_all("<Escape>", lambda e: self.pause())
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="Этап:").pack(side="left")
        self.stage_var = tk.StringVar(value=next(iter(self.stages)))
        box = ttk.Combobox(top, textvariable=self.stage_var, values=list(self.stages),
                           state="readonly", width=24)
        box.pack(side="left", padx=4)
        box.bind("<<ComboboxSelected>>", lambda e: self.reset())
        ttk.Label(top, text="Пауза, сек:").pack(side="left", padx=(12, 2))
        self.delay_var = tk.DoubleVar(value=1.5)
        ttk.Spinbox(top, from_=0.3, to=5, increment=0.1, textvariable=self.delay_var,
                    width=5).pack(side="left")
        self.conn_btn = ttk.Button(top, text="Подключить", command=self.connect)
        self.conn_btn.pack(side="right")

        self.status = tk.Label(self, text="Не подключено", fg="#b00", font=("Segoe UI", 10, "bold"))
        self.status.pack(anchor="w", padx=10)

        self.num_lbl = tk.Label(self, text="—", font=("Segoe UI", 64, "bold"))
        self.num_lbl.pack(pady=(10, 0))
        self.cmd_lbl = tk.Label(self, text="", font=("Consolas", 14))
        self.cmd_lbl.pack()
        self.prog = ttk.Progressbar(self, mode="determinate")
        self.prog.pack(fill="x", padx=12, pady=6)

        btns = ttk.Frame(self)
        btns.pack(pady=4)
        self.start_btn = ttk.Button(btns, text="▶ Старт", command=self.start)
        self.start_btn.pack(side="left", padx=4)
        ttk.Button(btns, text="⏸ Пауза (Esc)", command=self.pause).pack(side="left", padx=4)
        ttk.Button(btns, text="⏮ Назад 5", command=lambda: self.jump(-5)).pack(side="left", padx=4)
        ttk.Button(btns, text="↻ Повторить текущую", command=self.repeat).pack(side="left", padx=4)
        tk.Button(self, text="🎯 РЕАКЦИЯ! (пробел)", bg="#2ecc71", fg="white",
                  font=("Segoe UI", 16, "bold"), command=self.mark).pack(fill="x", padx=12, pady=6)

        self.log = tk.Text(self, height=8, font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 8))

    # ---------- связь ----------
    def connect(self):
        self.status.configure(text=f"Поиск {BLE_NAME}…", fg="#c80")
        self.conn_btn.configure(state="disabled")
        link = BleLink(on_rx=lambda d: self.after(0, self._got_rx, d),
                       on_disconnect=lambda: self.after(0, self._lost))

        def worker():
            try:
                addr = link.connect()
                self.ser = link
                self.after(0, lambda: self.status.configure(
                    text=f"Подключено к {BLE_NAME} ({addr})", fg="#1a8a3a"))
            except Exception as e:
                msg = f"Ошибка: {e}"
                self.after(0, lambda: (self.status.configure(text=msg, fg="#b00"),
                                       self.conn_btn.configure(state="normal")))

        threading.Thread(target=worker, daemon=True).start()

    def _lost(self):
        self.running = False
        self.ser = None
        self.status.configure(text="Связь потеряна — нажмите «Подключить»", fg="#b00")
        self.conn_btn.configure(state="normal")

    def _got_rx(self, data):
        last = self.history[-1] if self.history else None
        line = f"← РОБОТ ОТВЕТИЛ: {fmt(data)}  (после №{last[0] if last else '—'})"
        self.write_log(line)
        self._append_file(line)

    # ---------- перебор ----------
    def current_list(self):
        return self.stages[self.stage_var.get()]

    def reset(self):
        self.pause()
        self.idx = 0
        self.num_lbl.configure(text="—")
        self.cmd_lbl.configure(text="")
        self.prog.configure(value=0, maximum=len(self.current_list()))

    def start(self):
        if not self.ser:
            self.status.configure(text="Сначала нажмите «Подключить»", fg="#b00")
            return
        if not self.running:
            self.running = True
            self._tick()

    def pause(self):
        self.running = False

    def jump(self, n):
        self.idx = max(0, self.idx + n)

    def repeat(self):
        if self.history:
            self.send(self.history[-1][0] - 1)

    def _tick(self):
        if not self.running:
            return
        items = self.current_list()
        if self.idx >= len(items):
            self.running = False
            self.write_log(f"Этап «{self.stage_var.get()}» закончен.")
            return
        self.send(self.idx)
        self.idx += 1
        self.after(int(self.delay_var.get() * 1000), self._tick)

    def send(self, i):
        items = self.current_list()
        data = items[i]
        try:
            self.ser.write(data)
        except LinkError as e:
            self.running = False
            self.status.configure(text=f"Связь потеряна: {e}", fg="#b00")
            return
        num = i + 1
        self.history.append((num, self.stage_var.get(), data, time.time()))
        self.history = self.history[-50:]
        self.num_lbl.configure(text=str(num))
        self.cmd_lbl.configure(text=fmt(data))
        self.prog.configure(value=num, maximum=len(items))

    def mark(self):
        if not self.history:
            return
        now = time.time()
        recent = [h for h in self.history if now - h[3] <= 4][-4:] or self.history[-1:]
        stamp = datetime.now().strftime("%H:%M:%S")
        lines = [f"[{stamp}] РЕАКЦИЯ. Последние отправленные:"]
        lines += [f"    №{n} ({st}): {fmt(d)}" for n, st, d, _ in recent]
        for l in lines:
            self.write_log(l)
        self._append_file("\n".join(lines))

    def write_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _append_file(self, text):
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(text + "\n")

    def on_close(self):
        self.running = False
        if self.ser:
            self.ser.close()
        self.destroy()


if __name__ == "__main__":
    Probe().mainloop()
