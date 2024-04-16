import fileinput
import importlib
import json
import logging
import os
import resource
import shutil
import stat
import sys
from argparse import ArgumentParser
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock

from _ert.threading import set_signal_handler

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from qtpy.QtCore import QDir

from _ert.async_utils import get_running_loop
from ert.__main__ import ert_parser
from ert.cli import ENSEMBLE_EXPERIMENT_MODE
from ert.cli.main import run_cli
from ert.config import ErtConfig
from ert.ensemble_evaluator.config import EvaluatorServerConfig
from ert.services import StorageService
from ert.shared.feature_toggling import FeatureScheduler
from ert.storage import open_storage

from .utils import SOURCE_DIR

st.register_type_strategy(Path, st.builds(Path, st.text().map(lambda x: "/tmp/" + x)))


@pytest.fixture(autouse=True)
def log_check():
    logger = logging.getLogger()
    logger.setLevel(logging.WARNING)
    yield
    logger_after = logging.getLogger()
    level_after = logger_after.getEffectiveLevel()
    assert (
        level_after == logging.WARNING
    ), f"Detected differences in log environment: Changed to {level_after}"


@pytest.fixture(scope="session", autouse=True)
def _reraise_thread_exceptions_on_main_thread():
    """Allow `ert.shared.threading.ErtThread` to re-raise exceptions on main thread"""
    set_signal_handler()


# Timeout settings are unreliable both on CI and
# when running pytest with xdist so we disable it
settings.register_profile(
    "no_timeouts",
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
    print_blob=True,
)
settings.load_profile("no_timeouts")


@pytest.fixture()
def set_site_config(monkeypatch, tmp_path):
    test_site_config = tmp_path / "test_site_config.ert"
    test_site_config.write_text("JOB_SCRIPT job_dispatch.py\nQUEUE_SYSTEM LOCAL\n")
    monkeypatch.setenv("ERT_SITE_CONFIG", str(test_site_config))


@pytest.fixture(scope="session", name="source_root")
def fixture_source_root():
    return SOURCE_DIR


@pytest.fixture(scope="class")
def class_source_root(request, source_root):
    request.cls.SOURCE_ROOT = source_root
    request.cls.TESTDATA_ROOT = source_root / "test-data"
    request.cls.SHARE_ROOT = str(
        Path(importlib.util.find_spec("ert.shared").origin).parent / "share"
    )
    yield


@pytest.fixture(autouse=True)
def env_save():
    exceptions = [
        "PYTEST_CURRENT_TEST",
        "KMP_DUPLICATE_LIB_OK",
        "KMP_INIT_AT_FORK",
        "QT_API",
    ]
    environment_pre = [
        (key, val) for key, val in os.environ.items() if key not in exceptions
    ]
    yield
    environment_post = [
        (key, val) for key, val in os.environ.items() if key not in exceptions
    ]
    set_xor = set(environment_pre).symmetric_difference(set(environment_post))
    assert len(set_xor) == 0, f"Detected differences in environment: {set_xor}"


@pytest.fixture(scope="session", autouse=True)
def maximize_ulimits():
    """
    Bumps the soft-limit for max number of files up to its max-value
    since we know that the tests may open lots of files simultaneously.
    Resets to original when session ends.
    """
    limits = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (limits[1], limits[1]))
    yield
    resource.setrlimit(resource.RLIMIT_NOFILE, limits)


@pytest.fixture(name="setup_case")
def fixture_setup_case(tmp_path_factory, source_root, monkeypatch):
    def copy_case(path, config_file):
        tmp_path = tmp_path_factory.mktemp(path.replace("/", "-"))
        shutil.copytree(
            os.path.join(source_root, "test-data", path), tmp_path / "test_data"
        )
        monkeypatch.chdir(tmp_path / "test_data")
        return ErtConfig.from_file(config_file)

    yield copy_case


@pytest.fixture()
def poly_case(setup_case):
    return setup_case("poly_example", "poly.ert")


@pytest.fixture()
def snake_oil_case_storage(copy_snake_oil_case_storage):
    return ErtConfig.from_file("snake_oil.ert")


@pytest.fixture()
def snake_oil_case(setup_case):
    return setup_case("snake_oil", "snake_oil.ert")


@pytest.fixture()
def minimum_case(use_tmpdir):
    with open("minimum_config", "w", encoding="utf-8") as fout:
        fout.write(
            "NUM_REALIZATIONS 10\nQUEUE_OPTION LOCAL MAX_RUNNING 50\nMAX_RUNTIME 42"
        )
    return ErtConfig.from_file("minimum_config")


