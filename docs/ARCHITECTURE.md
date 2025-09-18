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
- `i18n.py` — минималистичная загрузка `.po`-каталогов и сбор недостающих переводов через `flush_missing`.【F:app/i18n.py†L1-L120】
- `log.py` и `telemetry.py` — настройка логирования (`configure_logging`, `JsonlHandler`) с ротацией файлов при старте процесса и одновременной записью в поток, текстовый и JSONL-логи, управление каталогом логов (`get_log_directory`, `open_log_directory`) и структурированная телеметрия (`log_event`, санитайзинг чувствительных данных).【F:app/log.py†L1-L131】【F:app/telemetry.py†L1-L49】
- `util/` — вспомогательные функции времени (`utc_now_iso`, `normalize_timestamp`) и другие мелкие утилиты.【F:app/util/time.py†L1-L27】
- `resources/` и `locale/` — иконки приложения и каталоги перевода, используемые `MainFrame` и `init_locale`.

### `app/core/`
- `model.py` — доменные перечисления (`RequirementType`, `Status`, …), дата-классы `Requirement`, `Attachment`, `Link`, генерация отпечатков (`requirement_fingerprint`) и сериализация требований.【F:app/core/model.py†L1-L184】【F:app/core/model.py†L246-L325】
- `document_store/` — работа с дисковым хранилищем: структуры `Document`, `DocumentLabels`, `RequirementPage`, загрузка/сохранение документов (`documents.py`), CRUD по элементам (`items.py`) и управление связями (`links.py`).【F:app/core/document_store/__init__.py†L1-L101】【F:app/core/document_store/documents.py†L31-L116】【F:app/core/document_store/items.py†L1-L64】【F:app/core/document_store/items.py†L60-L233】【F:app/core/document_store/links.py†L1-L70】
- `search.py` — фильтрация по статусам, меткам, текстовым полям и признакам производности; используется и GUI, и CLI/MCP.【F:app/core/search.py†L1-L87】【F:app/core/search.py†L120-L184】
- `label_presets.py` — наборы предустановленных меток и генератор пастельных цветов для них.【F:app/core/label_presets.py†L1-L39】

### `app/ui/`
- `main_frame.py` — главное окно: собирает панели (`DocumentTree`, `ListPanel`, `EditorPanel`, `AgentChatPanel`), меню `Navigation`, настраивает `MCPController` и связку с `DocumentsController` для загрузки данных; хранит в конфиге состояние сворачиваемой панели документов и ширину раскрытого дерева, отображает консоль логов с выбором уровня и усечением хвоста при росте истории. Метод `_load_directory` синхронизирует `MCPSettings.base_path` с выбранным каталогом и при необходимости перезапускает MCP-сервер, чтобы агент видел актуальные требования.【F:app/ui/main_frame.py†L1-L317】【F:app/config.py†L272-L311】【F:app/ui/main_frame.py†L1109-L1170】
- `controllers/documents.py` — `DocumentsController` загружает и кэширует документы/требования, проверяет уникальность ID, сохраняет файлы и управляет удалением.【F:app/ui/controllers/documents.py†L1-L134】
- `requirement_model.py` — модель представления, применяющая фильтры и сортировки поверх списка `Requirement`, доступная всем панелям GUI.【F:app/ui/requirement_model.py†L1-L92】【F:app/ui/requirement_model.py†L114-L167】
- Панели: `list_panel.py` (табличный список с фильтрами и контекстным меню), `editor_panel.py` (форма редактирования требования с валидацией и вложениями), `document_tree.py` (иерархия документов), `navigation.py` (меню и хоткеи), `agent_chat_panel.py` (чат с `LocalAgent`); отдельное плавающее окно редактирования — `detached_editor.py` (переносит `EditorPanel` в отдельный `wx.Frame`, когда основной редактор скрыт).【F:app/ui/list_panel.py†L1-L92】【F:app/ui/editor_panel.py†L1-L81】【F:app/ui/document_tree.py†L1-L83】【F:app/ui/navigation.py†L1-L107】【F:app/ui/agent_chat_panel.py†L1-L77】【F:app/ui/detached_editor.py†L1-L86】
- `agent_chat_panel.py` управляет беседами `ChatConversation` (`app/ui/chat_entry.py`), каждая из которых содержит список запросов/ответов `ChatEntry`; переписка рисуется карточками `TranscriptMessagePanel` (`app/ui/widgets/chat_message.py`) внутри `wx.lib.scrolledpanel.ScrolledPanel`: для каждого вызова инструмента создаётся `wx.CollapsiblePane` с деталями `tool_results` и кнопкой копирования JSON. Панель хранит `_AgentRunHandle` с `CancellationTokenSource`, чтобы по кнопке «Стоп» мгновенно снять блокировку ввода и закрыть поток LLM на уровне клиента.【F:app/ui/agent_chat_panel.py†L118-L263】【F:app/ui/agent_chat_panel.py†L360-L575】【F:app/ui/chat_entry.py†L1-L145】【F:app/ui/widgets/chat_message.py†L13-L209】【F:app/util/cancellation.py†L1-L117】
- Диалоги: `filter_dialog.py`, `document_dialog.py`, `labels_dialog.py`, `label_selection_dialog.py`, `settings_dialog.py`, `derivation_graph.py`, `trace_matrix.py` — отдельные окна для фильтров, настройки документов/меток, конфигурации LLM/MCP, визуализации связей и матриц трассировки.【F:app/ui/filter_dialog.py†L1-L73】【F:app/ui/document_dialog.py†L1-L70】【F:app/ui/labels_dialog.py†L1-L74】【F:app/ui/label_selection_dialog.py†L1-L61】【F:app/ui/settings_dialog.py†L1-L73】【F:app/ui/derivation_graph.py†L1-L55】【F:app/ui/trace_matrix.py†L1-L23】
- `resources/` — описывает конфигурацию редактора (`editor_fields.json`, `editor_config.py`), которую подхватывает `EditorPanel` для построения формы.

