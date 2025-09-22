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
- `confirm.py` — регистрация и реализация подтверждающих диалогов (`set_confirm`, `confirm`, `wx_confirm`, `auto_confirm`).【F:app/confirm.py†L1-L31】
- `i18n.py` — лёгкая обёртка над стандартным `gettext`: сначала пробует `gettext.translation`, а при отсутствии `.mo` компилирует `.po` через `polib` в памяти и выставляет `_`/`ngettext`/`pgettext` для GUI и CLI.【F:app/i18n.py†L1-L122】
- `log.py` и `telemetry.py` — настройка логирования (`configure_logging`, `JsonlHandler`) с использованием стандартных обработчиков `RotatingFileHandler` для потокового, текстового и JSONL-логов, встроенная ротация файлов при старте процесса и одновременная запись в поток, управление каталогом логов (`get_log_directory`, `open_log_directory`) и структурированная телеметрия (`log_event`, санитайзинг чувствительных данных).【F:app/log.py†L1-L173】【F:app/telemetry.py†L1-L49】
- `util/` — вспомогательные функции времени (`utc_now_iso`, `normalize_timestamp`) и другие мелкие утилиты.【F:app/util/time.py†L1-L27】
- `resources/` и `locale/` — иконки приложения и каталоги перевода, используемые `MainFrame` и `init_locale`.

### `app/core/`
- `model.py` — доменные перечисления (`RequirementType`, `Status`, …), дата-классы `Requirement`, `Attachment`, `Link`, генерация отпечатков (`requirement_fingerprint`) и сериализация требований.【F:app/core/model.py†L1-L184】【F:app/core/model.py†L246-L325】
- `document_store/` — работа с дисковым хранилищем: структуры `Document`, `DocumentLabels`, `RequirementPage`, загрузка/сохранение документов (`documents.py`), CRUD по элементам (`items.py`) и управление связями (`links.py`).【F:app/core/document_store/__init__.py†L1-L101】【F:app/core/document_store/documents.py†L31-L116】【F:app/core/document_store/items.py†L1-L64】【F:app/core/document_store/items.py†L60-L233】【F:app/core/document_store/links.py†L1-L70】
- `search.py` — фильтрация по статусам, меткам, текстовым полям и признакам производности; используется и GUI, и CLI/MCP.【F:app/core/search.py†L1-L87】【F:app/core/search.py†L120-L184】
- `label_presets.py` — наборы предустановленных меток и генератор пастельных цветов для них.【F:app/core/label_presets.py†L1-L39】