@pytest.fixture(name="copy_case")
def fixture_copy_case(tmp_path_factory, source_root, monkeypatch):
    def _copy_case(path):
        tmp_path = tmp_path_factory.mktemp(path.replace("/", "-"))
        shutil.copytree(
            os.path.join(source_root, "test-data", path),
            tmp_path / "test_data",
            ignore=shutil.ignore_patterns("storage"),
        )
        monkeypatch.chdir(tmp_path / "test_data")

    yield _copy_case


@pytest.fixture()
def copy_poly_case(copy_case):
    copy_case("poly_example")


@pytest.fixture()
def copy_snake_oil_field(copy_case):
    copy_case("snake_oil_field")


@pytest.fixture()
def copy_snake_oil_case(copy_case):
    copy_case("snake_oil")


@pytest.fixture(
    name="copy_snake_oil_case_storage",
    params=[
        pytest.param(0, marks=pytest.mark.xdist_group(name="snake_oil_case_storage"))
    ],
)
def fixture_copy_snake_oil_case_storage(_shared_snake_oil_case, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shutil.copytree(_shared_snake_oil_case, "test_data")
    monkeypatch.chdir("test_data")


@pytest.fixture()
def copy_minimum_case(copy_case):
    copy_case("simple_config")


@pytest.fixture()
def use_tmpdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def mock_start_server(monkeypatch):
    start_server = MagicMock()
    monkeypatch.setattr(StorageService, "start_server", start_server)
    yield start_server


@pytest.fixture()
def mock_connect(monkeypatch):
    connect = MagicMock()
    monkeypatch.setattr(StorageService, "connect", connect)
    yield connect


@pytest.fixture(scope="session", autouse=True)
def hide_window(request):
    if request.config.getoption("--show-gui"):
        yield
        return

    old_value = os.environ.get("QT_QPA_PLATFORM")
    if sys.platform == "darwin":
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    else:
        os.environ["QT_QPA_PLATFORM"] = "minimal"
    yield
    if old_value is None:
        del os.environ["QT_QPA_PLATFORM"]
    else:
        os.environ["QT_QPA_PLATFORM"] = old_value


def pytest_addoption(parser):
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )
    parser.addoption(
        "--eclipse-simulator",
        action="store_true",
        default=False,
        help="Defaults to not running tests that require eclipse.",
    )
    parser.addoption(
        "--openpbs",
        action="store_true",
        default=False,
        help="Run OpenPBS tests against the real cluster",
    )
    parser.addoption(
        "--lsf",
        action="store_true",
        default=False,
        help="Run LSF tests against the real cluster.",
    )
    parser.addoption("--show-gui", action="store_true", default=False)


