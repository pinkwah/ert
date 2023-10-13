import logging

import pytest
from qtpy.QtWidgets import QPlainTextEdit

from ert.gui.tools.event_viewer import EventViewerDialog, GUILogHandler

logger = logging.getLogger(__name__)


@pytest.mark.parametrize(
    "log_func, expected",
    [
        (logger.debug, ""),
        (logger.info, "INFO     Writing some text"),
        (logger.warning, "WARNING  Writing some text"),
        (logger.error, "ERROR    Writing some text"),
    ],
)
def test_logging_widget(qtbot, caplog, log_func, expected):
    logging_handle = GUILogHandler()
    logger.addHandler(logging_handle)

    widget = EventViewerDialog(logging_handle)
    qtbot.addWidget(widget)

    widget.open()
    with qtbot.waitExposed(widget), caplog.at_level(logging.DEBUG):
        log_func("Writing some text")
        assert widget.findChild(QPlainTextEdit).toPlainText() == expected
