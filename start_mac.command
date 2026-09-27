#!/bin/bash
# Первый запуск создаёт локальное окружение и устанавливает зависимости.
# Последующие запуски сразу открывают сайт на http://127.0.0.1:8001/.
set -e

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Не найден Python 3. Установите Python 3.12+ с https://www.python.org/downloads/macos/"
  read -r -p "Нажмите Enter, чтобы закрыть окно..."
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 12):
    raise SystemExit("Нужен Python 3.12 или новее.")
PY

if [ ! -x ".venv/bin/python" ]; then
  echo "Создаю виртуальное окружение..."
  python3 -m venv .venv
fi

echo "Устанавливаю зависимости..."
.venv/bin/python -m pip install -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
fi

echo "Проверяю базу данных..."
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_slots

echo "Открываю LAVIE — салон красоты..."
(sleep 2 && open "http://127.0.0.1:8001/") &
.venv/bin/python manage.py runserver 127.0.0.1:8001
