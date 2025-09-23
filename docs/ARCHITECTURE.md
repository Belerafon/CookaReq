# Архитектура CookaReq

Этот документ помогает быстро сориентироваться в кодовой базе и найти нужный слой реализации: графический интерфейс, сервисные компоненты, командную строку или MCP-интеграцию.

## Слои приложения

- **GUI (`app/ui`)** — виджеты wxPython, которые работают поверх контроллеров и моделей, обмениваются данными через `RequirementModel` и `DocumentsController`, а также предоставляют доступ к агенту (`LocalAgent`).
- **Ядро (`app/core`)** — доменные модели требований, файловое хранилище (`document_store`) и утилиты фильтрации/поиска. Этим же API пользуются CLI, MCP и агент.
- **Интеграции (`app/agent`, `app/llm`, `app/mcp`)** — обёртки вокруг LLM и MCP сервера/клиента, связывающие внешние сервисы с локальным хранилищем.
- **Командная строка (`app/cli`)** — оболочка над `document_store`, обеспечивающая сценарии без GUI.
- **Технические службы** — конфигурация, локализация, логирование, телеметрия и вспомогательные утилиты.

## Карта ключевых каталогов

### `app/`
- `main.py` — точка входа GUI: создаёт `wx.App`, инициализирует `ConfigManager`, `RequirementModel` и окно `MainFrame` с меню, контроллерами и агентом.【F:app/main.py†L5-L55】
- `config.py` — обёртка над `wx.Config`; класс `ConfigManager` хранит пользовательские настройки (колонки списка, последние каталоги, параметры LLM/MCP и т. д.).【F:app/config.py†L1-L121】
- `settings.py` — pydantic-модели `AppSettings`, `LLMSettings`, `MCPSettings`, `UISettings` и функции загрузки конфигов из JSON/TOML.【F:app/settings.py†L1-L89】【F:app/settings.py†L118-L149】
- `confirm.py` — регистрация и реализация подтверждающих диалогов (`set_confirm`, `confirm`, `wx_confirm`, `auto_confirm`). `wx_confirm` и `wx_confirm_requirement_update` маршалят выполнение в главный поток wx через `_call_in_wx_main_thread`, поэтому их можно вызывать из фоновых исполнителей агента без крашей в `wxThread::IsMain`.【F:app/confirm.py†L1-L31】【F:app/confirm.py†L214-L323】
- `i18n.py` — лёгкая обёртка над стандартным `gettext`: сначала пробует `gettext.translation`, а при отсутствии `.mo` компилирует `.po` через `polib` в памяти и выставляет `_`/`ngettext`/`pgettext` для GUI и CLI.【F:app/i18n.py†L1-L122】
- `log.py` и `telemetry.py` — настройка логирования (`configure_logging`, `JsonlHandler`) с использованием стандартных обработчиков `RotatingFileHandler` для потокового, текстового и JSONL-логов, встроенная ротация файлов при старте процесса и одновременная запись в поток, управление каталогом логов (`get_log_directory`, `open_log_directory`) и структурированная телеметрия (`log_event`, санитайзинг чувствительных данных).【F:app/log.py†L1-L173】【F:app/telemetry.py†L1-L49】
- `util/` — вспомогательные функции времени (`utc_now_iso`, `normalize_timestamp`) и другие мелкие утилиты.【F:app/util/time.py†L1-L27】
- `resources/` и `locale/` — иконки приложения и каталоги перевода, используемые `MainFrame` и `init_locale`.

### `app/core/`
- `model.py` — доменные перечисления (`RequirementType`, `Status`, …), дата-классы `Requirement`, `Attachment`, `Link`, генерация отпечатков (`requirement_fingerprint`) и сериализация требований.【F:app/core/model.py†L1-L184】【F:app/core/model.py†L246-L325】
- `document_store/` — работа с дисковым хранилищем: структуры `Document`, `DocumentLabels`, `RequirementPage`, загрузка/сохранение документов (`documents.py`), CRUD по элементам (`items.py`) и управление связями (`links.py`). Функции `update_requirement_field`, `set_requirement_labels`, `set_requirement_attachments`, `set_requirement_links` заменяют JSON Patch и при каждом сохранении автоматически увеличивают `revision`, перекладывая выбор допустимых полей и валидацию меток на хранилище.【F:app/core/document_store/__init__.py†L1-L101】【F:app/core/document_store/items.py†L1-L64】【F:app/core/document_store/items.py†L360-L523】【F:app/core/document_store/links.py†L1-L70】
- `search.py` — фильтрация по статусам, меткам, текстовым полям и признакам производности; используется и GUI, и CLI/MCP.【F:app/core/search.py†L1-L87】【F:app/core/search.py†L120-L184】
- `label_presets.py` — наборы предустановленных меток и генератор пастельных цветов для них.【F:app/core/label_presets.py†L1-L39】