### `app/agent/`
- `local_agent.py` — высокоуровневый `LocalAgent`, объединяющий `LLMClient` и `MCPClient`, проверку подключения (`check_llm`, `check_tools`) и цикл агентного выполнения: модель возвращает `LLMResponse` с текстом и функциями, агент перед вызовом MCP-инструментов выполняет health-check сервера, добавляет ответы в историю и повторно опрашивает LLM до получения финального сообщения; поддерживает отмену через токены, прерывая ожидание LLM и не запуская новые tool-calls после нажатия «Стоп». Внутри основной цикл реализован единым асинхронным помощником, а синхронные вызовы используют адаптеры, которые оборачивают методы клиентов в корутины. 【F:app/agent/local_agent.py†L1-L214】【F:app/agent/local_agent.py†L331-L495】

### `app/llm/`
- `client.py` — HTTP-клиент поверх `openai.OpenAI`: проверка доступности (`check_llm`), генерация ответов (`respond`/`parse_command`) с возвратом `LLMResponse` — текста и набора валидированных `LLMToolCall`, поддержка потокового режима, разбор истории с сообщениями `assistant`/`tool`, логирование запросов и аккуратное завершение SSE-потока при отмене через `CancellationTokenSource`.【F:app/llm/client.py†L1-L160】【F:app/llm/client.py†L308-L529】

### `app/util/`
- `cancellation.py` — примитивы отмены (`CancellationTokenSource`, `CancellationToken`, `CancellationRegistration`) и исключение `OperationCancelledError`, позволяющие из GUI и сервисов закрывать потоковые запросы и снимать ожидания в фоновых потоках.【F:app/util/cancellation.py†L1-L117】
- `constants.py` — дефолтные и минимальные лимиты токенов; `spec.py` содержит системный промпт и описание MCP-инструментов; `validation.py` проверяет аргументы вызовов инструментов.

### `app/mcp/`
- `server.py` — FastAPI + FastMCP: регистрация инструментов (`list_requirements`, `create_requirement`, …), middleware авторизации, логирование запросов, запуск через `uvicorn` (используется `start_server`/`stop_server`).【F:app/mcp/server.py†L1-L94】【F:app/mcp/server.py†L96-L164】
- `controller.py` — `MCPController` управляет жизненным циклом сервера и health-check (`MCPCheckResult`).【F:app/mcp/controller.py†L1-L60】
- `client.py` — синхронный HTTP-клиент с подтверждениями перед опасными операциями, кешированным health-check `/health` (метод `ensure_ready`) и форматированием ошибок, в том числе для недоступного сервера.【F:app/mcp/client.py†L1-L206】【F:app/mcp/client.py†L208-L344】
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
- Нужен GUI — стартуйте с `app/main.py` и `app/ui/main_frame.py`.
- Требуется правка бизнес-логики — смотрите `app/core/model.py` и `app/core/document_store/*`.
- Интересует автоматизация/LLM — изучайте `app/agent/local_agent.py`, `app/llm/client.py`, `app/mcp/*`.
- Требуется командная строка — `app/cli/commands.py` и `app/cli/main.py`.

Документ обновляйте по мере появления новых подсистем, чтобы сохранялась актуальная карта каталогов.
