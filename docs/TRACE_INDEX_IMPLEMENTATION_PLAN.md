# План доработки CookaReq: трассировка кода, тестов и результатов

> Этот файл — рабочий план реализации `trace-index`. Его нужно обновлять по мере выполнения этапов.

## Прогресс

| Этап | Статус | Примечание |
| --- | --- | --- |
| Шаг 1. Core-модель индекса | Готово | Создана модель `app.core.trace_index`, добавлены unit-тесты сериализации, stable keys и top-level schema. |
| Шаг 1A. Golden fixtures | Готово | Synthetic project fixture покрывает parsers и полный builder golden `trace_index.generated.json` без volatile `generated_at_utc`. |
| Шаг 2. Parser для code markers | Готово | Добавлен parser C block comments `@covers`, включая multiple RID, notes, line numbers, stable keys, invalid marker diagnostics и fixture golden checks. |
| Шаг 3. Parser для test cases | Готово | Добавлен parser `print_case_header`, static/direct test id, explicit `@test ... @covers ...`, duplicate/conflict diagnostics и fixture golden checks. |
| Шаг 4. Parser для legacy test results | Готово | Добавлен parser `Build/test_results.txt`: run headers, test result blocks, covers, expected/criterion/log diagnostics, status normalization, mismatch/no-id issues и fixture golden checks. |
| Шаг 5. Config, schema и cache fingerprint | Готово | Добавлены `TraceIndexConfig`, default conventions/overrides, deterministic `config_hash`, content-based `input_fingerprint`, metadata и stale checks. |
| Шаг 6. Index builder | Готово | Добавлен builder `requirements + config + code markers + test cases + result files -> TraceIndex` с validation diagnostics и deterministic golden test. |
| Шаг 7. Cache индекса | Готово | Добавлены cache path, atomic write/read JSON, stale cache read wrapper, generated-cache exclusion from fingerprints и tests на сохранение старого cache при ошибке replace. |
| Шаг 8. CLI | Готово | Добавлены `trace-index refresh/check/export --format json`, CLI globs/project/module args, summary, cache write, JSON export и `--fail-on`. |
| Шаг 9. GUI: Refresh и Trace tab | Частично готово | Добавлено окно GUI `Trace Index` с вкладкой `Trace`: показывает состояние cache, summary, diagnostics, запускает refresh с atomic cache write в background worker, открывает связанный artifact по diagnostic row и дает GUI-настройки module/glob фильтров. Остались stale indication глубже по workflow и переходы из summary/evidence-строк. |
| Шаг 10. GUI: Artifact Browser | Частично готово | Добавлена вкладка Artifact Browser, синхронизированная с Trace tab: показывает code locations, test cases и test results из текущего индекса, фильтрует по типу/RID/тексту, поддерживает группировку по RID, умеет фокусировать Browser на RID выбранной строки и из Artifact Matrix, открывает artifact в read-only viewer. Остались более богатые переходы между связанными сущностями. |
| Шаг 11. Artifact trace matrices | Готово | Добавлен core-builder requirement x external artifact matrix для code/test_case/test_result columns и result status cells; CLI экспортирует JSON view `artifact-matrix`; GUI показывает вкладку Artifact Matrix. |
| Шаг 12. Export reports | Частично готово | Для `artifact-matrix` добавлены CLI/GUI JSON/CSV/HTML exports; CLI `--view report --format html` и Trace tab GUI export строят combined summary/diagnostics/matrix report. Остальные report views остаются позже. |
| Шаг 13. Интеграция с `V_pid_reg3` | Готово в fixture-пилоте | В `tests/fixtures/trace_index_project` добавлены требования `LLR3`-`LLR12` в общем LLR-документе, `Vsrc/V_pid_reg3.c`, `Vinclude/V_pid_reg3.h`, `tests/test_V_pid_reg3` и legacy `test_results.txt`; golden/CLI tests проверяют сборку индекса без diagnostics. |
| Шаг 14. CI режим | Готово | CLI `check` поддерживает `--fail-on high/warning`; добавлены tests на exit code для warning-only diagnostics. |
| Шаг 15. JUnit XML parser | Готово | Добавлен parser JUnit XML для `testsuite/testcase`, testcase/suite properties `covers`, `test_id`, `run_id`, `env`, `date_utc` и status tags failure/error/skipped; default result globs включают `tests/test_*/Build/*.xml`. |

## 1. Цель

Сделать в CookaReq read-only ALM-слой поверх требований, кода, тестов и результатов тестов. Источник истины остается в исходных артефактах:

