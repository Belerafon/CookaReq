Адаптируй детали и Делай подзадачи 
PROMPT ДЛЯ АГЕНТА (СЕБЯ ЖЕ): Реализация иерархических требований в CookaReq «как в Doorstop», но под архитектуру CookaReq

Роль и цель

Ты — ведущий разработчик CookaReq. Нужно переписать хранилище и логику требований под модель «Документы → Элементы → Ссылки вверх», добавить древо документов в GUI, листы по документам, линковку и лайт-матрицу трассировки. Без старого режима: сразу новый формат.
Fingerprint/suspect/строгие проверки покрытия — не делаем в этом этапе.
Labels переносим в document.json c наследованием SYS→HLR→LLR.



---

Что реализуем (кратко)

1. Файловая структура:



project_root/
  requirements/
    SYS/
      document.json
      items/
        SYS001.json
        SYS002.json
    HLR/
      document.json   # parent = "SYS"
      items/
        HLR001.json
    LLR/
      document.json   # parent = "HLR"
      items/
        LLR001.json
  attachments/
  src/
  tests/

2. Документ (requirements/<PREFIX>/document.json) — задаёт префикс, ширину номера, родителя, метки.


3. Элемент (requirements/<PREFIX>/items/<RID>.json) — требования с полями, включая links: [ "<PARENT_RID>", ... ].


4. RID = prefix + id с паддингом digits (имя файла). Внутри храним числовой id.


5. Labels живут в document.json, наследуются вниз. Можно запретить свободный ввод меток.


6. GUI: слева дерево документов, по центру лист выбранного документа, редактор элемента с Tags и Links, вкладка Trace (light), граф с раскраской по документам.


7. CLI: doc create/list, item add/move, link, export trace.


8. Миграция: команда migrate to-docs — один раз преобразует старую «кучу» в новую структуру.




---

Инварианты/ограничения

Только новая структура. Старую поддерживать не нужно.

Проверки ссылок — только на существование и что ссылка указывает в родительские документы.

Не реализовывать: suspect/fingerprint, strict child coverage check, публикацию HTML, сложную перенумерацию.

GUI — wxPython; сохраняем стилистику и текущие окна/логи/локализацию.

Локализация: строки в .po пополнить.



---

Форматы данных (JSON Schema — ориентиры)

document.json

{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "CookaReq Document",
  "type": "object",
  "required": ["prefix", "title", "digits"],
  "properties": {
    "prefix":   { "type": "string", "pattern": "^[A-Z][A-Z0-9_]*$" },
    "title":    { "type": "string", "minLength": 1 },
    "digits":   { "type": "integer", "minimum": 1, "maximum": 6 },
    "parent":   { "type": ["string", "null"], "pattern": "^[A-Z][A-Z0-9_]*$" },
    "labels": {
      "type": "object",
      "properties": {
        "allowFreeform": { "type": "boolean", "default": false },
        "defs": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["key", "title"],
            "properties": {
              "key":   { "type": "string", "pattern": "^[a-z0-9_-]+$" },
              "title": { "type": "string" },
              "color": { "type": "string", "pattern": "^#([0-9a-fA-F]{6})$" }
            }
          }
        }
      },
      "additionalProperties": false
    },
    "attributes": { "type": "object", "additionalProperties": true }
  },
  "additionalProperties": false
}

items/<RID>.json

{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "CookaReq Item",
  "type": "object",
  "required": ["id", "title", "text"],
  "properties": {
    "id":         { "type": "integer", "minimum": 1 },
    "title":      { "type": "string", "minLength": 1 },
    "text":       { "type": "string", "minLength": 1 },
    "level":      { "type": ["string", "null"], "pattern": "^[0-9]+(\\.[0-9]+)*$" },
    "active":     { "type": "boolean", "default": true },
    "normative":  { "type": "boolean", "default": true },
    "derived":    { "type": "boolean", "default": false },
    "labels":     { "type": "array", "items": { "type": "string" } },
    "links":      { "type": "array", "items": { "type": "string", "pattern": "^[A-Z][A-Z0-9_]*[0-9]{1,6}$" } },
    "references": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["path"],
        "properties": {
          "path":    { "type": "string" },
          "keyword": { "type": ["string", "null"] },
          "type":    { "type": ["string", "null"], "enum": [null, "file", "url"] }
        }
      }
    },
    "attachments": { "type": "array", "items": { "type": "string" } },
    "created_at":  { "type": ["string", "null"], "format": "date-time" },
    "modified_at": { "type": ["string", "null"], "format": "date-time" },
    "revision":    { "type": "integer", "minimum": 0 }
  },
  "additionalProperties": true
}


