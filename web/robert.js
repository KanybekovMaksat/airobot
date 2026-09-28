/* Роберт в браузере: Web Bluetooth (протокол Robert RS01) + речь + общая шапка страниц.
   Работает в Chrome и Edge по HTTPS (или на localhost). */

const Robert = (() => {
  // ---------- протокол (как в robot_ble.py) ----------
  const SERVICE = 0xffc0, WRITE_CHAR = 0xffc1;
  const BACKWARD = 1, FORWARD = 2, LEFT = 3, RIGHT = 4, IDLE = 77;
  const LIGHT_ON = 0, LIGHT_OFF = 4;
  const range = (a, b) => Array.from({length: b - a + 1}, (_, i) => a + i);
  const COMBO_RANGE = range(1, 93).filter((n) => n !== IDLE);
  const HAND_RANGE = range(100, 110);
  const LEG_RANGE = range(200, 235);

  // Реальные цвета глаз робота (проверено калибровкой)
  const COLORS = {1: "тёмно-синий", 2: "голубой", 3: "зелёный", 4: "жёлтый",
                  5: "красный", 6: "фиолетовый", 7: "белый"};

  // Слова, которые русский голос читает неправильно
  const PRONUNCIATION = {
    "IT": "айти", "Codify": "Кодифай", "AI": "эй ай", "ИИ": "и-и",
    "Python": "Пайтон", "MediaPipe": "Медиа Пайп", "Teachable Machine": "Тичабл Машин",
    "Gemini": "Джемини",
  };

  let device = null, writeChar = null, connecting = false, wantConnected = false;
  let speed = 0, color = 2, light = LIGHT_ON;
  let writeQueue = Promise.resolve(), lastWrite = 0;
  const statusCbs = [];

  function packet(action, param = 8) {
    return new Uint8Array([0xAA, 0xAA, 0xCC, 0x32, 0x01,
                           action & 0xFF, action & 0xFF, param & 0xFF,
                           speed, color, light, 2, 2, 1, 1, 0x55, 0x55]);
  }

  const connected = () => !!(device && device.gatt.connected && writeChar);

  function notify() {
    const s = connecting ? "connecting" : connected() ? "connected" : "disconnected";
    statusCbs.forEach((cb) => cb(s));
  }

  // ---------- подключение ----------
  async function attach() {
    const gatt = await device.gatt.connect();
    const svc = await gatt.getPrimaryService(SERVICE);
    writeChar = await svc.getCharacteristic(WRITE_CHAR);
  }

  async function connect() {
    if (!navigator.bluetooth)
      throw new Error("этот браузер не умеет Web Bluetooth — откройте сайт в Chrome или Edge (не iPhone)");
    connecting = true; notify();
    try {
      device = await navigator.bluetooth.requestDevice({
        filters: [{namePrefix: "Robert"}], optionalServices: [SERVICE]});
      device.addEventListener("gattserverdisconnected", onDropped);
      await attach();
      wantConnected = true;
      lastWrite = Date.now();
    } finally {
      connecting = false; notify();
    }
  }

  // Связь оборвалась сама (робот далеко, помехи) — тихо переподключаемся
  async function onDropped() {
    writeChar = null; notify();
    if (!wantConnected) return;
    connecting = true; notify();
    for (let i = 0; i < 5 && wantConnected && device; i++) {
      await new Promise((r) => setTimeout(r, 1000 + i * 1000));
      try { await attach(); break; } catch {}
    }
    connecting = false; notify();
  }

  function disconnect() {
    wantConnected = false;
    if (device && device.gatt.connected) {
      try { send(IDLE); } catch {}
      device.gatt.disconnect();
    }
    writeChar = null; notify();
  }

  // «Пульс»: робот сам выключается через ~8 минут без команд, поэтому раз в полторы
  // минуты тишины шлём безобидный «стоп», чтобы он не засыпал
  setInterval(() => {
    if (connected() && Date.now() - lastWrite > 90000) {
      try { send(IDLE); } catch {}
    }
  }, 30000);

  // Записи по одной: BLE не любит параллельные операции
  function send(action, param = 8) {
    if (!connected()) throw new Error("робот не подключён — нажмите «Подключить робота»");
    const data = packet(action, param);
    lastWrite = Date.now();
    writeQueue = writeQueue
      .then(() => writeChar.writeValueWithoutResponse(data))
      .catch(() => {});
    return writeQueue;
  }

  // ---------- движения ----------
  const pick = (arr, n) => (n == null ? arr[Math.floor(Math.random() * arr.length)] : n);
  const walk = (action) => send(action, 0xFF);   // идти, пока не придёт другая команда
  const stop = () => send(IDLE);

  async function walkFor(action, seconds) {
    await walk(action);
    setTimeout(() => { if (connected()) stop(); }, seconds * 1000);
  }

  const hands = (n) => { n = pick(HAND_RANGE, n); send(n); return n; };
  const legs = (n) => { n = pick(LEG_RANGE, n); send(n); return n; };
  const combo = (n) => { n = pick(COMBO_RANGE, n); send(n); return n; };

  let danceTimer = null;
  function dance(seconds = 10) {
    clearInterval(danceTimer);
    const step = () => [hands, legs, combo][Math.floor(Math.random() * 3)]();
    step();
    danceTimer = setInterval(step, 2000);
    setTimeout(() => { clearInterval(danceTimer); if (connected()) stop(); }, seconds * 1000);
  }

  function eyes(c, on = true) {
    if (c) color = c;
    light = on ? LIGHT_ON : LIGHT_OFF;
    stop();  // цвет применяется командой «стоп», как в протоколе
  }

  const setSpeed = (v) => { speed = Math.max(0, Math.min(3, v | 0)); };

  // ---------- речь (синтез браузера; если робот сопряжён как колонка — звук идёт из него) ----------
  let ruVoice = null;
  function findVoice() {
    const vs = speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith("ru"));
    ruVoice = vs.find((v) => /irina|milena|svetlana|google/i.test(v.name)) || vs[0] || null;
  }
  if (window.speechSynthesis) {
    findVoice();
    speechSynthesis.onvoiceschanged = findVoice;
  }

  function pronounce(text) {
    for (const [word, spoken] of Object.entries(PRONUNCIATION))
      text = text.replace(new RegExp(`(?<![\\wа-яё])${word}(?![\\wа-яё])`, "gi"), spoken);
    return text;
  }

  function say(text, {gesture = true, rate = 1, volume = 1} = {}) {
    if (!window.speechSynthesis) return Promise.resolve();
    if (gesture && connected()) { try { hands(); } catch {} }
    return new Promise((resolve) => {
      const u = new SpeechSynthesisUtterance(pronounce(text));
      u.lang = "ru-RU";
      if (ruVoice) u.voice = ruVoice;
      u.rate = rate; u.volume = volume;
      u.onend = resolve; u.onerror = resolve;
      speechSynthesis.speak(u);
    });
  }

  const stopSpeech = () => speechSynthesis && speechSynthesis.cancel();

  // ---------- фразы ----------
  const PHRASES = {
    "Приветствие": [
      "Привет! Я Роберт из IT-школы Кодифай.",
      "Всем привет! Меня зовут Роберт, я робот IT-школы Кодифай.",
      "Здравствуйте, ребята! Робот Роберт из Кодифая на связи.",
    ],
    "Начало урока": [
      "Внимание! Урок начинается. Сегодня мы будем изучать искусственный интеллект.",
      "Рассаживайтесь поудобнее. Начинаем урок в IT-школе Кодифай!",
      "Друзья, пора учиться! Сегодня вы научите меня чему-то новому.",
      "Урок начинается! Открывайте ноутбуки и приготовьтесь программировать.",
    ],
    "Похвала": [
      "Молодцы! Отличная работа!",
      "Вот это да! Вы настоящие программисты!",
      "Супер! Я горжусь вами.",
      "Отлично! Так держать!",
    ],
    "Шутки": [
      "Почему робот не боится темноты? Потому что у него глаза светятся!",
      "Какой у робота любимый танец? Робот-н-ролл!",
      "Почему программисты путают Хэллоуин и Рождество? Потому что тридцать один в восьмеричной системе равно двадцати пяти в десятичной.",
      "Я не ленивый робот. Я просто в режиме энергосбережения.",
    ],
    "О себе": [
      "Я Роберт, танцующий робот IT-школы Кодифай. Я умею ходить, танцевать, менять цвет глаз и слушать ваши команды.",
      "Меня зовут Роберт. Я живу в IT-школе Кодифай и помогаю ребятам изучать искусственный интеллект.",
    ],
    "Конец урока": [
      "Урок окончен. Спасибо за работу! До встречи в Кодифае!",
      "На сегодня всё. Вы молодцы! Увидимся на следующем уроке.",
      "Урок закончен. Не забудьте сохранить свои проекты. Пока!",
    ],
  };

  // ---------- общая шапка: кнопка «Подключить» и статус ----------
  function initHeader() {
    const btn = document.getElementById("connectBtn");
    const status = document.getElementById("robotStatus");
    const render = (s) => {
      if (status) {
        const map = {connected: ["ok", "Робот подключён"], connecting: ["wait", "Подключаюсь…"],
                     disconnected: ["", "Робот не подключён"]};
        const [cls, label] = map[s];
        status.innerHTML = `<span class="dot ${cls}"></span>${label}`;
      }
      if (btn) btn.innerHTML = s === "connected"
        ? '<i class="ti ti-plug-connected-x"></i>Отключить'
        : '<i class="ti ti-plug-connected"></i>Подключить робота';
    };
    statusCbs.push(render);
    render("disconnected");
    if (btn) btn.onclick = async () => {
      if (connected()) { disconnect(); return; }
      try { await connect(); } catch (e) {
        if (e.name !== "NotFoundError")  // NotFoundError — ментор просто закрыл окно выбора
          alert("Не получилось подключиться: " + e.message);
      }
    };
  }
  document.addEventListener("DOMContentLoaded", initHeader);

  return {connect, disconnect, connected, send, walk, walkFor, stop,
          hands, legs, combo, dance, eyes, setSpeed, say, stopSpeech,
          onStatus: (cb) => statusCbs.push(cb),
          FORWARD, BACKWARD, LEFT, RIGHT, COLORS, PHRASES};
})();