1. требования хранятся в `Req/` как CookaReq items;
2. связь кода с требованиями задается маркерами в `.c/.h`;
3. связь тестов с требованиями задается явными маркерами или распознаваемой структурой тестового исходника;
4. результаты тестов берутся из файлов результатов;
5. CookaReq строит пересоздаваемый индекс, показывает матрицы, полноту и переходы к файлам.

Индекс не является источником истины. Его можно удалить и построить заново.

## 2. Разведение с существующим `trace`

Существующие `app.core.trace_matrix`, CLI-команда `trace` и GUI trace matrix остаются ответственными за связи CookaReq item-to-item, например `LLR -> HLR`.

Новый `trace-index` отвечает только за внешние evidence-артефакты:

```text
кодовые маркеры -> LLR
тестовые маркеры -> LLR
результаты тестов -> test_id / LLR
```

CLI-команды должны быть явно разведены:

```text
trace       - матрицы CookaReq links между требованиями
trace-index - индекс и матрицы внешних артефактов
```

## 3. Термины

- Requirement — CookaReq item, например `LLR3`.
- Code location — найденный в исходнике участок с `@covers LLR3`.
- Test case — найденный в тестовом исходнике тест. В MVP извлекается из текущего `print_case_header(ID, "LLR3", ...)`; явный `@test ... @covers ...` — будущий рекомендуемый формат.
- Test run — один прогон тестов с `run_id`, окружением и файлом результата.
- Test result — результат конкретного test case в конкретном test run.
- Trace index — пересоздаваемый read-only граф связей между этими сущностями.

## 4. Форматы маркеров MVP

### Requirement ID

Поддерживается RID формата:

```text
\b[A-Z]+-?0*[0-9]+\b
```

RID чувствителен к регистру. `llr3` считается невалидным маркером.
Для одного требования допускаются эквивалентные написания с дефисом и ведущими
нулями: `LLR3`, `LLR003`, `LLR-3`, `LLR-003`. В индекс сохраняется RID из
CookaReq item, например `LLR3`.

### Code markers

MVP поддерживает только C block comments `/* ... */`:

```c
/* @covers LLR3 */
/* @covers LLR3, LLR8: ограничение выхода */
```

Грамматика:

```text
covers_marker := "@covers" whitespace rid_list optional_note
rid_list      := rid (optional_space "," optional_space rid)*
optional_note := optional_space ":" any_text
```

Пояснение после `:` относится ко всему маркеру, а не к отдельному RID. Несколько `@covers` в одном комментарии допускаются и создают отдельные связи. Маркеры в строковых литералах не парсятся.

### Test markers

Будущий явный формат:

```c
/* @test ТЕСТ-UT-V_PID_REG3-0003 @covers LLR3 */
```

MVP-формат текущего проекта:

```c
static const char ID[] = "ТЕСТ-UT-V_PID_REG3-0003";
print_case_header(ID, "LLR3", ...);
```

Если оба формата присутствуют, они должны описывать один и тот же `test_id` и один и тот же набор RID. Расхождение дает `TraceIssue`.

### Legacy test result format

```text
ИД_ПРОГОНА: ПРОГОН-20260526-000000Z-HOST-001; ОКРУЖЕНИЕ: HOST; ДАТА_UTC: 2026-05-26T00:00:00Z
ИДЕНТ_ТЕСТА: ТЕСТ-UT-V_PID_REG3-0003
ПОКРЫВАЕТ_ТНУ: LLR3
РЕЗУЛЬТАТ: ТЕСТ-UT-V_PID_REG3-0003 = ПРОШЕЛ
```

Legacy parser читает UTF-8/UTF-8 BOM, CRLF и LF. Блок test result начинается с `ИДЕНТ_ТЕСТА:` и заканчивается строкой `РЕЗУЛЬТАТ:` или началом следующего блока. Summary в конце файла не является отдельным результатом. Несовпадение test id в `РЕЗУЛЬТАТ:` и текущем блоке дает `RESULT_TEST_ID_MISMATCH`.

## 5. Data ownership и conflicts

- `LLR` определяется как CookaReq item из документа `LLR`.
- Для проверок используются `rid`, `title`, `verification` / `verification_methods`, `context_docs`.
- Основной источник связи `test case -> RID` — test source marker или `print_case_header`.
- Result file `ПОКРЫВАЕТ_ТНУ` — evidence того, что конкретный прогон заявил покрытие RID.
- Если result covers отличается от test source covers, индекс сохраняет оба значения; матрица `LLR x Test Cases` строится по test source covers, а `LLR x Test Runs` помечает конфликт issue.