---

Архитектура кода (модули/классы/сигнатуры)

Слой хранилища

core/documents.py

class Document: prefix, title, digits, parent, labels, attributes, path

class DocumentRegistry:

load_all(root: Path) -> dict[str, Document]

children_of(prefix: str) -> list[str]

parent_of(prefix: str) -> str|None

ensure_tree_is_acyclic()

effective_labels(prefix: str) -> dict[str, LabelDef]  (merge родитель→дети)



core/items.py

class Item: doc_prefix, id, title, text, level, active, normative, derived, labels, links, ...

rid(item) -> str  (формирование по doc_prefix/digits)

parse_rid(rid: str) -> (prefix: str, id: int)


core/store.py

class ItemStore:

read_item(rid: str) -> Item

write_item(item: Item) -> None

delete_item(rid: str) -> None

generate_id(prefix: str) -> int

move_item(rid: str, new_prefix: str) -> str  (перенос файла, пересчёт имени)



core/index.py

class Index:

index_documents(reg: DocumentRegistry)

index_items(store: ItemStore)

by_rid: dict[str, Item], by_prefix: dict[str, list[Item]]

search(query: str, *, prefix: str|None, labels: list[str]|None) -> list[Item]



core/links.py

class LinkResolver:

validate_links(item: Item, reg: DocumentRegistry, index: Index) -> list[Error]
(проверка: все links существуют и принадлежат родительским документам)




CLI

app/cli/doc.py:

doc create <PREFIX> <PATH> [--title --digits --parent]

doc list


app/cli/item.py:

item add <PREFIX> --title --text [--level] [--labels a,b]

item move <RID> <NEW_PREFIX>

link <CHILD_RID> <PARENT_RID...>

export trace --from <PARENT_PREFIX> --to <CHILD_PREFIX> --out <FILE>



GUI (wxPython)

Sidebar Documents: ui/panels/doc_tree.py

List View per Document: ui/panels/doc_list.py

Editor Panel (Item): ui/panels/item_editor.py (Labels, Links)

Document Settings Dialog: ui/dialogs/document_settings.py (title/digits/parent/labels)

Trace View (light): ui/panels/trace_light.py (две колонки + CSV export)

Graph View recolor: ui/panels/graph_view.py (цвет по prefix)


Миграция

tools/migrate_to_docs.py:

CLI:

cookareq migrate to-docs \
  --rules "tag:doc=SYS->SYS; tag:doc=HLR->HLR; tag:doc=LLR->LLR" \
  --default SYS

Шаги: создать каталоги/document.json, разнести элементы, пересчитать имена файлов, преобразовать trace_up→links (RID), собрать/раскидать labels.



---

GUI: UX-детализация

Sidebar «Documents»

Дерево: корни без parent, дети — по parent.

Контекстное меню: New Document, Edit, Delete (Delete — с проверкой, что items/ пуст).


Лист документа

Таблица: RID, Title, Level, Active, Normative, Tags (бейджи), Links (счётчик), Attach.

Фильтры: строка поиска, чекбокс «только активные», выпадающий список по меткам (из effective_labels).

Действия: Add Item, Link to parent…, Export Trace (если документ — родитель/ребёнок).


Редактор элемента

Верх: RID (ro), Title, Level, чекбоксы Active/Normative/Derived.

Вкладки: Text, Tags, Links, References, Attachments.

Tags: мультиселект с цветом; если allowFreeform=false, блокировать неразрешённые.