### `app/ui/`
- `main_frame/` — пакет главного окна. `frame.py` собирает панели (`DocumentTree`, `ListPanel`, `EditorPanel`, `AgentChatPanel`), меню `Navigation`, настраивает `MCPController` и связывает `DocumentsController` для загрузки данных. Остальные модули сгруппированы по областям: `logging.py` содержит `WxLogHandler` и консоль логов; `sections.py` управляет сплиттерами, переключением секций и локализацией заголовков; `documents.py`, `editor.py`, `requirements.py`, `agent.py`, `settings.py`, `shutdown.py` держат обработчики для каталогов требований, редактирования, операций со списком, агентского чата, настроек и корректного завершения работы соответственно. Метод `_load_directory` в `documents.py` синхронизирует `MCPSettings.base_path` с выбранным каталогом и при необходимости перезапускает MCP-сервер, чтобы агент видел актуальные требования.【F:app/ui/main_frame/frame.py†L1-L213】【F:app/ui/main_frame/logging.py†L1-L150】【F:app/ui/main_frame/sections.py†L1-L217】【F:app/ui/main_frame/documents.py†L1-L253】【F:app/ui/main_frame/editor.py†L1-L174】【F:app/ui/main_frame/requirements.py†L1-L180】【F:app/ui/main_frame/agent.py†L1-L40】【F:app/ui/main_frame/settings.py†L1-L64】【F:app/ui/main_frame/shutdown.py†L1-L156】【F:app/config.py†L272-L311】【F:app/ui/main_frame/documents.py†L79-L160】
- `controllers/documents.py` — `DocumentsController` загружает и кэширует документы/требования, проверяет уникальность ID, сохраняет файлы и управляет удалением.【F:app/ui/controllers/documents.py†L1-L134】
- `requirement_model.py` — модель представления, применяющая фильтры и сортировки поверх списка `Requirement`, доступная всем панелям GUI.【F:app/ui/requirement_model.py†L1-L92】【F:app/ui/requirement_model.py†L114-L167】
- Панели: `list_panel.py` (табличный список с фильтрами и контекстным меню), `editor_panel.py` (форма редактирования требования с валидацией и вложениями), `document_tree.py` (иерархия документов), `navigation.py` (меню и хоткеи), `agent_chat_panel.py` (чат с `LocalAgent`); отдельное плавающее окно редактирования — `detached_editor.py` (переносит `EditorPanel` в отдельный `wx.Frame`, когда основной редактор скрыт).【F:app/ui/list_panel.py†L1-L92】【F:app/ui/editor_panel.py†L1-L81】【F:app/ui/document_tree.py†L1-L83】【F:app/ui/navigation.py†L1-L107】【F:app/ui/agent_chat_panel.py†L1-L214】【F:app/ui/detached_editor.py†L1-L86】
- `agent_chat_panel.py` управляет беседами `ChatConversation` (`app/ui/chat_entry.py`), каждая хранит пары `ChatEntry` с отметками времени и контекстом. История сохраняется рядом с каталогом требований (`.cookareq/agent_chats.json`), а интерфейс формирует список чатов и transcript с пузырями `TranscriptMessagePanel` и кнопками «Copy conversation»/«Copy technical log». Перед отправкой запросов панель собирает историю и дополнительный контекст, прикрепляет его к `_AgentRunHandle` и `ChatEntry`, чтобы `_compose_transcript_log_text()` выпускал инженерный журнал с системным промптом, описанием инструментов, снапшотом `context_messages`, фактическими сообщениями и результатами tool-calls. Последнему ответу доступна кнопка «Перегенерить», удаляющая текущий `ChatEntry` и повторно отправляющая запрос; кнопка «Стоп» использует `CancellationEvent` для немедленной отмены. Ответы отображаются Markdown через `MarkdownContent`, поэтому списки и код сохраняют форматирование.【F:app/ui/agent_chat_panel.py†L43-L214】【F:app/ui/agent_chat_panel.py†L315-L382】【F:app/ui/agent_chat_panel.py†L637-L706】【F:app/ui/agent_chat_panel.py†L1141-L1204】【F:app/ui/agent_chat_panel.py†L1335-L1706】【F:app/ui/chat_entry.py†L1-L194】【F:app/ui/widgets/chat_message.py†L1-L280】【F:app/ui/widgets/markdown_view.py†L1-L203】【F:app/ui/text.py†L1-L61】【F:app/util/cancellation.py†L1-L59】
- Для синхронизации истории с рабочими данными чат теперь передаёт успешные `tool_results` в `MainFrameAgentMixin`: `AgentChatPanel.set_tool_result_handler()` навешивает колбэк на завершение промпта, `_notify_tool_results()` фильтрует payloads и вызывает обработчик, а `MainFrameAgentMixin._on_agent_tool_results()` обновляет `RequirementModel`, пересчитывает `ListPanel.recalc_derived_map()`, переносит выделение и сбрасывает редактор после удаления. Благодаря этому заголовки и статусы требований меняются сразу после вызовов `update_requirement_field`, `set_requirement_*`, `link_requirements`, `delete_requirement` без ручной перезагрузки списка.【F:app/ui/agent_chat_panel.py†L201-L346】【F:app/ui/agent_chat_panel.py†L1510-L1520】【F:app/ui/agent_chat_panel.py†L2050-L2084】【F:app/ui/main_frame/frame.py†L224-L334】【F:app/ui/main_frame/agent.py†L114-L244】
- После переработки журнал теперь строится на базе `ChatEntry.diagnostic`: при завершении запроса `_build_entry_diagnostic()` сериализует снимок истории, контекста, обращений к MCP и ответа LLM, чтобы `_compose_transcript_log_text()` выводил секции строго в последовательности «Agent → LLM → MCP → User», заполняя отсутствующие этапы пометками `(none)`/`(не было)` и сохраняя весь технический payload для отладки.【F:app/ui/chat_entry.py†L10-L120】【F:app/ui/agent_chat_panel.py†L1608-L1899】【F:app/ui/agent_chat_panel.py†L1899-L2176】
- Разметка между панелями строится штатными `wx.SplitterWindow` прямо в `main_frame/frame.py` и `agent_chat_panel.py`, дополнительные утилиты оформления не используются.【F:app/ui/main_frame/frame.py†L101-L173】【F:app/ui/agent_chat_panel.py†L300-L406】
- Диалоги: `filter_dialog.py`, `document_dialog.py`, `labels_dialog.py`, `label_selection_dialog.py`, `settings_dialog.py`, `derivation_graph.py`, `trace_matrix.py` — отдельные окна для фильтров, настройки документов/меток, конфигурации LLM/MCP, визуализации связей и матриц трассировки.【F:app/ui/filter_dialog.py†L1-L73】【F:app/ui/document_dialog.py†L1-L70】【F:app/ui/labels_dialog.py†L1-L74】【F:app/ui/label_selection_dialog.py†L1-L61】【F:app/ui/settings_dialog.py†L1-L73】【F:app/ui/derivation_graph.py†L1-L55】【F:app/ui/trace_matrix.py†L1-L23】
- `resources/` — описывает конфигурацию редактора (`editor_fields.json`, `editor_config.py`), которую подхватывает `EditorPanel` для построения формы.

