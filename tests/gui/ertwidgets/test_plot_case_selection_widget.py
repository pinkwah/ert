from pytestqt.qtbot import QtBot
from qtpy.QtCore import Qt

from ert.gui.tools.plot.plot_ensemble_selection_widget import (
    EnsembleSelectionWidget,
    EnsembleSelectListWidget,
)

from ..conftest import get_child


def test_ensemble_selection_widget_max_min_selection(qtbot: QtBot):
    test_ensemble_names = [f"case{i}" for i in range(10)]
    widget = EnsembleSelectionWidget(ensemble_names=test_ensemble_names)
    qtbot.addWidget(widget)
    list_widget = get_child(widget, EnsembleSelectListWidget, "ensemble_selector")

    assert (
        len(widget.getPlotEnsembleNames()) == list_widget.MINIMUM_SELECTED
    )  # initially one selected

    qtbot.mouseClick(
        list_widget.viewport(),
        Qt.LeftButton,
        pos=list_widget.visualItemRect(list_widget.item(0)).center(),
    )  # deselect the only item selected

    assert (
        len(widget.getPlotEnsembleNames()) == list_widget.MINIMUM_SELECTED
    )  # still one selected

    for index in range(list_widget.count()):  # select 'all'
        it = list_widget.item(index)
        qtbot.mouseClick(
            list_widget.viewport(),
            Qt.LeftButton,
            pos=list_widget.visualItemRect(it).center(),
        )

    assert len(widget.getPlotEnsembleNames()) == list_widget.MAXIMUM_SELECTED

    for index in reversed(range(list_widget.count())):  # deselect 'all'
        it = list_widget.item(index)
        qtbot.mouseClick(
            list_widget.viewport(),
            Qt.LeftButton,
            pos=list_widget.visualItemRect(it).center(),
        )

    assert len(widget.getPlotEnsembleNames()) == list_widget.MINIMUM_SELECTED