Links: кнопка «Link to parent…» открывает диалог выбора элементов родительского документа с поиском по id/title/text.

Сохранение — авто-апдейт modified_at, revision += 1.


Trace (light)

Комбо «Пара уровней»: SYS→HLR, HLR→LLR, LLR→TST_... (если тестовые доки будут).

Таблица: Parent RID | Parent Title | Children (RID list)

Кнопка «Export CSV».


Graph View

Узлы — цвет по prefix.

Переключатели: «только вверх», «только вниз», «только текущий документ».


Document Settings

Поля: Title, Prefix (ro после создания), Digits, Parent (drop-down; не допускать циклов), Labels (список ключ/название/цвет, add/remove).

Кнопка «Rebuild effective labels preview».



---

Логика labels (наследование)

effective_labels(prefix) делает merge: labels(SYS) ∪ labels(HLR) ∪ labels(LLR) (низы перекрывают верхи по key).

В редакторе элемента отображаем effective.

Валидация: если allowFreeform=false в текущем документе, то каждый tag ∈ effective_labels.keys().



---

Правила ссылок (links)

links указывают только на элементы документов-предков по цепочке parent.

Ссылки хранятся как отсортированный список без дубликатов. В Doorstop допускается произвольная линковка и проверяется отсутствие циклических зависимостей; у нас ссылки разрешены только вверх по иерархии, поэтому циклы и self-link невозможны, но попытки связать элемент с самим собой следует отклонять.

При сохранении элемента выполняй:

Парс links → проверка формата RID → index.by_rid наличие → проверка parent-цепочки.

Невалидные — блокировать/отклонять с понятной ошибкой.

Экспорт трассировки выполняет генератор `iter_links`, выдающий пары `child parent`. Doorstop строит полноценную матрицу (CSV/HTML); текущий упрощённый формат служит основой для дальнейшего развития.



---

Тест-план (минимальный)

1. Unit: core

RID parse/format, generate_id, move_item, effective_labels merge, validate_links OK/FAIL.



2. Integration: repository + on-disk

Создание документов, добавление/перенос/удаление элементов, миграция на фикстурах.



3. GUI smoke

Открыть проект, щёлкать документы, добавить элемент, проставить теги/ссылки, экспорт CSV.



4. CLI

doc create/list, item add/move, link, export trace.



5. I18N

Строки отображаются в ru/… локалях, отсутствующие — fallback.



---

Порядок работ и PR-ы (пошагово)

PR1 — Модель/хранилище

Добавить Document, DocumentRegistry, ItemStore, Index, LinkResolver.

Создать новую константу пути REQUIREMENTS_ROOT.

Реализовать CRUD, RID, id-генерацию, валидацию ссылок.

Юнит-тесты на все классы.


PR2 — CLI: документы и элементы

doc create/list, item add, link, item move, export trace.

Интеграционные тесты CLI (pytest + tmp dir).


PR3 — GUI: Sidebar и списки

Панель дерева документов.

Листы документов с фильтрами/поиском.

Открытие редактора элемента.


PR4 — GUI: Редактор (Tags/Links), Document Settings

Вкладки Tags/Links, диалог линковки.

Диалог настроек документа (labels/parent/digits).


PR5 — Trace (light) и Graph recolor

Таблица покрытия, экспорт CSV.

Граф: цвета по prefix, фильтры.


PR6 — Мигратор

migrate to-docs с правилами/дефолтом.

Документация «как запустить».


PR7 — Полировка и I18N

Локализация строк, улучшения UX, сообщения об ошибках.



---

Критерии готовности (Definition of Done)

Проект с requirements/SYS/HLR/LLR открывается, дерево строится без циклов.

Создаю элементы, присваиваются корректные RID, работает фильтр/поиск/теги.

Линковка ограничена к родителям; невалидные RID блокируются с сообщением.

Trace (light) показывает соответствия и экспортируется в CSV.

Graph окрашен по документам и фильтруется.

Мигратор переносит старые файлы в новую структуру (по правилам), сохраняет связи/метки.

CLI покрывает основные операции; есть тесты.



---

Нефункциональные требования