### `app/agent/`
- `local_agent.py` — высокоуровневый `LocalAgent`, объединяющий `LLMClient` и `MCPClient`, проверку подключения (`check_llm`, `check_tools`) и цикл агентного выполнения: модель возвращает `LLMResponse` с текстом и функциями, агент перед первым вызовом MCP-инструментов делает проверку готовности сервера (при последующих вызовах повторно не ходит на `/health`, пока не возникнет ошибка), добавляет ответы в историю и повторно опрашивает LLM до получения финального сообщения; поддерживает отмену через токены, прерывая ожидание LLM и не запуская новые tool-calls после нажатия «Стоп». Клиенты должны реализовывать явный асинхронный интерфейс (`check_llm_async`, `respond_async`, `check_tools_async`, `ensure_ready_async`, `call_tool_async`), а синхронные обёртки агента используют `_run_sync`, чтобы запускать корутины вне действующего цикла событий. 【F:app/agent/local_agent.py†L1-L214】【F:app/agent/local_agent.py†L331-L495】

### `app/llm/`
- `client.py` — HTTP-клиент поверх `openai.OpenAI`: проверка доступности (`check_llm`), генерация ответов (`respond`/`parse_command`) с возвратом `LLMResponse` — текста и набора валидированных `LLMToolCall`, поддержка потокового режима, разбор истории с сообщениями `assistant`/`tool`, логирование запросов и аккуратное завершение SSE-потока при отмене через `CancellationEvent`.【F:app/llm/client.py†L1-L160】【F:app/llm/client.py†L308-L529】

### `app/util/`
- `cancellation.py` — лёгкий `CancellationEvent` поверх `threading.Event` и исключение `OperationCancelledError`, позволяющие из GUI и сервисов закрывать потоковые запросы и снимать ожидания в фоновых потоках.【F:app/util/cancellation.py†L1-L59】
- `constants.py` — дефолтные и минимальные лимиты токенов контекста; `spec.py` содержит системный промпт и описание MCP-инструментов; `validation.py` проверяет аргументы вызовов инструментов.

