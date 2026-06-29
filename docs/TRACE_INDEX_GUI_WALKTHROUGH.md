# Trace Index GUI: пошаговая проверка функционала

Этот документ описывает воспроизводимый ручной сценарий проверки GUI для Trace Index: refresh/cache, diagnostics, Artifact Browser, Artifact Matrix, двунаправленную навигацию, JUnit XML ingest и экспорты.

## 1. Подготовка demo-проекта

Все шаги ниже можно выполнять на копии fixture-проекта, чтобы не менять исходные тестовые данные репозитория.

```bash
rm -rf /tmp/cookareq-trace-index-demo
cp -a tests/fixtures/trace_index_project /tmp/cookareq-trace-index-demo
```

В дальнейших шагах:

- project root: `/tmp/cookareq-trace-index-demo`
- requirements root, который нужно открыть в CookaReq: `/tmp/cookareq-trace-index-demo/Req`
- ожидаемый generated cache: `/tmp/cookareq-trace-index-demo/Req/.cookareq/trace_index.generated.json`

## 2. Запуск GUI

Обычный запуск на машине с графическим окружением:

```bash
source .venv/bin/activate
python -m app.main
```

Запуск в контейнере/без физического display через виртуальный X display:

```bash
source .venv/bin/activate
python tools/run_wx.py --size 1600x1000 app/main.py
```

После старта приложения:

1. Откройте меню **File → Open Folder**.
2. Выберите `/tmp/cookareq-trace-index-demo/Req`.
3. Убедитесь, что требования `LLR` загрузились в основном окне.
4. Откройте меню **View → Show Trace Index**.
5. Должно открыться отдельное окно **Trace Index** с вкладками **Trace**, **Artifact Browser**, **Artifact Matrix**.

## 3. Trace tab: happy path refresh и cache

Цель: проверить генерацию индекса без diagnostics и создание generated cache.

1. Перейдите на вкладку **Trace**.
2. В поле **Exclude globs** укажите:

   ```text
   Vsrc/broken_*
   ```

   Это исключит специальный файл fixture с намеренно ошибочным marker.
3. Нажмите **Refresh Trace Index**.
4. Ожидаемый результат:
   - status: `Trace index refreshed successfully.`;
   - summary содержит `Requirements: 12`;
   - summary содержит `Test results: 5`;
   - diagnostics list пустой;
   - создан файл `/tmp/cookareq-trace-index-demo/Req/.cookareq/trace_index.generated.json`.

Проверка после перезапуска окна:

1. Закройте окно **Trace Index**.
2. Снова откройте **View → Show Trace Index**.
3. Если настройки scan совпадают с cache, status должен показывать, что cache актуален.

## 4. Trace tab: diagnostics и переход к файлу

Цель: увидеть diagnostics и открыть связанный artifact.

1. На вкладке **Trace** очистите поле **Exclude globs** или уберите из него `Vsrc/broken_*`.
2. Нажмите **Refresh Trace Index**.
3. Ожидаемый результат:
   - status: `Trace index refreshed with diagnostics.`;
   - в diagnostics list появляется строка по `Vsrc/broken_marker.c`;
   - у строки есть severity/code/location/message.
4. Выберите diagnostic row.
5. Нажмите **Open Location** или дважды кликните строку.
6. Ожидаемый результат: откроется read-only окно artifact viewer с файлом `Vsrc/broken_marker.c`; при наличии line number viewer должен показать позицию около проблемного marker.

## 5. Trace tab: stale cache indication

Цель: проверить, что GUI показывает устаревший cache после изменения входных файлов.

1. Сначала выполните refresh из раздела happy path, чтобы cache был создан.
2. Закройте окно **Trace Index**.
3. Из терминала измените любой входной artifact, например:

   ```bash
   printf '\n/* @covers LLR10: manual stale check */\n' >> /tmp/cookareq-trace-index-demo/Vsrc/demo.c
   ```

4. В GUI снова откройте **View → Show Trace Index**.
5. Ожидаемый результат: на вкладке **Trace** status сообщает, что cache stale и рекомендуется refresh; diagnostics list содержит issue `STALE_CACHE`.
6. Нажмите **Refresh Trace Index**.
7. Ожидаемый результат: stale indication пропадает, cache обновляется.

## 6. Artifact Browser: список, фильтры, группировка

Цель: проверить просмотр external evidence artifacts.

