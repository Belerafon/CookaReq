"""Requirement editor panel."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import wx
from wx.lib.dialogs import ScrolledMessageDialog

from app.core import store
from . import locale


class EditorPanel(wx.Panel):
    """Panel for creating and editing requirements."""

    def __init__(self, parent: wx.Window, on_save: Callable[[], None] | None = None):
        super().__init__(parent)
        self.fields: dict[str, wx.TextCtrl] = {}
        self.enums: dict[str, wx.Choice] = {}
        self._on_save_callback = on_save

        labels = {
            "id": "Идентификатор требования (число)",
            "title": "Краткое название требования",
            "statement": "Полный текст требования",
            "acceptance": "Критерии приемки требования",
            "conditions": "Условия и режимы",
            "trace_up": "Трассировка вверх",
            "trace_down": "Трассировка вниз",
            "version": "Версия требования",
            "modified_at": "Дата изменения",
            "owner": "Ответственный за требование",
            "source": "Источник требования",
            "type": "Тип требования",
            "status": "Текущий статус",
            "priority": "Приоритет исполнения",
            "verification": "Метод проверки",
        }

        help_texts = {
            "id": (
                "Поле 'Идентификатор требования' должно содержать уникальное целое "
                "число без префиксов. Этот номер используется для ссылок на "
                "требование в документации и тестах."
            ),
            "title": (
                "Введите краткое название, которое описывает суть требования. Оно "
                "отображается в списках и помогает быстро понять, о чем идет речь. "
                "Название должно быть коротким, но емким. Заполнение помогает при "
                "поиске и сортировке. Пример: 'Отображение состояния загрузки файла'."
            ),
            "statement": (
                "Основной текст требования. Опишите, что должна делать система или "
                "какие ограничения существуют. Четкая формулировка помогает "
                "разработчикам и тестировщикам одинаково понимать задачу. Пример: "
                "'Система должна сохранять черновик автоматически каждые 5 минут.'"
            ),
            "acceptance": (
                "Критерии приемки описывают, как проверить выполнение требования. "
                "Это могут быть тестовые сценарии или измеримые показатели. "
                "Заполнение поля облегчает работу тестировщиков и заказчика. "
                "Пример: 'При потере связи с сервером появляется уведомление и запись "
                "сохраняется локально.'"
            ),
            "conditions": "Условия выполнения и режимы работы для требования.",
            "trace_up": "Связанные вышестоящие требования.",
            "trace_down": "Связанные нижестоящие требования.",
            "version": "Версия текущего требования.",
            "modified_at": "Дата последнего изменения (устанавливается автоматически).",
            "owner": (
                "Ответственный человек или команда за требование. Укажите имя, "
                "логин или роль, чтобы было понятно, к кому обращаться за "
                "уточнениями. Пример: 'Команда backend', 'Иван Петров'."
            ),
            "source": (
                "Источник требования: документ, запрос клиента или нормативный акт. "
                "Указание источника позволяет отслеживать происхождение и при "
                "изменениях возвращаться к первоисточнику. Пример: 'Договор №123', "
                "'ГОСТ 34.201-89', 'Письмо клиента от 01.01.2025'."
            ),
            "type": (
                "Выберите тип требования: функциональное, ограничение, интерфейс и т.д. "
                "Правильная классификация помогает при анализе и планировании. Пример: "
                "'Ограничение'."
            ),
            "status": (
                "Текущий статус проработки требования. Используется для отслеживания "
                "прогресса: черновик, на рецензии, согласовано и т.п. Это поле помогает "
                "управлять процессом согласования и видеть, что еще требует внимания. "
                "Пример: 'На рецензии'."
            ),
            "priority": (
                "Важность требования. Высокий приоритет реализуется раньше, низкий можно "
                "отложить. Заполнение приоритета помогает планировать релизы и "
                "расставлять ресурсы. Пример: 'Высокий'."
            ),
            "verification": (
                "Метод проверки: инспекция, анализ, демонстрация, испытание. Указание "
                "метода помогает определить подход к тестированию и необходимые ресурсы. "
                "Пример: 'Испытание'."
            ),
        }

        def make_help_button(message: str) -> wx.Button:
            btn = wx.Button(self, label="?", style=wx.BU_EXACTFIT)
            btn.Bind(wx.EVT_BUTTON, lambda _evt, msg=message: self._show_help(msg))
            return btn

        sizer = wx.BoxSizer(wx.VERTICAL)

        for name, multiline in [
            ("id", False),
            ("title", False),
            ("statement", True),
            ("acceptance", True),
            ("conditions", True),
            ("trace_up", True),
            ("trace_down", True),
            ("source", True),
        ]:
            label = wx.StaticText(self, label=labels[name])
            help_btn = make_help_button(help_texts[name])
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            sizer.Add(row, 0, wx.ALL, 5)

            style = wx.TE_MULTILINE if multiline else 0
            ctrl = wx.TextCtrl(self, style=style)
            if name == "source":
                ctrl.SetMinSize((-1, 60))
            self.fields[name] = ctrl
            proportion = 1 if multiline and name != "source" else 0
            sizer.Add(ctrl, proportion, wx.EXPAND | wx.ALL, 5)
            if name == "id":
                ctrl.SetHint("Уникальный целочисленный идентификатор")

        def add_text_field(name: str) -> None:
            container = wx.BoxSizer(wx.VERTICAL)
            label = wx.StaticText(self, label=labels[name])
            help_btn = make_help_button(help_texts[name])
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            container.Add(row, 0, wx.ALL, 5)
            ctrl = wx.TextCtrl(self)
            if name == "modified_at":
                ctrl.SetEditable(False)
            self.fields[name] = ctrl
            container.Add(ctrl, 0, wx.EXPAND | wx.ALL, 5)
            grid.Add(container, 1, wx.EXPAND)

        def add_enum_field(name: str, mapping: dict[str, str]) -> None:
            container = wx.BoxSizer(wx.VERTICAL)
            label = wx.StaticText(self, label=labels[name])
            choice = wx.Choice(self, choices=list(mapping.values()))
            help_btn = make_help_button(help_texts[name])
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            row.Add(choice, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            row.Add(help_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            self.enums[name] = choice
            container.Add(row, 0, wx.EXPAND | wx.ALL, 5)
            grid.Add(container, 1, wx.EXPAND)

        grid = wx.FlexGridSizer(cols=2, hgap=5, vgap=5)
        grid.AddGrowableCol(0, 1)
        grid.AddGrowableCol(1, 1)

        items = [
            ("type", "enum", locale.TYPE),
            ("status", "enum", locale.STATUS),
            ("priority", "enum", locale.PRIORITY),
            ("verification", "enum", locale.VERIFICATION),
            ("modified_at", "text", None),
            ("owner", "text", None),
            ("version", "text", None),
        ]
        for name, kind, mapping in items:
            if kind == "enum":
                add_enum_field(name, mapping)
            else:
                add_text_field(name)

        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 5)

        self.save_btn = wx.Button(self, label="Сохранить")
        self.save_btn.Bind(wx.EVT_BUTTON, self._on_save_button)
        sizer.Add(self.save_btn, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        self.SetSizer(sizer)

        self.attachments: list[dict[str, str]] = []
        self.extra: dict[str, Any] = {
            "labels": [],
            "revision": 1,
            "approved_at": None,
            "notes": "",
        }
        self.current_path: Path | None = None
        self.mtime: float | None = None

    # basic operations -------------------------------------------------
    def new_requirement(self) -> None:
        for ctrl in self.fields.values():
            ctrl.SetValue("")
        defaults = {
            "type": locale.TYPE["requirement"],
            "status": locale.STATUS["draft"],
            "priority": locale.PRIORITY["medium"],
            "verification": locale.VERIFICATION["analysis"],
        }
        for name, choice in self.enums.items():
            choice.SetStringSelection(defaults[name])
        self.attachments = []
        self.current_path = None
        self.mtime = None
        self.extra.update({
            "labels": [],
            "revision": 1,
            "approved_at": None,
            "notes": "",
        })

    def load(self, data: dict[str, Any], *, path: str | Path | None = None, mtime: float | None = None) -> None:
        for name, ctrl in self.fields.items():
            ctrl.SetValue(str(data.get(name, "")))
        self.attachments = list(data.get("attachments", []))
        for name, choice in self.enums.items():
            mapping = getattr(locale, name.upper())
            code = data.get(name, next(iter(mapping)))
            choice.SetStringSelection(locale.code_to_ru(name, code))
        for key in self.extra:
            if key in data:
                self.extra[key] = data[key]
        self.current_path = Path(path) if path else None
        self.mtime = mtime

    def clone(self, new_id: int) -> None:
        self.fields["id"].SetValue(str(new_id))
        self.current_path = None
        self.mtime = None

    # data helpers -----------------------------------------------------
    def get_data(self) -> dict[str, Any]:
        id_value = self.fields["id"].GetValue().strip()
        if not id_value:
            raise ValueError("требуется указать идентификатор")
        try:
            req_id = int(id_value)
        except ValueError as exc:  # pragma: no cover - error path
            raise ValueError("идентификатор должен быть целым числом") from exc
        if req_id <= 0:
            raise ValueError("идентификатор должен быть положительным")

        data = {
            "id": req_id,
            "title": self.fields["title"].GetValue(),
            "statement": self.fields["statement"].GetValue(),
            "type": locale.ru_to_code("type", self.enums["type"].GetStringSelection()),
            "status": locale.ru_to_code("status", self.enums["status"].GetStringSelection()),
            "owner": self.fields["owner"].GetValue(),
            "priority": locale.ru_to_code("priority", self.enums["priority"].GetStringSelection()),
            "source": self.fields["source"].GetValue(),
            "verification": locale.ru_to_code(
                "verification", self.enums["verification"].GetStringSelection()
            ),
            "acceptance": self.fields["acceptance"].GetValue(),
            "conditions": self.fields["conditions"].GetValue(),
            "trace_up": self.fields["trace_up"].GetValue(),
            "trace_down": self.fields["trace_down"].GetValue(),
            "version": self.fields["version"].GetValue(),
            "modified_at": self.fields["modified_at"].GetValue(),
            "labels": self.extra.get("labels", []),
            "attachments": list(self.attachments),
            "revision": self.extra.get("revision", 1),
            "approved_at": self.extra.get("approved_at"),
            "notes": self.extra.get("notes", ""),
        }
        return data

    def _on_save_button(self, _evt: wx.Event) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.fields["modified_at"].SetValue(now)
        if self._on_save_callback:
            self._on_save_callback()

    def save(self, directory: str | Path) -> Path:
        data = self.get_data()
        path = store.save(directory, data, mtime=self.mtime)
        self.current_path = path
        self.mtime = path.stat().st_mtime
        return path

    def delete(self) -> None:
        if self.current_path and self.current_path.exists():
            self.current_path.unlink()
        self.current_path = None
        self.mtime = None

    def add_attachment(self, path: str, note: str = "") -> None:
        self.attachments.append({"path": path, "note": note})

    # helpers ----------------------------------------------------------
    def _show_help(self, message: str) -> None:
        dlg = ScrolledMessageDialog(self, message, "Подсказка")
        dlg.ShowModal()
        dlg.Destroy()