Производительность: загрузка 5–10k элементов < 2с на средне-мощной машине.

Атомарность записи: запись элемента — через временный файл и rename.

Логи: информативно логировать CRUD/миграции/линковку в окно логов и файл.

Надёжность: валидация JSON против схем при сохранении; дружелюбные ошибки.

Совместимость: проект, созданный новой версией, открывается без плясок (нет legacy).



---

RACI для себя

Я делаю всё по описанным PR. При необходимости — создаю мини-моки/фикстуры.

Каждый PR — компактный, с тестами, с понятным CHANGELOG фрагментом.



---

Стретч-цели (если останется время)

Автозаполнение Links по поиску текста в родителях.

Копирование/перемещение элементов мышью между листами (drag&drop) с автолинком.

Мини-диаграмма покрытия в Trace (heatmap).



---

Коммит-месседжи — стиль

core(storage): add DocumentRegistry and ItemStore with RID support

cli: add doc create/list, item add/move, link, export trace

gui: documents sidebar and per-document list view

gui: item editor labels/links and document settings

trace: light matrix view + csv export

tooling: migrate to new documents structure



---

Сразу начинай с PR1 (модель/хранилище). После мерджа PR1 — CLI (PR2), потом GUI (PR3/PR4), затем Trace/Graph (PR5) и Мигратор (PR6).
# AGENTS

Этот файл содержит инструкции и краткую архитектуру приложения "CookaReq".

## Общие инструкции
- Работать в основной ветке (без новых веток).
- Запускать `pytest -q`; тесты с маркером `slow` пропускаются.
- При повторном включении тестов, использующие `wx`, должны запускаться в виртуальном дисплее
  (плагин `pytest-xvfb` или обёртка `xvfb-run -a`).
- Для сборки и тестов использовать системный Python 3.12.3.
  В корне лежит файл `.python-version` со значением `system`, поэтому
  `pyenv` переключается автоматически; запускать команды следует через `python3`.
  Команда `python` отсутствует, используйте `python3`.
- Ключ OpenRouter хранится в файле `.env` в корне репозитория в переменной
  `OPEN_ROUTER`. Тесты и приложение читают ключ из окружения при наличии.
- По умолчанию тесты используют мок LLM и не обращаются к внешнему API.
  Чтобы запустить реальные интеграционные проверки, установите
  `COOKAREQ_RUN_REAL_LLM_TESTS=1` и выполняйте тесты с маркером `real_llm`,
  например:
  `COOKAREQ_RUN_REAL_LLM_TESTS=1 pytest tests/test_llm_openrouter_integration.py::test_openrouter_check_llm -q`.
  Без ключа `OPEN_ROUTER` или указанного флага такие тесты будут пропущены.

## Архитектура

### Слои и модули

#### Точка входа
- `app/main.py` — запуск графического приложения и создание главного окна.
- `app/cli/main.py` — консольный интерфейс: работа с требованиями и проверка настроек (запуск через `python3 -m app.cli`).
- `app/cli/commands.py` — обработчики команд `doc`, `item`, `link`, `trace`.

#### Настройки и конфигурация
- `app/settings.py` — Pydantic‑модели `LLMSettings`, `MCPSettings`, `UISettings` и агрегирующий `AppSettings`.
- `app/config.py` — обёртка над `wx.Config` с typed‑хелперами.

#### Бизнес-логика (`app/core`)
- `model.py` — dataclass `Requirement` и перечисления статусов.
- `schema.py` — JSON Schema для требований.
- `validate.py` — проверка бизнес-правил (уникальность id, обязательные поля).
- `labels.py` — предустановленные наборы меток и CRUD-операции в памяти.
- `store.py` — низкоуровневое чтение/запись JSON и генерация имён по идентификатору.
- `requirements.py` — высокоуровневые операции загрузки, поиска и сохранения.
- `repository.py` — интерфейс `RequirementRepository` и файловая реализация.
- `search.py` — фильтрация по меткам, статусу и текстовый поиск.
- `doc_store.py` — загрузка документов, генерация идентификаторов и проверка иерархии.