Коды конфликтов: `COVERAGE_MISMATCH`, `RESULT_WITHOUT_TEST_CASE`, `RESULT_WITHOUT_COVERS`.

## 6. Нормализация статусов и issues

`raw_status` хранит исходный текст, `normalized_status` — `passed`, `failed`, `error`, `skipped`, `unknown`, а `aggregate_status` — `passed`, `failed`, `error`, `skipped`, `unknown`, `not_run`, `mixed`, `missing`.

Стабильные issue codes:

```text
UNKNOWN_RID
INVALID_MARKER
DUPLICATE_TEST_ID
CONFLICTING_TEST_MARKERS
COVERAGE_MISMATCH
RESULT_WITHOUT_TEST_ID
RESULT_TEST_ID_MISMATCH
RESULT_WITHOUT_TEST_CASE
RESULT_WITHOUT_COVERS
MISSING_TEST_FOR_LLR
TEST_WITHOUT_RESULT
INPUT_FILE_UNREADABLE
STALE_CACHE
MODULE_NOT_FOUND
```

Severity: `high`, `warning`, `info`. CLI должен поддерживать `--fail-on high` и `--fail-on warning`.

## 7. Стабильные ключи

Line number не должен быть частью stable key.

- Requirement: RID из CookaReq item.
- Code location: `normalized_path + covers_rid + marker_ordinal_in_file`.
- Test case: `test_id`.
- Test run: `run_id + result_file`.
- Test result: `run_id + test_id + result_file + block_ordinal`.

## 8. Config и cache schema

Indexer получает `TraceIndexConfig`:

```text
project_root
req_root
source_globs: Vsrc/**/*.c, Vinclude/**/*.h
test_globs: tests/test_*/src/**/*.c
result_globs: tests/test_*/Build/test_results.txt, tests/test_*/Build/*.xml
exclude_globs: Build/coverage/**, .git/**
module_filter: optional
```

Cache хранится как generated JSON:

```text
Req/.cookareq/trace_index.generated.json
```

Обязательные top-level поля:

```json
{
  "schema_version": 1,
  "generator": "CookaReq trace-index",
  "generator_version": "...",
  "project_root": "...",
  "req_root": "...",
  "config_hash": "...",
  "input_fingerprint": "...",
  "generated_at_utc": "2026-06-25T00:00:00Z",
  "requirements": [],
  "code_locations": [],
  "test_cases": [],
  "test_runs": [],
  "test_results": [],
  "issues": []
}
```

Cache write должен быть atomic: запись во временный файл рядом с cache, затем rename/replace.

## 9. Предлагаемая структура кода

```text
app/core/trace_index/
  model.py
  config.py
  parsers.py
  parse_code.py
  parse_tests.py
  parse_results.py
  builder.py
  cache.py
  matrix.py
  export.py

app/ui/trace_index/
  trace_tab.py
  artifact_browser.py
  matrix_dialog.py
```

MVP не должен смешивать внешние evidence-связи с `app.core.trace_matrix` и CookaReq link `suspect` semantics.

## 10. Реализация по шагам

### Шаг 1. Core-модель индекса

Dataclasses: `TraceIndex`, `TraceRequirementRef`, `CodeLocation`, `TestCaseRef`, `TestRunRef`, `TestResultRef`, `TraceIssue`.

Минимальные поля: `schema_version`, `generator_version`, `config_hash`, `input_fingerprint`, `rid`, `path`, `line_start`, `line_end`, `symbol`, `marker_text`, `stable_key`, `test_id`, `run_id`, `env`, `date_utc`, `raw_status`, `normalized_status`, `result_file`, `issues`.

Тесты:

1. сериализация/десериализация модели;
2. стабильные ключи сущностей;
3. JSON schema top-level поля и сортировка.

Критерии приемки:

1. индекс можно создать в памяти без GUI;
2. индекс можно сохранить в JSON и прочитать обратно без потери данных;
3. stable key одинаков для одного и того же маркера при повторном скане.

### Шаг 1A. Golden fixtures

Создать `tests/fixtures/trace_index_project/` с минимальным `Req`, source, test source, result file и expected JSON. Добавить golden tests, включая broken marker.

### Шаг 2. Parser для code markers

Реализовать `.c/.h` scanner для `@covers` в C block comments, multiple RID, optional note, invalid marker diagnostics, best-effort `symbol`.

### Шаг 3. Parser для test cases

