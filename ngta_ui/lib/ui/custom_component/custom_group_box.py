from PySide6.QtWidgets import QGroupBox, QLineEdit

from ngta_ui.lib.ui.custom_component.custom_button import ResizableButton
from ngta_ui.lib.ui.custom_component.other_components import CustomQLabel, CustomQCheckBox, CustomQComboBox


class QGroupBoxBase(QGroupBox):
    def __init__(self, title):
        super().__init__(title)
        self.buttons = {}
        self.entries = {}
        self.combo_boxes = {}
        self.check_boxes = {}

    def create_button(self, name, text=None):
        if text is None:
            text = name.replace('_', ' ')
        button = ResizableButton(text)
        self.buttons[name] = button
        return button

    def create_entry(self, name, default_value, suffix=None):
        line_edit = QLineEdit()
        line_edit.setText(default_value)
        self.entries[name] = line_edit
        if suffix:
            # 这里返回一个元组，包含输入框和后缀标签
            suffix_label = CustomQLabel()
            return line_edit, suffix_label
        return line_edit

    def create_combobox(self, name, items):
        combo_box = CustomQComboBox()
        combo_box.addItems(items)
        self.combo_boxes[name] = combo_box
        return combo_box

    def create_checkbox(self, name, text):
        checkbox = CustomQCheckBox(text)
        self.check_boxes[name] = checkbox
        return checkbox