#### Сервисы и инфраструктура
- `app/agent/local_agent.py` — комбинирует LLM и MCP-клиенты, предоставляя высокоуровневые операции.
- `app/llm` — интеграция с LLM: `LLMClient` и описание схемы инструментов (`spec.py`).
- `app/mcp` — HTTP‑сервер/клиент MCP и набор инструментов:
  `server.py`, `tools_read.py`, `tools_write.py`, `client.py`, `utils.py`.
- `app/mcp/controller.py` — запуск и мониторинг MCP‑сервера.
- `app/log.py` — настройка логирования и JSONL‑обработчик.
- `app/telemetry.py` — единая точка логирования с редактированием чувствительных данных.
- `app/confirm.py` — регистрация и вызов функций подтверждения действий.
- `app/i18n.py` — загрузка переводов из `.po`‑файлов.
- `app/resources/` — статические файлы (иконки и пр.).

#### Пользовательский интерфейс (`app/ui`)
- `main_frame.py` — основное окно, меню, выбор папки.
- `list_panel.py` — список требований и фильтры/поиск.
- `editor_panel.py` — форма редактирования требований.
- `command_dialog.py` — ввод команд для `LocalAgent`.
- `settings_dialog.py` — редактирование настроек LLM/MCP/UI.
- `labels_dialog.py` — управление набором меток.
- `label_selection_dialog.py` — выбор меток из пресетов.
- `filter_dialog.py` — расширенные фильтры поиска.
- `derivation_graph.py` — граф отображения зависимых требований.
- `navigation.py` — навигация по связям требований.
- `requirement_model.py` — in-memory модель с фильтрацией и сортировкой.
- `locale.py` — словарь кодов ↔ русский текст.
- `controllers/requirements.py` — загрузка и CRUD‑операции над требованиями.
- `controllers/labels.py` — управление метками и синхронизация с требованиями.

#### Утилиты
- `app/util/hashing.py` — преобразование id в короткий SHA‑256 хэш.
- `app/util/paths.py` — работа с относительными путями.


#### Сборка
- `build.py` — упаковка проекта через PyInstaller (one-folder).

### Связи между слоями
- GUI (`app/ui`) обращается к контроллерам, которые взаимодействуют с сервисами и модулем `app/core`.
- `LocalAgent` использует `LLMClient` и `MCPClient`; последний вызывает инструменты MCP‑сервера, работающие поверх хранилища требований.
- Бизнес‑логика (`app/core`) оперирует файлами JSON на диске, выступая слоем хранилища.

### Порядок запуска
1. `main.py` настраивает логирование и конфигурацию, инициализирует локализацию.
2. Создаётся модель требований и основной `MainFrame`.
3. При необходимости пользователь запускает MCP‑сервер через `MCPController` или обращается к `LocalAgent` из GUI/CLI.

### Точки расширения
- Добавление новых MCP‑инструментов в `app/mcp/tools_*` и соответствующих схем в `app/llm/spec.py`.
- Расширение телеметрии через новые события в `log_event`.
- Внедрение новых панелей/диалогов в `app/ui` и соответствующих контроллеров.
- Подмена хранилища, реализовав альтернативы `app/core/store.py`.
 
## Сборка

Для создания Windows-сборки используется PyInstaller. Важно собирать в том же
окружении, где установлены все зависимости (wxPython и jsonschema), иначе в
сборку не попадут нужные пакеты.

1) Подготовьте окружение

```bash
python3 -m venv .venv
source .venv/bin/activate  # в Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller
```

2) Соберите приложение (режим one-folder по умолчанию)

```bash
python3 build.py
```

Готовые файлы появятся в каталоге `dist/CookaReq`. Этот вариант
самодостаточный: папка содержит все нужные DLL/библиотеки.

3) Альтернатива: один файл (one-file)

```bash
python3 build.py --onefile
```

Будет создан `CookaReq.exe`, который при запуске распаковывается во временную
папку. Такой EXE также самодостаточный и не зависит от установленных модулей в
системе.

