import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from pytestqt.qtbot import QtBot
from qtpy import QtWidgets
from qtpy.QtCore import Qt, QTimer
from qtpy.QtWidgets import QToolButton

from ert.config import ErtConfig
from ert.enkf_main import EnKFMain
from ert.ensemble_evaluator import state
from ert.ensemble_evaluator.event import (
    EndEvent,
    FullSnapshotEvent,
    SnapshotUpdateEvent,
)
from ert.ensemble_evaluator.snapshot import PartialSnapshot, SnapshotBuilder
from ert.gui.main import GUILogHandler, _setup_main_window
from ert.gui.simulation.run_dialog import RunDialog
from ert.gui.simulation.view.realization import RealizationWidget
from ert.gui.tools.file import FileDialog
from ert.services import StorageService


def test_success(runmodel, qtbot: QtBot, mock_tracker):
    notifier = Mock()
    widget = RunDialog("poly.ert", runmodel, notifier)
    widget.show()
    qtbot.addWidget(widget)

    with patch("ert.gui.simulation.run_dialog.EvaluatorTracker") as tracker:
        tracker.return_value = mock_tracker([EndEvent(failed=False, failed_msg="")])
        widget.startSimulation()

    with qtbot.waitExposed(widget, timeout=30000):
        qtbot.waitUntil(lambda: widget._total_progress_bar.value() == 100)
        qtbot.waitUntil(widget.done_button.isVisible, timeout=100)
        assert widget.done_button.text() == "Done"


def test_kill_simulations(runmodel, qtbot: QtBot, mock_tracker):
    notifier = Mock()
    widget = RunDialog("poly.ert", runmodel, notifier)
    widget.show()
    qtbot.addWidget(widget)

    with patch("ert.gui.simulation.run_dialog.EvaluatorTracker") as tracker:
        tracker.return_value = mock_tracker([EndEvent(failed=False, failed_msg="")])
        widget.startSimulation()

    with qtbot.waitSignal(widget.finished, timeout=30000):

        def handle_dialog():
            qtbot.waitUntil(
                lambda: len(
                    [
                        x
                        for x in widget.children()
                        if isinstance(x, QtWidgets.QMessageBox)
                    ]
                )
                > 0
            )
            message_box = [
                x for x in widget.children() if isinstance(x, QtWidgets.QMessageBox)
            ][0]
            dialog_button_box = [
                x
                for x in message_box.children()
                if isinstance(x, QtWidgets.QDialogButtonBox)
            ][0]
            qtbot.mouseClick(dialog_button_box.children()[-2], Qt.LeftButton)

        QTimer.singleShot(100, handle_dialog)
        widget.killJobs()


def test_large_snapshot(
    runmodel, large_snapshot, qtbot: QtBot, mock_tracker, timeout_per_iter=5000
):
    notifier = Mock()
    widget = RunDialog("poly.ert", runmodel, notifier)
    widget.show()
    qtbot.addWidget(widget)

    with patch("ert.gui.simulation.run_dialog.EvaluatorTracker") as tracker:
        iter_0 = FullSnapshotEvent(
            snapshot=large_snapshot,
            phase_name="Foo",
            current_phase=0,
            total_phases=1,
            progress=0.5,
            iteration=0,
            indeterminate=False,
        )
        iter_1 = FullSnapshotEvent(
            snapshot=large_snapshot,
            phase_name="Foo",
            current_phase=0,
            total_phases=1,
            progress=0.5,
            iteration=1,
            indeterminate=False,
        )
        tracker.return_value = mock_tracker(
            [iter_0, iter_1, EndEvent(failed=False, failed_msg="")]
        )
        widget.startSimulation()

    with qtbot.waitExposed(widget, timeout=timeout_per_iter * 6):
        qtbot.waitUntil(
            lambda: widget._total_progress_bar.value() == 100,
            timeout=timeout_per_iter * 3,
        )
        qtbot.mouseClick(widget.show_details_button, Qt.LeftButton)
        qtbot.waitUntil(
            lambda: widget._tab_widget.count() == 2, timeout=timeout_per_iter
        )
        qtbot.waitUntil(
            lambda: widget.done_button.isVisible(), timeout=timeout_per_iter
        )


