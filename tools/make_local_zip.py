"""Собрать архив локальной версии для менторов: robert-local.zip в корне проекта.

    python tools/make_local_zip.py

Внутри: папка robert-local с ЗАПУСК.bat, local_server.py, ЧЕК-ЛИСТ.txt и web/.
Имена файлов пишутся в UTF-8, чтобы русские названия не ломались при распаковке.
"""

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "robert-local.zip"
TOP = "robert-local"
FILES = ["ЗАПУСК.bat", "local_server.py", "ЧЕК-ЛИСТ.txt"]
SKIP_DIRS = {"__pycache__", ".git", "node_modules"}


def main():
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for name in FILES:
            z.write(ROOT / name, f"{TOP}/{name}")
        for p in sorted((ROOT / "web").rglob("*")):
            if p.is_dir() or SKIP_DIRS & set(p.parts):
                continue
            z.write(p, f"{TOP}/{p.relative_to(ROOT).as_posix()}")
    print(f"Готово: {OUT} ({OUT.stat().st_size // 1024} КБ)")


if __name__ == "__main__":
    main()