Примечание: если при запуске EXE видите `ModuleNotFoundError: No module named 'wx'`,
значит wxPython не был установлен в окружении, в котором выполнялся `build.py`.
Убедитесь, что выполняли сборку из активированного venv с установленными
зависимостями (см. шаг 1).

## Тестирование

Чтобы прогонять тесты GUI без сборки wxPython из исходников, установите
готовые пакеты и зависимости из репозиториев Ubuntu:

```bash
apt-get update && apt-get install -y \
    python3-wxgtk4.0 python3-pip xvfb xauth
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install pytest pytest-xvfb jsonschema
pytest -q
```

`pytest-xvfb` автоматически поднимает виртуальный дисплей, поэтому окна не
появятся и тесты выполняются в headless-режиме.

Для запусков вне `pytest` (отдельные скрипты или интеграционные проверки),
оборачивайте команду в `xvfb-run -a`, например:

```bash
xvfb-run -a python3 script.py
```

## Локализация

Переводы хранятся в текстовых `.po`‑файлах и загружаются приложением напрямую.
Бинарные `.mo`‑каталоги и утилита `msgfmt` больше не требуются.

## Журнал выполнения
- 2025-09-10: Сформирован первоначальный план разработки (устарел).
- 2025-09-10: Создан каркас проекта.
- 2025-09-10: Добавлены утилиты.
- 2025-09-10: Реализована модель требований, схема и бизнес-валидация.
- 2025-09-10: Добавлены `.gitignore` и `pytest.ini`.
- 2025-09-11: Реализовано хранилище JSON.
- 2025-09-11: Реализованы поиск и фильтры.
- 2025-09-11: Создан каркас GUI.
- 2025-09-11: Реализован редактор требований.
- 2025-09-11: Добавлена локализация.
- 2025-09-12: Подключён словарь локализации.
- 2025-09-13: Добавлен скрипт сборки PyInstaller и инструкции.
- 2025-09-14: Удалён файл `Plan.md`; AGENTS.md переписан с актуальной архитектурой.
- 2025-09-15: Добавлены `LocalAgent`, LLM-клиент, MCP-сервер/клиент и модуль телеметрии.
- 2025-09-15: Введены контроллеры и система настроек приложения.
- 2025-09-16: Реализованы `doc_store`, команда `migrate to-docs` и покрывающие тесты.
- 2025-09-16: Добавлены CLI-команды `doc create` и `doc list` для работы с документами.
- 2025-09-16: Добавлены CLI-команды `item add` и `item move`, расширен `doc_store` (parse_rid, next_item_id).
- 2025-09-16: На время рефакторинга тесты отключены; `pytest.ini` исключает каталог `tests`.
- 2025-09-17: Добавлена CLI-команда `link` для связывания требований с проверкой иерархии.
- 2025-09-17: Реализована CLI-команда `trace` для экспорта light-матрицы трассировки.
- 2025-09-17: Каталог `tests` возвращён в `pytest.ini`, исправлена потеря переводчика `_` в команде `link`.
- 2025-09-17: Введена проверка меток при добавлении требований с учётом наследования.
- 2025-09-18: Проанализирован Doorstop, уточнены правила ссылок и формат трассировки, обновлена архитектура.
- 2025-09-18: Запрещена self-link при связывании требований, добавлены негативные тесты на ссылки вне иерархии.
- 2025-09-18: CLI и мигратор перешли с `tags` на `labels`, добавлен аргумент `--labels` (алиас `--tags`).
- 2025-09-19: Команда `trace` получила экспорт в CSV.
- 2025-09-19: Команда `trace` получила экспорт в HTML.
- 2025-09-19: `trace` пишет результат в файл и добавляет минимальный CSS для HTML.
- 2025-09-20: `trace` создаёт родительские каталоги для пути вывода.
- 2025-09-20: GUI получил дерево документов и контроллер для загрузки иерархических требований.
- 2025-09-20: GUI поддерживает создание, клонирование и удаление требований внутри выбранного документа с наследованием меток.
- 2025-09-20: Диалог выбора меток поддерживает свободный ввод, если его разрешает любой документ в цепочке.
