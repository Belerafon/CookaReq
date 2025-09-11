# CookaReq

Приложение на wxPython для работы с требованиями, сохраняемыми в виде JSON-файлов.

## Сборка

Для создания Windows-сборки используется PyInstaller. Важно собирать в том же окружении, где установлены все зависимости (wxPython и jsonschema), иначе в сборку не попадут нужные пакеты.

1) Подготовьте окружение

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
pip install pyinstaller
```

2) Соберите приложение (режим one-folder по умолчанию)

```bash
python build.py
```

Готовые файлы появятся в каталоге `dist/CookaReq`. Этот вариант самодостаточный: папка содержит все нужные DLL/библиотеки.

3) Альтернатива: один файл (one-file)

```bash
python build.py --onefile
```

Будет создан один `CookaReq.exe`, который при запуске распаковывается во временную папку. Такой EXE также самодостаточный и не зависит от установленных модулей в системе.

Примечание: если при запуске EXE видите `ModuleNotFoundError: No module named 'wx'`, значит wxPython не был установлен в окружение, в котором выполнялся `build.py`. Убедитесь, что выполняли сборку из активированного venv с установленными зависимостями (см. шаг 1).

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
