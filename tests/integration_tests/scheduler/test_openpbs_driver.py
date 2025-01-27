import asyncio
import os
import signal
import sys
from typing import Set

import pytest

from ert.scheduler.event import FinishedEvent, StartedEvent
from ert.scheduler.openpbs_driver import Driver, OpenPBSDriver


@pytest.fixture(autouse=True)
def mock_torque(pytestconfig, request, monkeypatch, tmp_path):
    if pytestconfig.getoption("torque"):
        # User provided --torque, which means we should use the actual TORQUE
        # cluster without mocking anything.
        return

    bin_path = os.path.join(os.path.dirname(__file__), "bin")

    monkeypatch.setenv("PATH", f"{bin_path}:{os.environ['PATH']}")
    monkeypatch.setenv("PYTEST_TMP_PATH", str(tmp_path))
    monkeypatch.setenv("PYTHON", sys.executable)


async def poll(driver: Driver, expected: Set[int], *, started=None, finished=None):
    poll_task = asyncio.create_task(driver.poll())
    completed = set()
    try:
        while True:
            event = await driver.event_queue.get()
            if isinstance(event, StartedEvent):
                if started:
                    await started(event.iens)

            elif isinstance(event, FinishedEvent):
                if finished is not None:
                    await finished(event.iens, event.returncode, event.aborted)

                completed.add(event.iens)
                if completed == expected:
                    break
    finally:
        poll_task.cancel()


@pytest.mark.integration_test
async def test_submit(tmp_path):
    driver = OpenPBSDriver()
    await driver.submit(
        0, "sh", "-c", f"echo test > {tmp_path}/test", cwd=str(tmp_path)
    )
    await poll(driver, {0})

    assert (tmp_path / "test").read_text() == "test\n"


@pytest.mark.integration_test
async def test_returncode(tmp_path):
    driver = OpenPBSDriver()
    finished_called = False

    async def finished(iens, returncode, aborted):
        assert iens == 0
        assert returncode == 42
        assert aborted is False

        nonlocal finished_called
        finished_called = True

    await driver.submit(0, "sh", "-c", "exit 42", cwd=str(tmp_path))
    await poll(driver, {0}, finished=finished)
    assert finished_called


@pytest.mark.integration_test
async def test_kill(tmp_path):
    driver = OpenPBSDriver()
    aborted_called = False

    async def started(iens):
        nonlocal driver
        await driver.kill(iens)

    async def finished(iens, returncode, aborted):
        assert iens == 0
        assert returncode == 256 + signal.SIGTERM
        assert aborted is True

        nonlocal aborted_called
        aborted_called = True

    await driver.submit(0, "sh", "-c", "sleep 60; exit 2", cwd=str(tmp_path))
    await poll(driver, {0}, started=started, finished=finished)
    assert aborted_called