/* ---------- Gemini прямо из браузера (каждый со своим ключом) ---------- */
const Gemini = {
  MODELS: ["gemini-flash-latest", "gemini-flash-lite-latest"],

  extractKey(text) {
    const m = (text || "").match(/AIza[0-9A-Za-z_\-]{10,}|AQ\.[0-9A-Za-z_\-]{20,}/);
    return m ? m[0] : "";
  },

  /** system + история [{role, content}] + вопрос → текст ответа */
  async ask(key, system, history, question) {
    key = this.extractKey(key);
    if (!key) throw new Error("это не похоже на ключ: ключ Gemini начинается с «AIza…» или «AQ.…» — скопируй его целиком на aistudio.google.com/apikey");
    const contents = history.slice(-10).map((m) => ({
      role: m.role === "user" ? "user" : "model",
      parts: [{text: String(m.content).slice(0, 2000)}],
    }));
    contents.push({role: "user", parts: [{text: question}]});
    const body = JSON.stringify({
      system_instruction: {parts: [{text: system}]},
      contents,
      generationConfig: {maxOutputTokens: 2048},
    });
    let overloaded = false;
    for (const model of this.MODELS) {
      for (const pause of [0, 1500]) {
        if (pause) await new Promise((r) => setTimeout(r, pause));
        let r;
        try {
          r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`,
            {method: "POST", headers: {"Content-Type": "application/json", "x-goog-api-key": key}, body});
        } catch {
          throw new Error("нет соединения с нейросетью — проверьте интернет");
        }
        if (r.status >= 500) { overloaded = true; continue; }
        if (r.status === 404) break;  // модели нет — к запасной
        if (r.status === 429) throw new Error("бесплатный лимит Gemini на минуту исчерпан — подождите немного");
        if (!r.ok) throw new Error("ключ Gemini не подошёл — проверь, что скопировал его целиком (выдаётся на aistudio.google.com/apikey)");
        const data = await r.json();
        const parts = data.candidates?.[0]?.content?.parts || [];
        const answer = parts.map((p) => p.text || "").join("").trim();
        if (!answer) throw new Error("нейросеть не ответила, попробуй переформулировать вопрос");
        return answer;
      }
    }
    throw new Error(overloaded
      ? "нейросеть Google сейчас перегружена — подождите минуту и спросите ещё раз"
      : "модели Gemini недоступны — попробуйте позже");
  },
};
