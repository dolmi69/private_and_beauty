# Запуск проекта на MacBook

В архив уже включена SQLite-база с шестью врачами и временным администратором:

- логин: `admin`
- пароль: `admin`

## Быстрый запуск

1. Распакуйте архив в обычную папку, например `Documents/everwell-clinic-ru`.
2. Установите Python 3.12 или новее с [python.org](https://www.python.org/downloads/macos/), если его ещё нет.
3. Откройте Terminal и перейдите в распакованную папку.
4. Выполните:

```bash
chmod +x start_mac.command
./start_mac.command
```

При первом запуске скрипт создаст `.venv`, установит зависимости, применит миграции и откроет сайт. В следующие разы можно снова запускать `./start_mac.command`.
Он также добавит свободное время врачей на ближайшие 21 день. Клиенты регистрируются на `/register/`, менеджер создаёт доступ врачу на `/manager/team/`.

Сайт: [http://127.0.0.1:8001/](http://127.0.0.1:8001/)

Админ-панель: [http://127.0.0.1:8001/manager/dashboard/](http://127.0.0.1:8001/manager/dashboard/)

Остановить сервер можно сочетанием `Control+C` в Terminal.

## Ручной запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver 127.0.0.1:8001
```

Файл `.env.example` не содержит API-ключей. Без ключа ГигаЧата помощник работает в локальном демонстрационном режиме.

Пароль `admin` подходит только для локальной демонстрации. Перед публикацией сайта создайте безопасный пароль командой:

```bash
source .venv/bin/activate
python manage.py changepassword admin
```