### `app/mcp/`
- `server.py` — FastAPI-приложение с ручным маршрутом `/mcp`: middleware авторизации, журналы запросов, запуск через `uvicorn` и реестр инструментов, формируемый декоратором `register_tool`. Каждый HTTP-запрос получает `request_id`, длительность и адрес клиента в отдельном файле `server.jsonl`, а записи о вызовах инструментов привязываются к тому же идентификатору. При пустом `base_path` сервер использует подкаталог `mcp` внутри общего лог-директория приложения, поэтому достаточно системных пакетов `fastapi`, `uvicorn` и `httpx`; для экспериментов с официальным `FastMCP` дополнительно понадобятся `typer>=0.9` и `rich`, но в текущей конфигурации мы осознанно остаёмся на ручной реализации для полного контроля над журналированием.【F:app/mcp/server.py†L34-L146】【F:app/mcp/server.py†L240-L347】
- `controller.py` — `MCPController` управляет жизненным циклом сервера и health-check (`MCPCheckResult`).【F:app/mcp/controller.py†L1-L60】
- `client.py` — HTTP-клиент на базе `httpx` с подтверждениями перед опасными операциями, однократным health-check `/health`, который запоминает успешный результат и больше не опрашивает endpoint до первой ошибки (метод `ensure_ready`), и синхронным/асинхронным интерфейсом, использующим общее журналирование и переводящим сетевые ошибки MCP в структурированные ответы.【F:app/mcp/client.py†L1-L248】【F:app/mcp/client.py†L250-L430】
- `tools_read.py` и `tools_write.py` — адаптеры между MCP-инструментами и `document_store`, логирующие вызовы и преобразующие ответы; `tools_write.py` оборачивает микро-инструменты (`update_requirement_field`, `set_requirement_labels`, `set_requirement_attachments`, `set_requirement_links`), упрощая контракт для LLM и обрабатывая ошибки валидации без участия клиента.【F:app/mcp/tools_read.py†L1-L77】【F:app/mcp/tools_write.py†L1-L182】
- `utils.py` — генерация структур ошибок (`mcp_error`), нормализация исключений, общее логирование инструментов (`log_tool`).【F:app/mcp/utils.py†L1-L74】

### `app/cli/`
- `main.py` — точка входа CLI, собирает `argparse` и грузит `AppSettings` из файла; `__main__.py` проксирует запуск через `python -m app.cli`.
- `commands.py` — регистрация подкоманд (`doc`, `item`, `link`, `trace`, `check` и др.), разбор аргументов в `ItemPayload`, вызовы `document_store` и форматирование выводов (CSV/HTML для трассировки).【F:app/cli/commands.py†L1-L88】【F:app/cli/commands.py†L90-L166】

### `app/llm`, `app/mcp` и GUI
GUI использует LLM/MCP через чат-панель и настройки: `AgentChatPanel` создаёт `LocalAgent`, `SettingsDialog` умеет проверять соединение с помощью `LLMClient`/`MCPClient` и управлять `MCPController`.

### Прочие каталоги
- `requirements/` — пример хранилища требований: каталоги документов (`SYS`, `HLR`, …) с `document.json` и файлами `items/<ID>.json`.
- `tests/` — тестовый набор, сгруппированный по подкаталогам: `unit/` (модульные проверки ядра и утилит), `integration/` (связка LLM/MCP/CLI), `gui/` (wx-окна под xvfb), `smoke/` (быстрые проверки), `slow/` (долгие сценарии, отключены по умолчанию).
- `tools/` — одноразовые служебные скрипты для обслуживания хранилища требований и разработки.
- `build.py` — сборка дистрибутива через PyInstaller, добавляет иконку и ресурсы GUI.【F:build.py†L1-L39】
- Конфигурационные файлы (`pyproject.toml`, `pytest.ini`, `requirements*.txt`) задают зависимости, флаги тестов и окружение.

## Быстрый выбор слоя
- Нужен GUI — стартуйте с `app/main.py` и `app/ui/main_frame/`.
- Требуется правка бизнес-логики — смотрите `app/core/model.py` и `app/core/document_store/*`.
- Интересует автоматизация/LLM — изучайте `app/agent/local_agent.py`, `app/llm/client.py`, `app/mcp/*`.
- Требуется командная строка — `app/cli/commands.py` и `app/cli/main.py`.

Документ обновляйте по мере появления новых подсистем, чтобы сохранялась актуальная карта каталогов.
