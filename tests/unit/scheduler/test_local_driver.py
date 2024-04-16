import asyncio
import os
import signal
from pathlib import Path

import pytest

from ert.scheduler import local_driver
from ert.scheduler.driver import SIGNAL_OFFSET
from ert.scheduler.event import FinishedEvent, StartedEvent
from ert.scheduler.local_driver import LocalDriver


async def test_success(tmp_path):
    driver = LocalDriver()

    os.chdir(tmp_path)
    await driver.submit(42, "/usr/bin/env", "touch", "testfile")
    assert await driver.event_queue.get() == StartedEvent(iens=42)
    assert await driver.event_queue.get() == FinishedEvent(iens=42, returncode=0)

    assert Path("testfile").exists()


async def test_failure():
    driver = LocalDriver()

    await driver.submit(42, "/usr/bin/env", "false")
    assert await driver.event_queue.get() == StartedEvent(iens=42)
    assert await driver.event_queue.get() == FinishedEvent(iens=42, returncode=1)


async def test_file_not_found():
    driver = LocalDriver()

    await driver.submit(42, "/file/not/found")
    assert await driver.event_queue.get() == FinishedEvent(iens=42, returncode=127)


async def test_kill():
    driver = LocalDriver()

    await driver.submit(42, "/usr/bin/env", "sleep", "10")
    assert await driver.event_queue.get() == StartedEvent(iens=42)
    await driver.kill(42)
    assert await driver.event_queue.get() == FinishedEvent(
        iens=42, returncode=signal.SIGTERM + SIGNAL_OFFSET
    )


@pytest.mark.timeout(10)
async def test_kill_unresponsive_process(monkeypatch, tmp_path):
    # Reduce timeout to something more appropriate for a test
    monkeypatch.setattr(local_driver, "_TERMINATE_TIMEOUT", 0.1)

    (tmp_path / "script").write_text(
        """\
    trap "" 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15
    start=$(date +%s)
    while true
    do
        now=$(date +%s)
        runtime=$((now - start))
        echo "I'm still alive at runtime $runtime"
        sleep 20
    done
    """
    )

    driver = LocalDriver()

    await driver.submit(42, "/usr/bin/env", "bash", str(tmp_path / "script"))
    assert await driver.event_queue.get() == StartedEvent(iens=42)

    # Allow the script to trap signals
    await asyncio.sleep(1)

    await driver.kill(42)
    assert await driver.event_queue.get() == FinishedEvent(
        iens=42, returncode=signal.SIGKILL + SIGNAL_OFFSET
    )


@pytest.mark.parametrize("cmd,returncode", [("true", 0), ("false", 1)])
async def test_kill_when_job_completed(cmd, returncode):
    driver = LocalDriver()

    await driver.submit(42, "/usr/bin/env", cmd)
    assert await driver.event_queue.get() == StartedEvent(iens=42)
    await asyncio.sleep(0.5)
    await driver.kill(42)
    assert await driver.event_queue.get() == FinishedEvent(
        iens=42, returncode=returncode
    )


async def test_that_killing_killed_job_does_not_raise():
    driver = LocalDriver()
    await driver.submit(23, "/usr/bin/env", "sleep", "10")
    assert await driver.event_queue.get() == StartedEvent(iens=23)
    await driver.kill(23)
    assert await driver.event_queue.get() == FinishedEvent(
        iens=23, returncode=signal.SIGTERM + SIGNAL_OFFSET
    )
    # Killing a dead job should not raise an exception
    await driver.kill(23)
    await driver.kill(23)
    await driver.kill(23)
    assert driver.event_queue.empty()
