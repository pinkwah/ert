import pytest
import os

from ert.config import QueueConfig, QueueSystem
from ert import HAS_CLIB


@pytest.mark.skipif(not HAS_CLIB, reason="ert._clib not installed")
@pytest.fixture
def create_driver():
    from ert.job_queue import Driver
    return Driver.create_driver


def test_set_and_unset_option(create_driver):
    queue_config = QueueConfig(
        job_script="script.sh",
        queue_system=QueueSystem.LOCAL,
        max_submit=2,
        queue_options={
            QueueSystem.LOCAL: [
                ("MAX_RUNNING", "50"),
                ("MAX_RUNNING", ""),
            ]
        },
    )
    driver = create_driver(queue_config)
    assert driver.get_option("MAX_RUNNING") == "0"
    assert driver.set_option("MAX_RUNNING", "42")
    assert driver.get_option("MAX_RUNNING") == "42"
    driver.set_option("MAX_RUNNING", "")
    assert driver.get_option("MAX_RUNNING") == "0"
    driver.set_option("MAX_RUNNING", "100")
    assert driver.get_option("MAX_RUNNING") == "100"
    driver.set_option("MAX_RUNNING", "0")
    assert driver.get_option("MAX_RUNNING") == "0"


def test_get_driver_name(create_driver):
    queue_config = QueueConfig(queue_system=QueueSystem.LOCAL)
    assert create_driver(queue_config).name == "LOCAL"
    queue_config = QueueConfig(queue_system=QueueSystem.SLURM)
    assert create_driver(queue_config).name == "SLURM"
    queue_config = QueueConfig(queue_system=QueueSystem.LSF)
    assert create_driver(queue_config).name == "LSF"


def test_get_slurm_queue_config(create_driver):
    queue_config = QueueConfig(
        job_script=os.path.abspath("script.sh"),
        queue_system=QueueSystem.SLURM,
        max_submit=2,
        queue_options={
            QueueSystem.SLURM: [
                ("MAX_RUNNING", "50"),
                ("SBATCH", "/path/to/sbatch"),
                ("SQUEUE", "/path/to/squeue"),
            ]
        },
    )

    assert queue_config.queue_system == QueueSystem.SLURM
    driver = create_driver(queue_config)

    assert driver.get_option("SBATCH") == "/path/to/sbatch"
    assert driver.get_option("SCONTROL") == "scontrol"
    driver.set_option("SCONTROL", "")
    assert not driver.get_option("SCONTROL")
    assert driver.name == "SLURM"