Реализовать scanner для `static const char ID[]`, `print_case_header(ID, "LLR3", ...)`, direct string и `/* @test ... @covers ... */`. Duplicate/conflicting test ids дают issues.

### Шаг 4. Parser для legacy test results

Реализовать parser текущего `Build/test_results.txt`: run headers, result blocks, covers, expected, criterion, logs, summary ignore, status normalization.

### Шаг 5. Config, schema и cache fingerprint

Реализовать `TraceIndexConfig`, default conventions, override globs, `config_hash`, `input_fingerprint`, stale checks.

### Шаг 6. Index builder

Собрать `requirements + config + code markers + test cases + result files -> TraceIndex` с diagnostics за один проход и deterministic JSON.

### Шаг 7. Cache индекса

Сохранять и читать `Req/.cookareq/trace_index.generated.json`, поддержать stale detection и atomic write.

### Шаг 8. CLI

Добавить:

```bash
python -m app.cli trace-index refresh <ReqRoot> --module V_pid_reg3
python -m app.cli trace-index check <ReqRoot> --module V_pid_reg3
python -m app.cli trace-index export <ReqRoot> --module V_pid_reg3 --format json
```

CLI должен принимать `--project-root`, `--config`, `--source-glob`, `--test-glob`, `--result-glob` и печатать summary.

### Шаги 9-12. GUI, matrices, reports

Post-MVP: refresh button, Requirement Trace tab, Artifact Browser, artifact trace matrices, HTML/CSV reports. JSON export входит в MVP-0.

### Шаг 13. Интеграция с `V_pid_reg3`

Пилотный модуль: code markers в `Vsrc/V_pid_reg3.c`, использование текущих `print_case_header`, чтение `test_results.txt`, CLI refresh/check/export.

### Шаг 14. CI режим

`trace-index check ... --fail-on high|warning`, понятные exit codes и summary для job log.

### Шаг 15. JUnit XML parser

Post-MVP parser с project-specific `<properties>` для `covers`, `run_id`, `env`.

## 11. MVP order

### MVP-0: CLI-only индекс

1. Шаг 1 — core-модель.
2. Шаг 1A — golden fixtures.
3. Шаг 2 — code parser.
4. Шаг 3 — test parser.
5. Шаг 4 — legacy result parser.
6. Шаг 5 — config/schema/cache fingerprint.
7. Шаг 6 — index builder.
8. Шаг 7 — cache.
9. Шаг 8 — CLI refresh/check/json export.
10. Шаг 13 — пилот `V_pid_reg3` без GUI.

Критерий MVP-0: `trace-index refresh/check` строит deterministic индекс на golden fixtures и на `V_pid_reg3`, сообщает diagnostics с issue codes и пишет валидный JSON cache/export.

### MVP-1: GUI Trace tab

Шаг 9 частично реализован: базовое окно с refresh/background worker, cache state, summary, diagnostics, открытием artifact из diagnostic row и настройками module/glob фильтров готово. Осталась расширенная stale indication в workflow выбранного требования.

Шаг 10 частично реализован: вкладка Artifact Browser показывает code locations, test cases и test results из текущего TraceIndex, фильтрует по типу/RID/тексту, поддерживает группировку по RID, умеет фокусировать Browser на RID выбранной строки и выбранной строки Artifact Matrix, открывает artifact в read-only viewer. Остались более богатые переходы между связанными сущностями.

Шаг 11 реализован: `app/core/trace_index/matrix.py` строит deterministic requirement x external artifact matrix из `TraceIndex` без смешивания с CookaReq item-to-item `trace_matrix`; CLI `trace-index export --view artifact-matrix` отдает эту матрицу в JSON; GUI-вкладка Artifact Matrix показывает requirement rows и artifact columns. Более богатая навигация по связанным evidence остается развитием Artifact Browser/Matrix UX.

### MVP-2: browser, matrices, reports

Шаг 12 частично реализован: `trace-index export --view artifact-matrix` поддерживает JSON, CSV и HTML, GUI-вкладка Artifact Matrix экспортирует текущую матрицу в JSON/CSV/HTML, а CLI `trace-index export --view report --format html` и кнопка Trace tab GUI export строят combined summary/diagnostics/matrix report. Остальные специализированные отчеты остаются следующими подшагами.

Шаг 15 реализован: result parser распознает JUnit XML-файлы, а default result globs включают `tests/test_*/Build/*.xml` вместе с legacy `test_results.txt`. Пилотные golden fixtures оставлены без XML-файлов, поэтому проверяют обратную совместимость legacy-пути при расширенном default config.