1. Выполните happy path refresh из раздела 3.
2. Перейдите на вкладку **Artifact Browser**.
3. Ожидаемый результат: status показывает примерно `Artifacts: 30 of 30`, а таблица содержит типы **Code**, **Test Case**, **Test Result**.
4. В поле **Type** выберите **Test Result**.
5. Нажмите **Apply Filter**.
6. Ожидаемый результат: таблица показывает только результаты тестов, примерно `5 of 30`.
7. В поле **RID contains** введите:

   ```text
   LLR10
   ```

8. Нажмите **Apply Filter**.
9. Ожидаемый результат: список сужается до artifacts, связанных с `LLR10`.
10. Нажмите **Clear Filter**.
11. Включите **Group by RID**.
12. Ожидаемый результат: artifacts, покрывающие несколько RID, разворачиваются в отдельные строки по RID; строк становится больше, чем в негруппированном режиме.

## 7. Artifact Browser: открыть artifact

Цель: проверить read-only navigation из Browser.

1. На вкладке **Artifact Browser** выберите любую строку с существующим source/result file.
2. Нажмите **Open Artifact** или дважды кликните строку.
3. Ожидаемый результат: откроется read-only artifact viewer с соответствующим файлом.
4. Для code/test source строк viewer должен открыться около line number artifact, если line number есть в индексе.

## 8. Artifact Matrix: просмотр матрицы

Цель: проверить requirement × artifact projection.

1. Выполните happy path refresh из раздела 3.
2. Перейдите на вкладку **Artifact Matrix**.
3. Ожидаемый результат:
   - status показывает `12 requirements x 30 artifacts`;
   - строки начинаются с RID требований, например `LLR3`, `LLR10`;
   - столбцы включают code/test_case/test_result artifacts;
   - для test result cells отображаются normalized statuses, например `passed`.

## 9. Artifact Matrix → Artifact Browser: фокус по RID

Цель: проверить переход от строки требования в Matrix к Browser.

1. На вкладке **Artifact Matrix** выберите строку `LLR10`.
2. Нажмите **Focus Browser**.
3. Перейдите на вкладку **Artifact Browser**.
4. Ожидаемый результат:
   - поле **RID contains** заполнено `LLR10`;
   - таблица Browser показывает только artifacts, связанные с `LLR10`.

## 10. Artifact Browser → Artifact Matrix: обратный фокус по RID

Цель: проверить обратную навигацию от artifact/evidence к requirement row.

1. На вкладке **Artifact Browser** в поле **RID contains** введите `LLR10`.
2. Нажмите **Apply Filter**.
3. Выберите любую строку с `LLR10` в колонке **Requirements**.
4. Нажмите **Focus Matrix**.
5. Перейдите на вкладку **Artifact Matrix**.
6. Ожидаемый результат: в Matrix выбрана строка `LLR10`.

## 11. Artifact Matrix exports: JSON, CSV, HTML

Цель: проверить exports текущей artifact matrix из GUI.

1. На вкладке **Artifact Matrix** после refresh нажмите **Export JSON**.
2. Сохраните файл, например:

   ```text
   /tmp/cookareq-trace-index-demo/out/trace_artifact_matrix.json
   ```

3. Повторите для **Export CSV** и **Export HTML**.
4. Ожидаемый результат:
   - JSON содержит top-level поля `requirements`, `columns`, `cells`;
   - CSV начинается с колонок `Requirement,Title,...`;
   - HTML содержит заголовок `Trace Index Artifact Matrix` и таблицу.

## 12. Trace tab combined report export

Цель: проверить GUI-export combined HTML report.

1. На вкладке **Trace** после refresh нажмите **Export Report**.
2. Сохраните файл, например:

   ```text
   /tmp/cookareq-trace-index-demo/out/trace_index_report.html
   ```

3. Откройте HTML-файл в браузере.
4. Ожидаемый результат: отчет содержит summary counters, diagnostics table и artifact matrix table.

## 13. JUnit XML ingest в GUI

Fixture по умолчанию проверяет legacy `test_results.txt`. Чтобы вручную увидеть JUnit XML ingest через GUI, добавьте XML-файл в копию demo-проекта.

