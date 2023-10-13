from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator, Optional

from qtpy import QtCore
from qtpy.QtCore import QObject
from qtpy.QtWidgets import QDialog, QPlainTextEdit, QVBoxLayout, QWidget


_LOG_HANDLER: Optional[GUILogHandler] = None


class GUILogHandler(logging.Handler, QObject):
    """
    Log handler which will emit a qt signal every time a
    log is emitted
    """

    append_log_statement = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
        self.setLevel(logging.INFO)

        QObject.__init__(self)

    def emit(self, record):
        msg = self.format(record)
        self.append_log_statement.emit(msg)


class EventViewerDialog(QDialog):
    def __init__(self, log_handler: Optional[GUILogHandler] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)

        if log_handler is None:
            log_handler = _LOG_HANDLER
            assert log_handler is not None

        self.setMinimumSize(500, 200)
        self.setWindowTitle("Event viewer")

        text_box = QPlainTextEdit(self)
        text_box.setReadOnly(True)
        text_box.setMaximumBlockCount(1000)

        log_handler.append_log_statement.connect(text_box.appendPlainText)


@contextmanager
def add_gui_log_handler() -> Iterator[GUILogHandler]:
    """
    Context manager for the GUILogHandler class. Will make sure that the handler
    is removed prior to program exit.
    """
    logger = logging.getLogger()

    handler = GUILogHandler()
    logger.addHandler(handler)

    global _LOG_HANDLER
    _LOG_HANDLER = handler

    yield handler

    logger.removeHandler(handler)