@pytest.fixture(
    params=[
        pytest.param(False, id="using_job_queue"),
        pytest.param(True, id="using_scheduler"),
    ]
)
def using_scheduler(request, monkeypatch):
    should_enable_scheduler = request.param
    if should_enable_scheduler:
        # Flaky - the new scheduler needs an event loop, which might not be initialized yet.
        #  This might be a bug in python 3.8, but it does not occur locally.
        _ = get_running_loop()

    monkeypatch.setenv("ERT_FEATURE_SCHEDULER", "1" if should_enable_scheduler else "0")
    monkeypatch.setattr(FeatureScheduler, "_value", should_enable_scheduler)
    yield should_enable_scheduler


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        # --runslow given in cli: do not skip slow tests
        skip_quick = pytest.mark.skip(
            reason="skipping quick performance tests on --runslow"
        )
        for item in items:
            if "quick_only" in item.keywords:
                item.add_marker(skip_quick)
            if item.get_closest_marker("requires_eclipse") and not config.getoption(
                "--eclipse_simulator"
            ):
                item.add_marker(pytest.mark.skip("Requires eclipse"))

    else:
        skip_slow = pytest.mark.skip(reason="need --runslow option to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
            if item.get_closest_marker("requires_eclipse") and not config.getoption(
                "--eclipse-simulator"
            ):
                item.add_marker(pytest.mark.skip("Requires eclipse"))


def _run_snake_oil(source_root):
    shutil.copytree(os.path.join(source_root, "test-data", "snake_oil"), "test_data")
    os.chdir("test_data")
    with fileinput.input("snake_oil.ert", inplace=True) as fin:
        for line in fin:
            if "NUM_REALIZATIONS 25" in line:
                print("NUM_REALIZATIONS 5", end="")
            else:
                print(line, end="")

    parser = ArgumentParser(prog="test_main")
    parsed = ert_parser(
        parser,
        [
            ENSEMBLE_EXPERIMENT_MODE,
            "--disable-monitor",
            "--current-case",
            "default_0",
            "snake_oil.ert",
        ],
    )

    run_cli(parsed)


@pytest.fixture
def _shared_snake_oil_case(request, monkeypatch, source_root):
    """This fixture will run the snake_oil case to populate storage,
    this is quite slow, but the results will be cached. If something comes
    out of sync, clear the cache and start again.
    """
    snake_path = request.config.cache.mkdir(
        "snake_oil_data" + os.environ.get("PYTEST_XDIST_WORKER", "")
    )
    monkeypatch.chdir(snake_path)
    if not os.listdir(snake_path):
        _run_snake_oil(source_root)
    else:
        monkeypatch.chdir("test_data")

    yield os.getcwd()


@pytest.fixture
def storage(tmp_path):
    with open_storage(tmp_path / "storage", mode="w") as storage:
        yield storage


@pytest.fixture
def new_ensemble(storage):
    experiment_id = storage.create_experiment()
    return storage.create_ensemble(
        experiment_id, name="new_ensemble", ensemble_size=100
    )


@pytest.fixture
def snake_oil_storage(snake_oil_case_storage):
    with open_storage(snake_oil_case_storage.ens_path, mode="w") as storage:
        yield storage


@pytest.fixture
def snake_oil_default_storage(snake_oil_case_storage):
    with open_storage(snake_oil_case_storage.ens_path) as storage:
        yield storage.get_ensemble_by_name("default_0")


@pytest.fixture(scope="session")
def block_storage_path(source_root):
    path = source_root / "test-data/block_storage/snake_oil"
    if not path.is_dir():
        pytest.skip(
            "'test-data/block_storage' has not been checked out.\n"
            "Run: git submodule update --init --recursive"
        )
    return path.parent


@pytest.fixture(autouse=True)
def no_cert_in_test(monkeypatch):
    # Do not generate certificates during test, parts of it can be time
    # consuming (e.g. 30 seconds)
    # Specifically generating the RSA key <_openssl.RSA_generate_key_ex>
    class MockESConfig(EvaluatorServerConfig):
        def __init__(self, *args, **kwargs):
            if "use_token" not in kwargs:
                kwargs["use_token"] = False
            if "generate_cert" not in kwargs:
                kwargs["generate_cert"] = False
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("ert.cli.main.EvaluatorServerConfig", MockESConfig)


QSTAT_HEADER = (
    "Job id                         Name            User             Time Use S Queue\n"
    "-----------------------------  --------------- ---------------  -------- - ---------------\n"
)
QSTAT_HEADER_FORMAT = "%-30s %-15s %-15s %-8s %-1s %-5s"


@pytest.fixture
def create_mock_flaky_qstat(monkeypatch, tmp_path):
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    monkeypatch.chdir(bin_path)
    monkeypatch.setenv("PATH", f"{bin_path}:{os.environ['PATH']}")
    yield _mock_flaky_qstat


def _mock_flaky_qstat(error_message_to_output: str):
    qsub_path = Path("qsub")
    qsub_path.write_text("#!/bin/sh\necho '1'")
    qsub_path.chmod(qsub_path.stat().st_mode | stat.S_IEXEC)
    qstat_path = Path("qstat")
    qstat_path.write_text(
        "#!/bin/sh"
        + dedent(
            f"""
            count=0
            if [ -f counter_file ]; then
                count=$(cat counter_file)
            fi
            echo "$((count+1))" > counter_file
            if [ $count -ge 3 ]; then
                json_flag_set=false;
                while [ "$#" -gt 0 ]; do
                    case "$1" in
                        -Fjson)
                            json_flag_set=true
                            ;;
                    esac
                    shift
                done
                if [ "$json_flag_set" = true ]; then
                    echo '{json.dumps({"Jobs": {"1": {"Job_Name": "1", "job_state": "E", "Exit_status": "0"}}})}'
                else
                    echo "{QSTAT_HEADER}"; printf "{QSTAT_HEADER_FORMAT}" 1 foo someuser 0 E normal
                fi
            else
                echo "{error_message_to_output}" >&2
                exit 2
            fi
        """
        )
    )
    qstat_path.chmod(qstat_path.stat().st_mode | stat.S_IEXEC)