@pytest.mark.parametrize(
    "events,tab_widget_count",
    [
        pytest.param(
            [
                FullSnapshotEvent(
                    snapshot=(
                        SnapshotBuilder()
                        .add_forward_model(
                            forward_model_id="0",
                            index="0",
                            name="job_0",
                            status=state.FORWARD_MODEL_STATE_START,
                        )
                        .build(["0"], state.REALIZATION_STATE_UNKNOWN)
                    ),
                    phase_name="Foo",
                    current_phase=0,
                    total_phases=1,
                    progress=0.25,
                    iteration=0,
                    indeterminate=False,
                ),
                SnapshotUpdateEvent(
                    partial_snapshot=PartialSnapshot(
                        SnapshotBuilder().build(
                            [], status=state.REALIZATION_STATE_FINISHED
                        )
                    ),
                    phase_name="Foo",
                    current_phase=0,
                    total_phases=1,
                    progress=0.5,
                    iteration=0,
                    indeterminate=False,
                ),
                EndEvent(failed=False, failed_msg=""),
            ],
            1,
            id="real_less_partial",
        ),
        pytest.param(
            [
                FullSnapshotEvent(
                    snapshot=(
                        SnapshotBuilder()
                        .add_forward_model(
                            forward_model_id="0",
                            index="0",
                            name="job_0",
                            max_memory_usage="1000",
                            current_memory_usage="500",
                            status=state.FORWARD_MODEL_STATE_START,
                        )
                        .build(["0"], state.REALIZATION_STATE_UNKNOWN)
                    ),
                    phase_name="Foo",
                    current_phase=0,
                    total_phases=1,
                    progress=0.25,
                    iteration=0,
                    indeterminate=False,
                ),
                SnapshotUpdateEvent(
                    partial_snapshot=PartialSnapshot(
                        SnapshotBuilder().build(
                            ["0"], status=state.REALIZATION_STATE_FINISHED
                        )
                    ),
                    phase_name="Foo",
                    current_phase=0,
                    total_phases=1,
                    progress=0.5,
                    iteration=0,
                    indeterminate=False,
                ),
                EndEvent(failed=False, failed_msg=""),
            ],
            1,
            id="jobless_partial",
        ),
        pytest.param(
            [
                FullSnapshotEvent(
                    snapshot=(
                        SnapshotBuilder()
                        .add_forward_model(
                            forward_model_id="0",
                            index="0",
                            name="job_0",
                            status=state.FORWARD_MODEL_STATE_START,
                        )
                        .add_forward_model(
                            forward_model_id="1",
                            index="1",
                            name="job_1",
                            status=state.FORWARD_MODEL_STATE_START,
                        )
                        .build(["0", "1"], state.REALIZATION_STATE_UNKNOWN)
                    ),
                    phase_name="Foo",
                    current_phase=0,
                    total_phases=1,
                    progress=0.25,
                    iteration=0,
                    indeterminate=False,
                ),
                SnapshotUpdateEvent(
                    partial_snapshot=PartialSnapshot(
                        SnapshotBuilder()
                        # .add_step(status=state.STEP_STATE_SUCCESS)
                        .add_forward_model(
                            forward_model_id="0",
                            index="0",
                            status=state.FORWARD_MODEL_STATE_FINISHED,
                            name="job_0",
                        )
                        .build(["1"], status=state.REALIZATION_STATE_RUNNING)
                    ),
                    phase_name="Foo",
                    current_phase=0,
                    total_phases=1,
                    progress=0.5,
                    iteration=0,
                    indeterminate=False,
                ),
                SnapshotUpdateEvent(
                    partial_snapshot=PartialSnapshot(
                        SnapshotBuilder()
                        .add_forward_model(
                            forward_model_id="1",
                            index="1",
                            status=state.FORWARD_MODEL_STATE_FAILURE,
                            name="job_1",
                        )
                        .build(["0"], status=state.REALIZATION_STATE_FAILED)
                    ),
                    phase_name="Foo",
                    current_phase=0,
                    total_phases=1,
                    progress=0.5,
                    iteration=0,
                    indeterminate=False,
                ),
                EndEvent(failed=False, failed_msg=""),
            ],
            1,
            id="two_job_updates_over_two_partials",
        ),
        pytest.param(
            [
                FullSnapshotEvent(
                    snapshot=(
                        SnapshotBuilder()
                        .add_forward_model(
                            forward_model_id="0",
                            index="0",
                            name="job_0",
                            status=state.FORWARD_MODEL_STATE_START,
                        )
                        .build(["0"], state.REALIZATION_STATE_UNKNOWN)
                    ),
                    phase_name="Foo",
                    current_phase=0,
                    total_phases=1,
                    progress=0.25,
                    iteration=0,
                    indeterminate=False,
                ),
                FullSnapshotEvent(
                    snapshot=(
                        SnapshotBuilder()
                        .add_forward_model(
                            forward_model_id="0",
                            index="0",
                            name="job_0",
                            status=state.FORWARD_MODEL_STATE_START,
                        )
                        .build(["0"], state.REALIZATION_STATE_UNKNOWN)
                    ),
                    phase_name="Foo",
                    current_phase=0,
                    total_phases=1,
                    progress=0.5,
                    iteration=1,
                    indeterminate=False,
                ),
                EndEvent(failed=False, failed_msg=""),
            ],
            2,
            id="two_iterations",
        ),
    ],
)
def test_run_dialog(events, tab_widget_count, runmodel, qtbot: QtBot, mock_tracker):
    notifier = Mock()
    widget = RunDialog("poly.ert", runmodel, notifier)
    widget.show()
    qtbot.addWidget(widget)

    with patch("ert.gui.simulation.run_dialog.EvaluatorTracker") as tracker:
        tracker.return_value = mock_tracker(events)
        widget.startSimulation()

    with qtbot.waitExposed(widget, timeout=30000):
        qtbot.mouseClick(widget.show_details_button, Qt.LeftButton)
        qtbot.waitUntil(
            lambda: widget._tab_widget.count() == tab_widget_count, timeout=5000
        )
        qtbot.waitUntil(widget.done_button.isVisible, timeout=5000)