1. Создайте файл `/tmp/cookareq-trace-index-demo/tests/test_demo/Build/junit_results.xml`:

   ```bash
   cat > /tmp/cookareq-trace-index-demo/tests/test_demo/Build/junit_results.xml <<'XML'
   <?xml version="1.0" encoding="utf-8"?>
   <testsuite name="manual-junit" timestamp="2026-06-25T12:00:00Z">
     <properties>
       <property name="run_id" value="RUN-JUNIT-MANUAL-1" />
       <property name="env" value="manual" />
     </properties>
     <testcase classname="demo" name="test_junit_pass">
       <properties>
         <property name="test_id" value="ТЕСТ-JUNIT-MANUAL-1" />
         <property name="covers" value="LLR10" />
       </properties>
     </testcase>
     <testcase classname="demo" name="test_junit_fail">
       <properties>
         <property name="test_id" value="ТЕСТ-JUNIT-MANUAL-2" />
         <property name="covers" value="LLR11" />
       </properties>
       <failure message="manual failure">stack</failure>
     </testcase>
   </testsuite>
   XML
   ```

2. В GUI откройте **Trace Index** и на вкладке **Trace** убедитесь, что **Result globs** содержит:

   ```text
   tests/test_*/Build/*.xml
   ```

3. Нажмите **Refresh Trace Index**.
4. Ожидаемый результат:
   - summary увеличивает счетчики test runs/test results относительно legacy-only сценария;
   - на вкладке **Artifact Browser** появляются дополнительные **Test Result** строки из `junit_results.xml`;
   - на вкладке **Artifact Matrix** для `LLR10`/`LLR11` появляются cells со статусами из JUnit (`passed` и `failed`).

Если одновременно остались legacy results, это нормально: Trace Index индексирует все файлы, попавшие под Result globs.

## 14. Проверка ошибок JUnit XML

Цель: увидеть diagnostic для невалидного XML/result metadata.

1. Замените содержимое `junit_results.xml` на невалидный XML, например:

   ```bash
   printf '<testsuite><broken></testsuite>\n' > /tmp/cookareq-trace-index-demo/tests/test_demo/Build/junit_results.xml
   ```

2. Нажмите **Refresh Trace Index**.
3. Ожидаемый результат: на вкладке **Trace** появится diagnostic с code `INVALID_MARKER` для XML-файла.
4. Исправьте XML и снова нажмите **Refresh Trace Index**.

## 15. Что дополнительно можно проверить через CLI для сверки с GUI

GUI и CLI используют один core-builder. Если нужно сверить GUI-результаты с CLI, выполните:

```bash
source .venv/bin/activate
python -m app.cli.main trace-index refresh /tmp/cookareq-trace-index-demo/Req --project-root /tmp/cookareq-trace-index-demo
python -m app.cli.main trace-index export /tmp/cookareq-trace-index-demo/Req --project-root /tmp/cookareq-trace-index-demo --view artifact-matrix --format csv --output /tmp/cookareq-trace-index-demo/out/matrix.csv
python -m app.cli.main trace-index export /tmp/cookareq-trace-index-demo/Req --project-root /tmp/cookareq-trace-index-demo --view report --format html --output /tmp/cookareq-trace-index-demo/out/report.html
```

Ожидаемо CLI-export matrix/report должен совпадать по смыслу с GUI exports.

## 16. Быстрый checklist ручной приемки

- [ ] GUI запускается и открывает `/tmp/cookareq-trace-index-demo/Req`.
- [ ] **View → Show Trace Index** открывает окно с 3 вкладками.
- [ ] **Refresh Trace Index** создает generated cache.
- [ ] Summary показывает `Requirements: 12` и test result counters.
- [ ] Diagnostics появляются при включенном `Vsrc/broken_marker.c`.
- [ ] **Open Location** открывает read-only artifact viewer.
- [ ] Artifact Browser показывает Code/Test Case/Test Result rows.
- [ ] Type/RID/Text filters работают.
- [ ] **Group by RID** разворачивает multi-RID artifacts.
- [ ] Artifact Browser открывает artifact viewer.
- [ ] Artifact Matrix показывает requirement × artifact table.
- [ ] Matrix → Browser работает через **Focus Browser**.
- [ ] Browser → Matrix работает через **Focus Matrix**.
- [ ] Matrix exports JSON/CSV/HTML создают файлы.
- [ ] Trace tab **Export Report** создает combined HTML report.
- [ ] JUnit XML файл из Result globs попадает в Test Result rows и Matrix cells.
- [ ] После изменения input file cache становится stale до следующего refresh.
