"""Озвучка фраз диагностики в mp3-файлы для web/audio/diag.

Голос: Microsoft Dmitry (нейросетевой, бесплатный, через edge-tts). Нужен интернет
только в момент озвучки, дальше файлы работают без сети.

Запуск (один раз, из папки проекта):
    python -m venv .venv-voice
    .venv-voice\\Scripts\\pip install edge-tts
    .venv-voice\\Scripts\\python tools\\make_voice.py

Фразы с {имя} и {имена} пропускаются: их робот говорит голосом браузера.
Уже озвученные файлы не переделываются, если текст не менялся (см. audio/diag/index.json).
"""
import asyncio
import json
import re
import sys
from pathlib import Path

VOICE = "ru-RU-DmitryNeural"
RATE = "+0%"

ROOT = Path(__file__).resolve().parent.parent
PHRASES_JS = ROOT / "web" / "diag_phrases.js"
OUT = ROOT / "web" / "audio" / "diag"


def load_phrases():
    text = PHRASES_JS.read_text(encoding="utf-8")
    m = re.search(r"const DIAG_PHRASES\s*=\s*(\{.*\});", text, re.S)
    if not m:
        sys.exit("не нашёл JSON в " + str(PHRASES_JS))
    return json.loads(m.group(1))


async def main():
    try:
        import edge_tts
    except ImportError:
        sys.exit("нет edge-tts: установите  pip install edge-tts")

    OUT.mkdir(parents=True, exist_ok=True)
    index_file = OUT / "index.json"
    done = json.loads(index_file.read_text(encoding="utf-8")) if index_file.exists() else {}

    jobs = []
    for stage in load_phrases()["stages"]:
        for btn in stage["buttons"]:
            for i, phrase in enumerate(btn["phrases"]):
                if "{имя}" in phrase or "{имена}" in phrase:
                    continue
                name = f"{btn['id']}-{i}.mp3"
                if done.get(name) == phrase and (OUT / name).exists():
                    continue
                jobs.append((name, phrase))

    if not jobs:
        print("всё уже озвучено")
        return
    for name, phrase in jobs:
        print(name, "<-", phrase)
        await edge_tts.Communicate(phrase, VOICE, rate=RATE).save(str(OUT / name))
        done[name] = phrase
        index_file.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"готово: {len(jobs)} файлов в {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