### `app/ui/`
- `main_frame/` — пакет главного окна. `frame.py` собирает панели (`DocumentTree`, `ListPanel`, `EditorPanel`, `AgentChatPanel`), меню `Navigation`, настраивает `MCPController` и связывает `DocumentsController` для загрузки данных. Остальные модули сгруппированы по областям: `logging.py` содержит `WxLogHandler` и консоль логов; `sections.py` управляет сплиттерами, переключением секций и локализацией заголовков; `documents.py`, `editor.py`, `requirements.py`, `agent.py`, `settings.py`, `shutdown.py` держат обработчики для каталогов требований, редактирования, операций со списком, агентского чата, настроек и корректного завершения работы соответственно. Метод `_load_directory` в `documents.py` синхронизирует `MCPSettings.base_path` с выбранным каталогом и при необходимости перезапускает MCP-сервер, чтобы агент видел актуальные требования.【F:app/ui/main_frame/frame.py†L1-L213】【F:app/ui/main_frame/logging.py†L1-L150】【F:app/ui/main_frame/sections.py†L1-L217】【F:app/ui/main_frame/documents.py†L1-L253】【F:app/ui/main_frame/editor.py†L1-L174】【F:app/ui/main_frame/requirements.py†L1-L180】【F:app/ui/main_frame/agent.py†L1-L40】【F:app/ui/main_frame/settings.py†L1-L64】【F:app/ui/main_frame/shutdown.py†L1-L156】【F:app/config.py†L272-L311】【F:app/ui/main_frame/documents.py†L79-L160】
- `controllers/documents.py` — `DocumentsController` загружает и кэширует документы/требования, проверяет уникальность ID, сохраняет файлы и управляет удалением.【F:app/ui/controllers/documents.py†L1-L134】
- `requirement_model.py` — модель представления, применяющая фильтры и сортировки поверх списка `Requirement`, доступная всем панелям GUI.【F:app/ui/requirement_model.py†L1-L92】【F:app/ui/requirement_model.py†L114-L167】
- Панели: `list_panel.py` (табличный список с фильтрами и контекстным меню), `editor_panel.py` (форма редактирования требования с валидацией и вложениями), `document_tree.py` (иерархия документов), `navigation.py` (меню и хоткеи), `agent_chat_panel.py` (чат с `LocalAgent`); отдельное плавающее окно редактирования — `detached_editor.py` (переносит `EditorPanel` в отдельный `wx.Frame`, когда основной редактор скрыт).【F:app/ui/list_panel.py†L1-L92】【F:app/ui/editor_panel.py†L1-L81】【F:app/ui/document_tree.py†L1-L83】【F:app/ui/navigation.py†L1-L107】【F:app/ui/agent_chat_panel.py†L1-L77】【F:app/ui/detached_editor.py†L1-L86】
<<<<< slztez-codex/add-regenerate-button-to-chat-response
- `agent_chat_panel.py` управляет беседами `ChatConversation` (`app/ui/chat_entry.py`), каждая из которых хранит пары `ChatEntry` с отметками времени вопроса/ответа. Переписка отображается пузырями `TranscriptMessagePanel` (`app/ui/widgets/chat_message.py`) внутри `wx.lib.scrolledpanel.ScrolledPanel`: пользовательские сообщения выравниваются вправо, агентские — влево, в шапке показывается локальное время. Сама панель больше не раскрывает `tool_results` — `TranscriptMessagePanel` рендерит только текстовые пузыри, а технические детали (временные метки, `raw_result`, аргументы и ответы инструментов) копируются через новую кнопку «Copy technical log», которая вызывает `get_transcript_log_text()` и форматирует полное инженерное досье чата. Ответы агента по-прежнему рендерятся как Markdown в `MarkdownContent` (`wx.html.HtmlWindow`), поэтому таблицы, списки и кодовые блоки сохраняют форматирование и доступны для копирования. Перед отправкой запросов панель собирает историю и дополнительный контекст (через `context_provider`), строки пропускает через `normalize_for_display`, чтобы сгладить экзотические символы, а `_AgentRunHandle` с `CancellationEvent` позволяет по кнопке «Стоп» мгновенно разморозить ввод и закрыть поток LLM. История чатов сохраняется в `agent_chats.json` подкаталога `.cookareq` внутри каталога требований, чтобы переписка перемещалась вместе с документами. Для последнего ответа добавлена кнопка «Перегенерить»: она удаляет текущий результат из истории и автоматически отправляет тот же запрос ещё раз, что обеспечивает быстрое получение альтернативы без ручного копирования текста.【F:app/ui/agent_chat_panel.py†L118-L287】【F:app/ui/agent_chat_panel.py†L360-L575】【F:app/ui/agent_chat_panel.py†L600-L671】【F:app/ui/agent_chat_panel.py†L1001-L1033】【F:app/ui/chat_entry.py†L1-L168】【F:app/ui/widgets/chat_message.py†L1-L280】【F:app/ui/widgets/markdown_view.py†L1-L203】【F:app/ui/text.py†L1-L61】【F:app/util/cancellation.py†L1-L59】
======
- `agent_chat_panel.py` управляет беседами `ChatConversation` (`app/ui/chat_entry.py`), каждая из которых хранит пары `ChatEntry` с отметками времени вопроса/ответа. Переписка отображается пузырями `TranscriptMessagePanel` (`app/ui/widgets/chat_message.py`) внутри `wx.lib.scrolledpanel.ScrolledPanel`: пользовательские сообщения выравниваются вправо, агентские — влево, в шапке показывается локальное время. Сама панель больше не раскрывает `tool_results` — `TranscriptMessagePanel` рендерит только текстовые пузыри, а технические детали (временные метки, `raw_result`, аргументы и ответы инструментов) копируются через кнопку «Copy technical log». Каждый `ChatEntry` дополнительно сохраняет снимок контекстных сообщений (`context_messages`), чтобы журнал мог воспроизвести фактический запрос, включая системный промпт LLM и JSON-схемы MCP-инструментов; `get_transcript_log_text()` форматирует эти данные отдельными блоками «LLM system prompt», «LLM tool specification», «Context messages» и «LLM request messages». Ответы агента по-прежнему рендерятся как Markdown в `MarkdownContent` (`wx.html.HtmlWindow`), поэтому таблицы, списки и кодовые блоки сохраняют форматирование и доступны для копирования. Перед отправкой запросов панель собирает историю и дополнительный контекст (через `context_provider`), строки пропускает через `normalize_for_display`, чтобы сгладить экзотические символы, а `_AgentRunHandle` с `CancellationEvent` позволяет по кнопке «Стоп» мгновенно разморозить ввод и закрыть поток LLM. История чатов сохраняется в `agent_chats.json` подкаталога `.cookareq` внутри каталога требований, чтобы переписка перемещалась вместе с документами.【F:app/ui/agent_chat_panel.py†L118-L287】【F:app/ui/agent_chat_panel.py†L360-L575】【F:app/ui/agent_chat_panel.py†L600-L671】【F:app/ui/agent_chat_panel.py†L1001-L1185】【F:app/ui/chat_entry.py†L1-L194】【F:app/ui/widgets/chat_message.py†L1-L280】【F:app/ui/widgets/markdown_view.py†L1-L203】【F:app/ui/text.py†L1-L61】【F:app/util/cancellation.py†L1-L59】
>>>>> main
- Разметка между панелями строится штатными `wx.SplitterWindow` прямо в `main_frame/frame.py` и `agent_chat_panel.py`, дополнительные утилиты оформления не используются.【F:app/ui/main_frame/frame.py†L101-L173】【F:app/ui/agent_chat_panel.py†L1-L77】
- Диалоги: `filter_dialog.py`, `document_dialog.py`, `labels_dialog.py`, `label_selection_dialog.py`, `settings_dialog.py`, `derivation_graph.py`, `trace_matrix.py` — отдельные окна для фильтров, настройки документов/меток, конфигурации LLM/MCP, визуализации связей и матриц трассировки.【F:app/ui/filter_dialog.py†L1-L73】【F:app/ui/document_dialog.py†L1-L70】【F:app/ui/labels_dialog.py†L1-L74】【F:app/ui/label_selection_dialog.py†L1-L61】【F:app/ui/settings_dialog.py†L1-L73】【F:app/ui/derivation_graph.py†L1-L55】【F:app/ui/trace_matrix.py†L1-L23】
- `resources/` — описывает конфигурацию редактора (`editor_fields.json`, `editor_config.py`), которую подхватывает `EditorPanel` для построения формы.

