import os
import stat
from unittest.mock import PropertyMock, patch

import pytest

from _ert_job_runner.job import Job
from _ert_job_runner.reporting.message import Exited, Running, Start


@patch("_ert_job_runner.job.assert_file_executable")
@patch("_ert_job_runner.job.Popen")
@patch("_ert_job_runner.job.Process")
@pytest.mark.usefixtures("use_tmpdir")
def test_run_with_process_failing(
    mock_process, mock_popen, mock_assert_file_executable
):
    job = Job({}, 0)
    type(mock_process.return_value.memory_info.return_value).rss = PropertyMock(
        return_value=10
    )
    mock_process.return_value.wait.return_value = 9

    run = job.run()

    assert isinstance(next(run), Start), "run did not yield Start message"
    assert isinstance(next(run), Running), "run did not yield Running message"
    exited = next(run)
    assert isinstance(exited, Exited), "run did not yield Exited message"
    assert exited.exit_code == 9, "Exited message had unexpected exit code"

    with pytest.raises(StopIteration):
        next(run)


@pytest.mark.flaky(reruns=5)
@pytest.mark.usefixtures("use_tmpdir")
def test_memory_usage_counts_grandchildren():
    scriptname = "recursive_memory_hog.py"
    with open(scriptname, "w", encoding="utf-8") as script:
        script.write(
            """#!/usr/bin/env python
import os
import sys
import time

counter = int(sys.argv[1])
numbers = list(range(int(1e6)))
if counter > 0:
    parent = os.fork()
    if not parent:
        os.execv(sys.argv[0], [sys.argv[0], str(counter - 1)])
time.sleep(0.3)"""  # Too low sleep will make the test faster but flaky
        )
    executable = os.path.realpath(scriptname)
    os.chmod(scriptname, stat.S_IRWXU | stat.S_IRWXO | stat.S_IRWXG)

    def max_memory_per_subprocess_layer(layers: int) -> int:
        job = Job(
            {
                "executable": executable,
                "argList": [str(layers)],
            },
            0,
        )
        job.MEMORY_POLL_PERIOD = 0.01
        max_seen = 0
        for status in job.run():
            if isinstance(status, Running):
                max_seen = max(max_seen, status.max_memory_usage)
        return max_seen

    max_seens = [max_memory_per_subprocess_layer(layers) for layers in range(3)]
    assert max_seens[0] < max_seens[1]
    assert max_seens[1] < max_seens[2]


@pytest.mark.usefixtures("use_tmpdir")
def test_run_fails_using_exit_bash_builtin():
    job = Job(
        {
            "name": "exit 1",
            "executable": "/bin/sh",
            "stdout": "exit_out",
            "stderr": "exit_err",
            "argList": ["-c", 'echo "failed with 1" 1>&2 ; exit 1'],
        },
        0,
    )

    statuses = list(job.run())

    assert len(statuses) == 3, "Wrong statuses count"
    assert statuses[2].exit_code == 1, "Exited status wrong exit_code"
    assert (
        statuses[2].error_message == "Process exited with status code 1"
    ), "Exited status wrong error_message"


@pytest.mark.usefixtures("use_tmpdir")
def test_run_with_defined_executable_but_missing():
    executable = os.path.join(os.getcwd(), "this/is/not/a/file")
    job = Job(
        {
            "name": "TEST_EXECUTABLE_NOT_FOUND",
            "executable": executable,
            "stdout": "mkdir_out",
            "stderr": "mkdir_err",
        },
        0,
    )

    with pytest.raises(IOError):
        for _ in job.run():
            pass


@pytest.mark.usefixtures("use_tmpdir")
def test_run_with_empty_executable():
    empty_executable = os.path.join(os.getcwd(), "foo")
    with open(empty_executable, "a", encoding="utf-8"):
        pass
    st = os.stat(empty_executable)
    os.chmod(empty_executable, st.st_mode | stat.S_IEXEC)

    job = Job(
        {
            "name": "TEST_EXECUTABLE_NOT_EXECUTABLE",
            "executable": empty_executable,
            "stdout": "mkdir_out",
            "stderr": "mkdir_err",
        },
        0,
    )
    run_status = list(job.run())
    assert len(run_status) == 2
    start_msg, exit_msg = run_status
    assert isinstance(start_msg, Start)
    assert isinstance(exit_msg, Exited)
    assert exit_msg.exit_code == 8
    assert "Missing execution format information" in exit_msg.error_message


@pytest.mark.usefixtures("use_tmpdir")
def test_run_with_defined_executable_no_exec_bit():
    non_executable = os.path.join(os.getcwd(), "foo")
    with open(non_executable, "a", encoding="utf-8"):
        pass

    job = Job(
        {
            "name": "TEST_EXECUTABLE_NOT_EXECUTABLE",
            "executable": non_executable,
            "stdout": "mkdir_out",
            "stderr": "mkdir_err",
        },
        0,
    )

    with pytest.raises(IOError):
        for _ in job.run():
            pass


def test_init_job_no_std():
    job = Job(
        {},
        0,
    )
    assert job.std_err is None
    assert job.std_out is None


def test_init_job_with_std():
    job = Job(
        {
            "stdout": "exit_out",
            "stderr": "exit_err",
        },
        0,
    )
    assert job.std_err == "exit_err"
    assert job.std_out == "exit_out"


def test_makedirs(monkeypatch, tmp_path):
    """
    Test that the directories for the output process streams are created if
    they don't exist
    """
    monkeypatch.chdir(tmp_path)
    job = Job(
        {
            "executable": "true",
            "stdout": "a/file",
            "stderr": "b/c/file",
        },
        0,
    )
    for _ in job.run():
        pass
    assert (tmp_path / "a/file").is_file()
    assert (tmp_path / "b/c/file").is_file()