@pytest.mark.usefixtures("copy_poly_case", "using_scheduler")
def test_that_run_dialog_can_be_closed_while_file_plot_is_open(qtbot: QtBot, storage):
    """
    This is a regression test for a crash happening when
    closing the RunDialog with a file open.
    """

    config_file = Path("poly.ert")
    args_mock = Mock()
    args_mock.config = str(config_file)

    ert_config = ErtConfig.from_file(str(config_file))
    enkf_main = EnKFMain(ert_config)
    with StorageService.init_service(
        project=os.path.abspath(ert_config.ens_path),
    ):
        gui = _setup_main_window(enkf_main, args_mock, GUILogHandler(), storage)
        qtbot.addWidget(gui)
        start_simulation = gui.findChild(QToolButton, name="start_simulation")

        qtbot.mouseClick(start_simulation, Qt.LeftButton)

        qtbot.waitUntil(lambda: gui.findChild(RunDialog) is not None)
        run_dialog = gui.findChild(RunDialog)
        qtbot.mouseClick(run_dialog.show_details_button, Qt.LeftButton)
        job_view = run_dialog._job_view
        qtbot.waitUntil(job_view.isVisible, timeout=20000)
        qtbot.waitUntil(run_dialog.done_button.isVisible, timeout=200000)

        realization_widget = run_dialog.findChild(RealizationWidget)

        click_pos = realization_widget._real_view.rectForIndex(
            realization_widget._real_list_model.index(0, 0)
        ).center()

        with qtbot.waitSignal(realization_widget.currentChanged, timeout=30000):
            qtbot.mouseClick(
                realization_widget._real_view.viewport(),
                Qt.LeftButton,
                pos=click_pos,
            )
        click_pos = job_view.visualRect(run_dialog._job_model.index(0, 4)).center()
        qtbot.mouseClick(job_view.viewport(), Qt.LeftButton, pos=click_pos)

        qtbot.waitUntil(run_dialog.findChild(FileDialog).isVisible, timeout=3000)

        with qtbot.waitSignal(run_dialog.accepted, timeout=30000):
            run_dialog.close()  # Close the run dialog by pressing 'x' close button

        # Ensure that once the run dialog is closed
        # another simulation can be started
        assert start_simulation.isEnabled()


