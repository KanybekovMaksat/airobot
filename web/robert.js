/* Роберт в браузере: Web Bluetooth (протокол Robert RS01) + речь + общая шапка страниц.
   Работает в Chrome и Edge по HTTPS (или на localhost). */

const Robert = (() => {
  // ---------- протокол (как в robot_ble.py) ----------
  const SERVICE = 0xffc0, WRITE_CHAR = 0xffc1;
  // Проверено на роботе: 1 — вперёд, 2 — назад (в старой прошивке считалось наоборот)
  const FORWARD = 1, BACKWARD = 2, LEFT = 3, RIGHT = 4, IDLE = 77;
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

  // Связь оборвалась сама (помехи, фоновая вкладка, робот занят звуком) —
  // переподключаемся, пока ментор не нажал «Отключить» или робот не выключился
  let reconnecting = false;
  async function tryReattach() {
    if (reconnecting || !wantConnected || !device || connected()) return;
    reconnecting = true; connecting = true; notify();
    for (let i = 0; wantConnected && device && !connected(); i++) {
      try { await attach(); lastWrite = Date.now(); break; } catch {}
      // первые попытки — сразу, дальше — раз в 5 секунд, не сдаёмся
      await new Promise((r) => setTimeout(r, Math.min(5000, 1000 + i * 1000)));
    }
    reconnecting = false; connecting = false; notify();
  }

  function onDropped() {
    writeChar = null; notify();
    tryReattach();
  }

  // Вкладка вернулась на передний план — фоновые таймеры Chrome спали, проверяем связь
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) tryReattach();
  });

  function disconnect() {
    wantConnected = false;
    if (device && device.gatt.connected) {
      try { send(IDLE); } catch {}
      device.gatt.disconnect();
    }
    writeChar = null; notify();
  }

  // «Пульс» и сторож: робот засыпает через ~8 минут без команд — в тишине шлём
  // безобидный «стоп»; а если связь порвалась незаметно — пробуем переподключиться.
  // Интервал с запасом: в фоновой вкладке Chrome будит таймеры не чаще раза в минуту.
  setInterval(() => {
    if (connected()) {
      if (Date.now() - lastWrite > 60000) { try { send(IDLE); } catch {} }
    } else {
      tryReattach();
    }
  }, 15000);

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

  // ---------- речь: записанный голос из audio/diag или синтез браузера (робот сопряжён как колонка — звук идёт из него) ----------
  let ruVoice = null;
  function findVoice() {
    const vs = speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith("ru"));
    // Нейросетевые голоса Edge (Dmitry/Svetlana «Natural») звучат заметно лучше обычных
    ruVoice = vs.find((v) => /natural|online/i.test(v.name))
      || vs.find((v) => /irina|milena|svetlana|google/i.test(v.name)) || vs[0] || null;
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

  // Записанный голос Роберта: фраза → mp3 в audio/diag. Сравниваем без знаков препинания и регистра,
  // поэтому «Урок закончен, не забудьте…» и «Урок закончен. Не забудьте…» — одна запись.
  const RECORDED_LIST = [
    ["Всем привет! Меня зовут Роберт, и я робот IT-школы Кодифай.", "hello-0"],
    ["Я Роберт, танцующий робот IT-школы Кодифай. Я умею ходить, танцевать, менять цвет глаз и слушать ваши команды.", "about-0"],
    ["Друзья, пора учиться. Сегодня мы научимся чему-то новому, так что рассаживайтесь поудобнее. Мы начинаем!", "start-0"],
    ["Почему робот не боится темноты? Потому что у него глаза светятся! Ха-ха.", "joke-0"],
    ["Почему робот не боится темноты? Потому что у него глаза светятся!", "joke-0"],
    ["Какой у робота любимый танец? Робот-н-ролл! Ха-ха-ха.", "joke-1"],
    ["Какой у робота любимый танец? Робот-н-ролл!", "joke-1"],
    ["Я не ленивый робот, я просто в режиме энергосбережения.", "joke-2"],
    ["Вот это да! Вы настоящие программисты!", "final_done-0"],
    ["Урок закончен, не забудьте сохранить свои проекты. Пока!", "bye-0"],
  ];
  // Метка версии записей. Поменяйте её, когда заменили mp3 на новый с тем же именем,
  // иначе браузер будет играть старый файл из кеша.
  const AUDIO_VERSION = "2026-10-02b";
  const audioUrl = (file) => `audio/diag/${file}?v=${AUDIO_VERSION}`;
  const normText = (t) => String(t).toLowerCase().replace(/ё/g, "е").replace(/[^a-zа-я0-9]+/g, "");
  const RECORDED = Object.fromEntries(RECORDED_LIST.map(([t, f]) => [normText(t), audioUrl(f + ".mp3")]));
  let recordedAudio = null;
  const addRecording = (text, file) => { RECORDED[normText(text)] = audioUrl(file); };

  function playRecorded(src, volume) {
    return new Promise((resolve, reject) => {
      const a = new Audio(src);
      recordedAudio = a;
      a.volume = volume;
      a.onended = () => { if (recordedAudio === a) recordedAudio = null; resolve(); };
      a.onerror = () => { if (recordedAudio === a) recordedAudio = null; reject(new Error("нет файла " + src)); };
      a.play().catch(reject);
    });
  }

  function sayBrowser(text, rate, volume) {
    if (!window.speechSynthesis) return Promise.resolve();
    return new Promise((resolve) => {
      const u = new SpeechSynthesisUtterance(pronounce(text));
      u.lang = "ru-RU";
      if (ruVoice) u.voice = ruVoice;
      u.rate = rate; u.volume = volume;
      u.onend = resolve; u.onerror = resolve;
      speechSynthesis.speak(u);
    });
  }

  // Сначала записанный голос Роберта, если такой фразы нет или файл не загрузился — голос браузера
  function say(text, {gesture = true, rate = 1, volume = 1} = {}) {
    stopSpeech();
    if (gesture && connected()) { try { hands(); } catch {} }
    const src = RECORDED[normText(text)];
    if (src) return playRecorded(src, volume).catch(() => sayBrowser(text, rate, volume));
    return sayBrowser(text, rate, volume);
  }

  const stopSpeech = () => {
    if (recordedAudio) { recordedAudio.pause(); recordedAudio = null; }
    if (window.speechSynthesis) speechSynthesis.cancel();
  };

  // ---------- фразы ----------
  // Только фразы, записанные голосом Роберта (см. RECORDED_LIST). Новую фразу сначала записать в mp3.
  const PHRASES = {
    "Приветствие": [
      "Всем привет! Меня зовут Роберт, и я робот IT-школы Кодифай.",
    ],
    "О себе": [
      "Я Роберт, танцующий робот IT-школы Кодифай. Я умею ходить, танцевать, менять цвет глаз и слушать ваши команды.",
    ],
    "Начало урока": [
      "Друзья, пора учиться. Сегодня мы научимся чему-то новому, так что рассаживайтесь поудобнее. Мы начинаем!",
    ],
    "Шутки": [
      "Почему робот не боится темноты? Потому что у него глаза светятся! Ха-ха.",
      "Какой у робота любимый танец? Робот-н-ролл! Ха-ха-ха.",
      "Я не ленивый робот, я просто в режиме энергосбережения.",
    ],
    "Похвала": [
      "Вот это да! Вы настоящие программисты!",
    ],
    "Конец урока": [
      "Урок закончен, не забудьте сохранить свои проекты. Пока!",
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
    // Бургер-меню: закрывать по клику мимо и по Esc
    const menu = document.querySelector(".topbar .menu");
    if (menu) {
      document.addEventListener("click", (e) => { if (!menu.contains(e.target)) menu.open = false; });
      document.addEventListener("keydown", (e) => { if (e.key === "Escape") menu.open = false; });
    }
  }
  document.addEventListener("DOMContentLoaded", initHeader);

  return {connect, disconnect, connected, send, walk, walkFor, stop,
          hands, legs, combo, dance, eyes, setSpeed, say, stopSpeech, addRecording,
          playAudio: (src) => playRecorded(src, 1),
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

/* ---------- ElevenLabs: озвучка фраз с именами детей тем же голосом Роберта ----------
   Ключ и голос хранятся только в браузере ментора (localStorage). Готовый звук кладём
   в кеш браузера (Cache API), чтобы одно и то же имя не озвучивать дважды и не тратить лимит. */
const ElevenLabs = {
  API: "https://api.elevenlabs.io/v1",
  MODEL: "eleven_multilingual_v2",
  KEY_STORE: "eleven_key",
  VOICE_STORE: "eleven_voice",
  memory: new Map(),  // text → blob-URL на эту сессию

  key() { try { return (localStorage.getItem(this.KEY_STORE) || "").trim(); } catch { return ""; } },
  voiceId() { try { return (localStorage.getItem(this.VOICE_STORE) || "").trim(); } catch { return ""; } },
  setKey(v) { try { localStorage.setItem(this.KEY_STORE, (v || "").trim()); } catch {} },
  setVoice(v) { try { localStorage.setItem(this.VOICE_STORE, (v || "").trim()); } catch {} },
  ready() { return !!(this.key() && this.voiceId()); },

  async request(path, init = {}) {
    const key = this.key();
    if (!key) throw new Error("нет ключа ElevenLabs — вставьте его в карточке «Голос для имён»");
    let r;
    try {
      r = await fetch(this.API + path, {...init, headers: {"xi-api-key": key, ...(init.headers || {})}});
    } catch {
      throw new Error("нет соединения с ElevenLabs — проверьте интернет");
    }
    if (r.ok) return r;
    let detail = null;
    try { detail = (await r.json()).detail; } catch {}
    if (detail?.status === "missing_permissions") {
      const perm = (detail.message || "").match(/permission (\w+)/)?.[1] || "";
      throw new Error(perm === "voices_read"
        ? "у ключа нет права на список голосов — впишите ID голоса вручную или выпустите ключ с правами Voices: Read и Text to Speech"
        : "у ключа ElevenLabs нет права " + perm + " — выпустите ключ с правами Text to Speech");
    }
    if (detail?.code === "paid_plan_required")
      throw new Error("этот голос из библиотеки ElevenLabs, на бесплатном тарифе он через API не работает — выберите голос с пометкой «базовый» или оформите платный тариф");
    if (r.status === 401) throw new Error("ключ ElevenLabs не подошёл — проверьте, что скопировали его целиком");
    if (r.status === 402 || r.status === 429) throw new Error("лимит символов ElevenLabs исчерпан — подождите или пополните тариф");
    const msg = typeof detail === "string" ? detail : detail?.message || "";
    throw new Error("ElevenLabs ответил ошибкой " + r.status + (msg ? ": " + msg : ""));
  },

  /** Список голосов аккаунта: [{id, name}] */
  async voices() {
    const data = await (await this.request("/voices")).json();
    // category: premade — базовые голоса ElevenLabs (есть на бесплатном тарифе),
    // cloned/generated — свои, professional — из библиотеки (через API только на платном тарифе)
    const kind = {premade: "базовый", cloned: "свой клон", generated: "свой", professional: "библиотека, платно"};
    return (data.voices || []).map((v) => ({id: v.voice_id, name: v.name, category: v.category, kind: kind[v.category] || v.category || ""}));
  },

  cacheKey(text) { return "/eleven/" + this.voiceId() + "/" + encodeURIComponent(text); },

  /** Текст → URL готового mp3 (из кеша или с сервера) */
  async synth(text) {
    text = String(text).trim();
    if (this.memory.has(text)) return this.memory.get(text);
    const voice = this.voiceId();
    if (!voice) throw new Error("не выбран голос ElevenLabs — выберите его в карточке «Голос для имён»");
    let cache = null;
    try { cache = window.caches ? await caches.open("eleven-voice") : null; } catch {}
    let blob = null;
    if (cache) { const hit = await cache.match(this.cacheKey(text)); if (hit) blob = await hit.blob(); }
    if (!blob) {
      const r = await this.request(`/text-to-speech/${voice}?output_format=mp3_44100_128`, {
        method: "POST",
        headers: {"Content-Type": "application/json", "Accept": "audio/mpeg"},
        body: JSON.stringify({text, model_id: this.MODEL}),
      });
      blob = await r.blob();
      if (cache) { try { await cache.put(this.cacheKey(text), new Response(blob, {headers: {"Content-Type": "audio/mpeg"}})); } catch {} }
    }
    const url = URL.createObjectURL(blob);
    this.memory.set(text, url);
    return url;
  },

  /** Озвучить сразу: сгенерировать (или взять из кеша) и проиграть */
  async say(text) {
    const url = await this.synth(text);
    Robert.stopSpeech();
    return Robert.playAudio(url);
  },
};
