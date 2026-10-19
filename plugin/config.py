from calibre.utils.config import JSONConfig

prefs = JSONConfig("plugins/kindle_auto_prepare")
prefs.defaults.update({
    "enabled": True,
    "inline_notes": True,
    "darken": True,
    "repair_toc": True,
    "repair_cover": True,
})


def make_widget():
    from qt.core import QWidget, QVBoxLayout, QLabel, QCheckBox
    class Widget(QWidget):
        def __init__(self):
            super().__init__()
            layout = QVBoxLayout(self)
            intro = QLabel("新 EPUB 入库时自动处理，并在从 EPUB 转换前复查。\n只修改 Calibre 使用的临时副本，源文件不变。")
            intro.setWordWrap(True)
            layout.addWidget(intro)
            labels = {
                "enabled": "启用自动处理",
                "inline_notes": "将可确认、单一引用的脚注改为段后文字",
                "darken": "加深译注和正文注音文字",
                "repair_toc": "检查目录目标，补充精确的标题锚点",
                "repair_cover": "检查封面图片引用和封面标记",
            }
            self.boxes = {}
            for key, label in labels.items():
                checkbox = QCheckBox(label)
                checkbox.setChecked(bool(prefs[key]))
                self.boxes[key] = checkbox
                layout.addWidget(checkbox)
            note = QLabel("共享脚注和无法确认的目录目标保留原样，并记录报告。\nKindle 书架缩略图由 Calibre 的内置驱动管理。")
            note.setWordWrap(True)
            layout.addWidget(note)

        def save_settings(self):
            with prefs:
                for key, checkbox in self.boxes.items():
                    prefs[key] = checkbox.isChecked()
    return Widget()


def ConfigWidget():
    return make_widget()
