from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QScrollArea, QVBoxLayout, QWidget
from petcore.ui.settings.base import make_button
from petcore.ui.settings.style import is_dark, stylesheet
from .runtime import texts


class DivinationCard(QDialog):
    def __init__(self, state, slot, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'每日一签 · 宠物 {slot}')
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet(stylesheet(is_dark()))
        self.resize(460, 380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(18)
        self.heading = QLabel(self)
        self.heading.setProperty('role', 'sectionTitle')
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        area = QScrollArea(self)
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget(area)
        inner = QVBoxLayout(body)
        self.content = QLabel(body)
        self.content.setTextFormat(Qt.TextFormat.PlainText)
        self.content.setWordWrap(True)
        self.content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.content.setAccessibleName('完整签文与解签')
        inner.addWidget(self.content)
        inner.addStretch()
        area.setWidget(body)
        layout.addWidget(area, 1)
        close = make_button('收好今日签', self, primary=True)
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self.set_state(state)

    def set_state(self, state):
        number = f"第 {state['quote_id']} 签" if state['quote_id'] else '升级前今日签'
        self.heading.setText(f"{state['date']} · {number}")
        self.content.setText('\n\n'.join(texts(state)[1]))
