import datetime
from unittest.mock import patch

import pytest
from dateutil import tz
from PyQt5.QtCore import QModelIndex
from pytestqt.qt_compat import qt_api

from ert.ensemble_evaluator import identifiers as ids
from ert.ensemble_evaluator.snapshot import ForwardModel, PartialSnapshot
from ert.ensemble_evaluator.state import (
    FORWARD_MODEL_STATE_FAILURE,
    FORWARD_MODEL_STATE_RUNNING,
    FORWARD_MODEL_STATE_START,
)
from ert.gui.model.job_list import JobListProxyModel
from ert.gui.model.node import NodeType
from ert.gui.model.snapshot import COLUMNS, DURATION, SnapshotModel

from .gui_models_utils import partial_snapshot


def _id_to_col(identifier):
    for col, fields in enumerate(COLUMNS[NodeType.REAL]):
        if fields[1] == identifier:
            return col
    raise ValueError(f"{identifier} not a column in {COLUMNS}")


def test_using_qt_model_tester(qtmodeltester, full_snapshot):
    partial = partial_snapshot(full_snapshot)
    source_model = SnapshotModel()

    model = JobListProxyModel(None, 0, 0)
    model.setSourceModel(source_model)

    reporting_mode = qt_api.QtTest.QAbstractItemModelTester.FailureReportingMode.Warning
    tester = qt_api.QtTest.QAbstractItemModelTester(  # noqa: F841, prevent GC
        model, reporting_mode
    )

    source_model._add_snapshot(SnapshotModel.prerender(full_snapshot), 0)
    source_model._add_snapshot(SnapshotModel.prerender(full_snapshot), 1)

    source_model._add_partial_snapshot(SnapshotModel.prerender(partial), 0)
    source_model._add_partial_snapshot(SnapshotModel.prerender(partial), 1)

    qtmodeltester.check(model, force_py=True)


def test_changes(full_snapshot):
    source_model = SnapshotModel()

    model = JobListProxyModel(None, 0, 0)
    model.setSourceModel(source_model)

    reporting_mode = qt_api.QtTest.QAbstractItemModelTester.FailureReportingMode.Warning
    tester = qt_api.QtTest.QAbstractItemModelTester(  # noqa: F841, prevent GC
        model, reporting_mode
    )

    source_model._add_snapshot(SnapshotModel.prerender(full_snapshot), 0)
    assert model.index(0, _id_to_col(ids.STATUS)).data() == FORWARD_MODEL_STATE_START

    partial = PartialSnapshot(full_snapshot)
    start_time = datetime.datetime(year=2020, month=10, day=27, hour=12)
    end_time = datetime.datetime(year=2020, month=10, day=28, hour=13)
    partial.update_forward_model(
        "0",
        "0",
        forward_model=ForwardModel(
            status=FORWARD_MODEL_STATE_FAILURE,
            start_time=start_time,
            end_time=end_time,
        ),
    )
    source_model._add_partial_snapshot(SnapshotModel.prerender(partial), 0)
    assert (
        model.index(0, _id_to_col(DURATION), QModelIndex()).data() == "1 day, 1:00:00"
    )
    assert (
        model.index(0, _id_to_col(ids.STATUS), QModelIndex()).data()
        == FORWARD_MODEL_STATE_FAILURE
    )


@pytest.mark.parametrize("timezone", [(None), (tz.gettz("UTC"))])
@patch("ert.gui.model.snapshot.datetime", wraps=datetime)
def test_duration(mock_datetime, timezone, full_snapshot):
    source_model = SnapshotModel()

    model = JobListProxyModel(None, 0, 0)
    model.setSourceModel(source_model)

    reporting_mode = qt_api.QtTest.QAbstractItemModelTester.FailureReportingMode.Warning
    tester = qt_api.QtTest.QAbstractItemModelTester(  # noqa: F841, prevent GC
        model, reporting_mode
    )

    source_model._add_snapshot(SnapshotModel.prerender(full_snapshot), 0)
    assert (
        model.index(0, _id_to_col(ids.STATUS), QModelIndex()).data()
        == FORWARD_MODEL_STATE_START
    )

    partial = PartialSnapshot(full_snapshot)
    start_time = datetime.datetime(
        year=2020, month=10, day=27, hour=12, tzinfo=timezone
    )
    # mock only datetime.datetime.now()
    mock_datetime.datetime.now.return_value = datetime.datetime(
        year=2020,
        month=10,
        day=28,
        hour=13,
        minute=12,
        second=11,
        microsecond=5,  # Note that microseconds are intended to be removed
        tzinfo=timezone,
    )
    partial.update_forward_model(
        "0",
        "2",
        forward_model=ForwardModel(
            status=FORWARD_MODEL_STATE_RUNNING,
            start_time=start_time,
        ),
    )
    source_model._add_partial_snapshot(SnapshotModel.prerender(partial), 0)
    assert (
        model.index(2, _id_to_col(DURATION), QModelIndex()).data() == "1 day, 1:12:11"
    )
    mock_datetime.datetime.now.assert_called_once_with(timezone)


def test_no_cross_talk(full_snapshot):
    source_model = SnapshotModel()

    model = JobListProxyModel(None, 0, 0)
    model.setSourceModel(source_model)

    reporting_mode = qt_api.QtTest.QAbstractItemModelTester.FailureReportingMode.Warning
    qt_api.QtTest.QAbstractItemModelTester(model, reporting_mode)  # noqa: F841

    source_model._add_snapshot(SnapshotModel.prerender(full_snapshot), 0)
    source_model._add_snapshot(SnapshotModel.prerender(full_snapshot), 1)

    # Test that changes to iter=1 does not bleed into iter=0
    partial = PartialSnapshot(full_snapshot)
    partial.update_forward_model(
        "0", "0", forward_model=ForwardModel(status=FORWARD_MODEL_STATE_FAILURE)
    )
    source_model._add_partial_snapshot(SnapshotModel.prerender(partial), 1)
    assert (
        model.index(0, _id_to_col(ids.STATUS), QModelIndex()).data()
        == FORWARD_MODEL_STATE_START
    )

    model.set_real(1, 0)
    assert (
        model.index(0, _id_to_col(ids.STATUS), QModelIndex()).data()
        == FORWARD_MODEL_STATE_FAILURE
    )