### `app/agent/`
- `local_agent.py` — высокоуровневый `LocalAgent`, объединяющий `LLMClient` и `MCPClient`, проверку подключения (`check_llm`, `check_tools`) и цикл агентного выполнения: модель возвращает `LLMResponse` с текстом и функциями, агент перед вызовом MCP-инструментов выполняет health-check сервера, добавляет ответы в историю и повторно опрашивает LLM до получения финального сообщения; поддерживает отмену через токены, прерывая ожидание LLM и не запуская новые tool-calls после нажатия «Стоп». Клиенты должны реализовывать явный асинхронный интерфейс (`check_llm_async`, `respond_async`, `check_tools_async`, `ensure_ready_async`, `call_tool_async`), а синхронные обёртки агента используют `_run_sync`, чтобы запускать корутины вне действующего цикла событий. 【F:app/agent/local_agent.py†L1-L214】【F:app/agent/local_agent.py†L331-L495】

### `app/llm/`
- `client.py` — HTTP-клиент поверх `openai.OpenAI`: проверка доступности (`check_llm`), генерация ответов (`respond`/`parse_command`) с возвратом `LLMResponse` — текста и набора валидированных `LLMToolCall`, поддержка потокового режима, разбор истории с сообщениями `assistant`/`tool`, логирование запросов и аккуратное завершение SSE-потока при отмене через `CancellationEvent`.【F:app/llm/client.py†L1-L160】【F:app/llm/client.py†L308-L529】

### `app/util/`
- `cancellation.py` — лёгкий `CancellationEvent` поверх `threading.Event` и исключение `OperationCancelledError`, позволяющие из GUI и сервисов закрывать потоковые запросы и снимать ожидания в фоновых потоках.【F:app/util/cancellation.py†L1-L59】
- `constants.py` — дефолтные и минимальные лимиты токенов контекста; `spec.py` содержит системный промпт и описание MCP-инструментов; `validation.py` проверяет аргументы вызовов инструментов.

### `app/mcp/`
- `server.py` — FastAPI-приложение с ручным маршрутом `/mcp`: middleware авторизации, журналы запросов, запуск через `uvicorn` и реестр инструментов, формируемый декоратором `register_tool`. Каждый HTTP-запрос получает `request_id`, длительность и адрес клиента в отдельном файле `server.jsonl`, а записи о вызовах инструментов привязываются к тому же идентификатору. При пустом `base_path` сервер использует подкаталог `mcp` внутри общего лог-директория приложения, поэтому достаточно системных пакетов `fastapi`, `uvicorn` и `httpx`; для экспериментов с официальным `FastMCP` дополнительно понадобятся `typer>=0.9` и `rich`, но в текущей конфигурации мы осознанно остаёмся на ручной реализации для полного контроля над журналированием.【F:app/mcp/server.py†L34-L146】【F:app/mcp/server.py†L240-L347】
- `controller.py` — `MCPController` управляет жизненным циклом сервера и health-check (`MCPCheckResult`).【F:app/mcp/controller.py†L1-L60】
- `client.py` — HTTP-клиент на базе `httpx` с подтверждениями перед опасными операциями, кешированным health-check `/health` (метод `ensure_ready`) и синхронным/асинхронным интерфейсом, использующим общее журналирование и переводящим сетевые ошибки MCP в структурированные ответы.【F:app/mcp/client.py†L1-L248】【F:app/mcp/client.py†L250-L430】
- `tools_read.py` и `tools_write.py` — адаптеры между MCP-инструментами и `document_store`, логирующие вызовы и преобразующие ответы.【F:app/mcp/tools_read.py†L1-L77】【F:app/mcp/tools_write.py†L1-L86】
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