@pytest.mark.parametrize(
    "events,tab_widget_count",
    [
        pytest.param(
            [
                FullSnapshotEvent(
                    snapshot=(
                        SnapshotBuilder()
                        .add_forward_model(
                            forward_model_id="0",
                            index="0",
                            name="job_0",
                            status=state.FORWARD_MODEL_STATE_START,
                        )
                        .build(["0"], state.REALIZATION_STATE_UNKNOWN)
                    ),
                    phase_name="Foo",
                    current_phase=0,
                    total_phases=1,
                    progress=0.25,
                    iteration=0,
                    indeterminate=False,
                ),
                SnapshotUpdateEvent(
                    partial_snapshot=PartialSnapshot(
                        SnapshotBuilder()
                        .add_forward_model(
                            forward_model_id="0",
                            index="0",
                            status=state.FORWARD_MODEL_STATE_RUNNING,
                            current_memory_usage=45000,
                            max_memory_usage=55000,
                            name="job_0",
                        )
                        .build(["0"], status=state.REALIZATION_STATE_RUNNING)
                    ),
                    phase_name="Foo",
                    current_phase=0,
                    total_phases=1,
                    progress=0.5,
                    iteration=0,
                    indeterminate=False,
                ),
                SnapshotUpdateEvent(
                    partial_snapshot=PartialSnapshot(
                        SnapshotBuilder()
                        .add_forward_model(
                            forward_model_id="0",
                            index="0",
                            status=state.FORWARD_MODEL_STATE_FINISHED,
                            name="job_0",
                            current_memory_usage=50000,
                            max_memory_usage=60000,
                        )
                        .build(["0"], status=state.REALIZATION_STATE_FINISHED)
                    ),
                    phase_name="Foo",
                    current_phase=0,
                    total_phases=1,
                    progress=1,
                    iteration=0,
                    indeterminate=False,
                ),
                EndEvent(failed=False, failed_msg=""),
            ],
            1,
            id="running_job_with_memory_usage",
        ),
    ],
)
def test_run_dialog_memory_usage_showing(
    events, tab_widget_count, runmodel, qtbot: QtBot, mock_tracker
):
    notifier = Mock()
    widget = RunDialog("poly.ert", runmodel, notifier)
    widget.show()
    qtbot.addWidget(widget)

    with patch("ert.gui.simulation.run_dialog.EvaluatorTracker") as tracker:
        tracker.return_value = mock_tracker(events)
        widget.startSimulation()

    with qtbot.waitExposed(widget, timeout=30000):
        qtbot.mouseClick(widget.show_details_button, Qt.LeftButton)
        qtbot.waitUntil(
            lambda: widget._tab_widget.count() == tab_widget_count, timeout=5000
        )
        qtbot.waitUntil(widget.done_button.isVisible, timeout=5000)

        # This is the container of realization boxes
        realization_box = widget._tab_widget.widget(0)
        assert type(realization_box) == RealizationWidget
        # Click the first realization box
        qtbot.mouseClick(realization_box, Qt.LeftButton)
        assert widget._job_model._real == 0

        job_number = 0
        current_memory_column_index = 6
        max_memory_column_index = 7

        current_memory_column_proxy_index = widget._job_model.index(
            job_number, current_memory_column_index
        )
        current_memory_value = widget._job_model.data(
            current_memory_column_proxy_index, Qt.DisplayRole
        )
        assert current_memory_value == "50.00 kB"

        max_memory_column_proxy_index = widget._job_model.index(
            job_number, max_memory_column_index
        )
        max_memory_value = widget._job_model.data(
            max_memory_column_proxy_index, Qt.DisplayRole
        )
        assert max_memory_value == "60.00 kB"


@pytest.mark.usefixtures("use_tmpdir", "set_site_config", "using_scheduler")
def test_that_gui_runs_a_minimal_example(qtbot: QtBot, storage):
    """
    This is a regression test for a crash happening when clicking show details
    when running a minimal example.
    """
    config_file = "minimal_config.ert"
    with open(config_file, "w", encoding="utf-8") as f:
        f.write("NUM_REALIZATIONS 1")
    args_mock = Mock()
    args_mock.config = config_file

    ert_config = ErtConfig.from_file(config_file)
    enkf_main = EnKFMain(ert_config)
    with StorageService.init_service(
        project=os.path.abspath(ert_config.ens_path),
    ):
        gui = _setup_main_window(enkf_main, args_mock, GUILogHandler(), storage)
        qtbot.addWidget(gui)
        start_simulation = gui.findChild(QToolButton, name="start_simulation")

        qtbot.mouseClick(start_simulation, Qt.LeftButton)

        qtbot.waitUntil(lambda: gui.findChild(RunDialog) is not None)
        run_dialog = gui.findChild(RunDialog)
        qtbot.mouseClick(run_dialog.show_details_button, Qt.LeftButton)
        qtbot.waitUntil(run_dialog.done_button.isVisible, timeout=200000)
