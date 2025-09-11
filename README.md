# CookaReq

Приложение на wxPython для работы с требованиями, сохраняемыми в виде JSON-файлов.

## Сборка

Для создания Windows-сборки используется PyInstaller (режим one-folder).

1. Установите PyInstaller, если он ещё не установлен:
   ```bash
   pip install pyinstaller
   ```
2. Запустите скрипт сборки:
   ```bash
   python build.py
   ```

Готовые файлы появятся в каталоге `dist/CookaReq`.

## Запуск тестов в контейнере

Чтобы прогонять тесты GUI без сборки wxPython из исходников,
установите готовые пакеты и зависимости из репозиториев Ubuntu:

```bash
apt-get update && apt-get install -y \
    python3-wxgtk4.0 python3-pip xvfb xauth
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install pytest pytest-xvfb jsonschema
pytest -q
```

`pytest-xvfb` автоматически поднимает виртуальный дисплей, поэтому
окна не появятся и тесты выполняются в headless-режиме.

