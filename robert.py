"""Пульт управления танцующим роботом Robert RS01 по Bluetooth LE."""

import random
import threading
import tkinter as tk
from tkinter import ttk

import robot_ble as rb

# Реальные цвета глаз робота (проверено калибровкой)
COLORS = [(1, "#2c46c8"), (2, "#3fb3e8"), (3, "#2ecc71"), (4, "#f1c40f"),
          (5, "#e74c3c"), (6, "#9b59b6"), (7, "#ecf0f1")]
MOVE_KINDS = {
    "Комбинация (1–93)": rb.COMBO_RANGE,
    "Руки (100–110)": rb.HAND_RANGE,
    "Ноги (200–235)": rb.LEG_RANGE,
}


class App(tk.Tk):
    KEYS = {"w": rb.FORWARD, "Up": rb.FORWARD, "s": rb.BACKWARD, "Down": rb.BACKWARD,
            "a": rb.LEFT, "Left": rb.LEFT, "d": rb.RIGHT, "Right": rb.RIGHT}

    def __init__(self):
        super().__init__()
        self.title("Robert — пульт управления")
        self.minsize(640, 620)
        self.link = rb.BleLink(on_rx=lambda d: self.after(0, self.log, f"← {d.hex(' ')}"),
                               on_disconnect=lambda: self.after(0, self._set_disconnected,
                                                                "Связь потеряна"))
        self.color = 2
        self.light = rb.LIGHT_ON
        self.speed = tk.IntVar(value=0)
        self.moving = None
        self.pressed = set()
        self._build()
        self.bind_all("<KeyPress>", self.on_key_down)
        self.bind_all("<KeyRelease>", self.on_key_up)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- интерфейс ----------
    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)
        self.conn_btn = ttk.Button(top, text="Подключить", command=self.toggle_connect)
        self.conn_btn.pack(side="left")
        self.status = tk.Label(top, text="Не подключено", fg="#b00", font=("Segoe UI", 10, "bold"))
        self.status.pack(side="left", padx=10)

        mid = ttk.Frame(self)
        mid.pack(fill="x", padx=8)

        pad = ttk.LabelFrame(mid, text="Ходьба (зажать; WASD / стрелки, пробел — стоп)")
        pad.pack(side="left", padx=4, anchor="n")
        for label, action, r, c in [("▲", rb.FORWARD, 0, 1), ("◀", rb.LEFT, 1, 0),
                                    ("▶", rb.RIGHT, 1, 2), ("▼", rb.BACKWARD, 2, 1)]:
            b = tk.Button(pad, text=label, width=4, height=2, font=("Segoe UI", 18), bg="#dfe6ee")
            b.grid(row=r, column=c, padx=3, pady=3)
            b.bind("<ButtonPress-1>", lambda e, a=action: self.start_walk(a))
            b.bind("<ButtonRelease-1>", lambda e: self.stop())
        tk.Button(pad, text="■", width=4, height=2, font=("Segoe UI", 18), bg="#e74c3c", fg="white",
                  command=self.stop).grid(row=1, column=1, padx=3, pady=3)

        side = ttk.Frame(mid)
        side.pack(side="left", fill="both", expand=True, padx=8)

        dance = ttk.LabelFrame(side, text="Танец — случайное движение")
        dance.pack(fill="x")
        for text, kind in [("✋ Руки", "Руки (100–110)"), ("🦵 Ноги", "Ноги (200–235)"),
                           ("🕺 Комбинация", "Комбинация (1–93)")]:
            tk.Button(dance, text=text, font=("Segoe UI", 12), bg="#dfe6ee",
                      command=lambda k=kind: self.random_move(k)).pack(side="left", expand=True,
                                                                        fill="x", padx=3, pady=4)

        exact = ttk.LabelFrame(side, text="Конкретное движение")
        exact.pack(fill="x", pady=6)
        self.kind_var = tk.StringVar(value=next(iter(MOVE_KINDS)))
        kind_box = ttk.Combobox(exact, textvariable=self.kind_var, values=list(MOVE_KINDS),
                                state="readonly", width=18)
        kind_box.grid(row=0, column=0, columnspan=4, padx=4, pady=4, sticky="we")
        kind_box.bind("<<ComboboxSelected>>", lambda e: self.num_var.set(self._kind_range()[0]))
        self.num_var = tk.IntVar(value=1)
        ttk.Button(exact, text="◀", width=3, command=lambda: self.step_move(-1)).grid(row=1, column=0)
        ttk.Spinbox(exact, from_=1, to=235, textvariable=self.num_var, width=6).grid(row=1, column=1)
        ttk.Button(exact, text="▶", width=3, command=lambda: self.step_move(1)).grid(row=1, column=2)
        ttk.Button(exact, text="Выполнить", command=self.play_exact).grid(row=1, column=3, padx=4)

        spd = ttk.LabelFrame(side, text="Скорость движений")
        spd.pack(fill="x")
        for v in range(4):
            ttk.Radiobutton(spd, text=str(v), value=v, variable=self.speed).pack(side="left", padx=8, pady=4)

        eyes = ttk.LabelFrame(self, text="Глаза")
        eyes.pack(fill="x", padx=12, pady=6)
        self.color_btns = {}
        for num, hexc in COLORS:
            b = tk.Button(eyes, text=str(num), width=4, bg=hexc, relief="raised",
                          command=lambda n=num: self.set_color(n))
            b.pack(side="left", padx=3, pady=4)
            self.color_btns[num] = b
        self.light_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(eyes, text="Подсветка", variable=self.light_var,
                        command=self.toggle_light).pack(side="left", padx=12)
        self._mark_color()

        logf = ttk.LabelFrame(self, text="Журнал")
        logf.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.log_box = tk.Text(logf, height=8, state="disabled", font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True, padx=4, pady=4)

    # ---------- подключение ----------
    def toggle_connect(self):
        if self.link.connected:
            self.stop()
            self.link.close()
            self._set_disconnected("Отключено")
            return
        self.status.configure(text=f"Поиск {rb.BLE_NAME}… (до 30 сек)", fg="#c80")
        self.conn_btn.configure(state="disabled")

        def worker():
            try:
                addr = self.link.connect()
                self.after(0, self._set_connected, addr)
            except Exception as e:
                self.after(0, self._set_disconnected, f"Ошибка: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _set_connected(self, addr):
        self.status.configure(text=f"Подключено к Robert ({addr})", fg="#1a8a3a")
        self.conn_btn.configure(text="Отключить", state="normal")
        self.log(f"Подключено: {addr}")

    def _set_disconnected(self, msg):
        self.moving = None
        self.status.configure(text=msg, fg="#b00")
        self.conn_btn.configure(text="Подключить", state="normal")
        self.log(msg)

    # ---------- команды ----------
    def send(self, action, param=8, note=""):
        data = rb.packet(action, param, self.speed.get(), self.color, self.light)
        try:
            self.link.write_async(data)
            self.log(f"→ {note or action}: {data.hex(' ')}")
        except rb.LinkError:
            self.status.configure(text="Не подключено — нажмите «Подключить»", fg="#b00")

    def start_walk(self, action):
        if self.moving != action:
            self.moving = action
            names = {rb.FORWARD: "вперёд", rb.BACKWARD: "назад", rb.LEFT: "влево", rb.RIGHT: "вправо"}
            self.send(action, 0xFF, names[action])

    def stop(self):
        self.moving = None
        self.send(rb.IDLE, 8, "стоп")

    def _kind_range(self):
        return MOVE_KINDS[self.kind_var.get()]

    def random_move(self, kind):
        num = random.choice([n for n in MOVE_KINDS[kind] if n != rb.IDLE])
        self.send(num, 8, f"{kind.split()[0].lower()} №{num}")

    def step_move(self, delta):
        r = self._kind_range()
        n = self.num_var.get() + delta
        if n == rb.IDLE:
            n += delta
        n = min(max(n, r[0]), r[-1])
        self.num_var.set(n)
        self.play_exact()

    def play_exact(self):
        try:
            n = int(self.num_var.get())
        except (tk.TclError, ValueError):
            return
        if n == rb.IDLE or not 1 <= n <= 255:
            return
        self.send(n, 8, f"движение №{n}")

    def set_color(self, num):
        self.color = num
        self._mark_color()
        self.send(rb.IDLE, 8, f"цвет {num}")

    def _mark_color(self):
        for n, b in self.color_btns.items():
            b.configure(relief="sunken" if n == self.color else "raised",
                        bd=4 if n == self.color else 2)

    def toggle_light(self):
        self.light = rb.LIGHT_ON if self.light_var.get() else rb.LIGHT_OFF
        self.send(rb.IDLE, 8, "подсветка " + ("вкл" if self.light == rb.LIGHT_ON else "выкл"))

    # ---------- клавиатура ----------
    def _typing(self):
        return isinstance(self.focus_get(), (tk.Entry, ttk.Entry, ttk.Spinbox, ttk.Combobox))

    def on_key_down(self, e):
        if self._typing():
            return
        key = e.keysym if e.keysym in self.KEYS else e.keysym.lower()
        if key in self.pressed:
            return  # автоповтор клавиши
        self.pressed.add(key)
        if key == "space":
            self.stop()
        elif key in self.KEYS:
            self.start_walk(self.KEYS[key])

    def on_key_up(self, e):
        if self._typing():
            return
        key = e.keysym if e.keysym in self.KEYS else e.keysym.lower()
        self.pressed.discard(key)
        if key in self.KEYS:
            held = [k for k in self.pressed if k in self.KEYS]
            if held:
                self.start_walk(self.KEYS[held[-1]])
            else:
                self.stop()

    # ---------- прочее ----------
    def log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def on_close(self):
        if self.link.connected:
            try:
                self.link.write(rb.packet(rb.IDLE, 8, self.speed.get(), self.color, self.light))
            except rb.LinkError:
                pass
            self.link.close()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
