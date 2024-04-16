import copy
import datetime
import json
import logging
import os
import os.path
import stat
from textwrap import dedent
from typing import List

import pytest

from ert.config import ErtConfig, ForwardModel
from ert.constant_filenames import JOBS_FILE
from ert.simulator.forward_model_status import ForwardModelStatus
from ert.substitution_list import SubstitutionList


@pytest.fixture()
def context():
    return SubstitutionList({"<RUNPATH>": "./"})


@pytest.fixture
def joblist():
    result = [
        {
            "name": "PERLIN",
            "executable": "perlin.py",
            "target_file": "my_target_file",
            "error_file": "error_file",
            "start_file": "some_start_file",
            "stdout": "perlin.stdout",
            "stderr": "perlin.stderr",
            "stdin": "input4thewin",
            "argList": ["-speed", "hyper"],
            "environment": {"TARGET": "flatland"},
            "max_running_minutes": 12,
        },
        {
            "name": "AGGREGATOR",
            "executable": "aggregator.py",
            "target_file": "target",
            "error_file": "None",
            "start_file": "eple",
            "stdout": "aggregator.stdout",
            "stderr": "aggregator.stderr",
            "stdin": "illgiveyousome",
            "argList": ["-o"],
            "environment": {"STATE": "awesome"},
            "max_running_minutes": 1,
        },
        {
            "name": "PI",
            "executable": "pi.py",
            "target_file": "my_target_file",
            "error_file": "error_file",
            "start_file": "some_start_file",
            "stdout": "pi.stdout",
            "stderr": "pi.stderr",
            "stdin": "input4thewin",
            "argList": ["-p", "8"],
            "environment": {"LOCATION": "earth"},
            "max_running_minutes": 12,
        },
        {
            "name": "OPTIMUS",
            "executable": "optimus.py",
            "target_file": "target",
            "error_file": "None",
            "start_file": "eple",
            "stdout": "optimus.stdout",
            "stderr": "optimus.stderr",
            "stdin": "illgiveyousome",
            "argList": ["-help"],
            "environment": {"PATH": "/ubertools/4.1"},
            "max_running_minutes": 1,
        },
    ]
    for job in result:
        job["environment"].update(ForwardModel.default_env)
    return result


forward_model_keywords = [
    "STDIN",
    "STDOUT",
    "STDERR",
    "EXECUTABLE",
    "TARGET_FILE",
    "ERROR_FILE",
    "START_FILE",
    "ARGLIST",
    "ENV",
    "MAX_RUNNING_MINUTES",
]

json_keywords = [
    "name",
    "executable",
    "target_file",
    "error_file",
    "start_file",
    "stdout",
    "stderr",
    "stdin",
    "max_running_minutes",
    "argList",
    "environment",
]


def str_none_sensitive(x):
    return str(x) if x is not None else None


DEFAULT_NAME = "default_job_name"


def _generate_job(
    name,
    executable,
    target_file,
    error_file,
    start_file,
    stdout,
    stderr,
    stdin,
    environment,
    arglist,
    max_running_minutes,
):
    config_file = DEFAULT_NAME if name is None else name

    values = [
        stdin,
        stdout,
        stderr,
        executable,
        target_file,
        error_file,
        start_file,
        None if arglist is None else " ".join(arglist),
        environment,
        str_none_sensitive(max_running_minutes),
    ]

    with open(config_file, "w", encoding="utf-8") as conf:
        for key, val in zip(forward_model_keywords, values):
            if key == "ENV" and val:
                for k, v in val.items():
                    conf.write(f"{key} {k} {v}\n")
            elif val is not None:
                conf.write(f"{key} {val}\n")

    with open(executable, "w", encoding="utf-8"):
        pass
    mode = os.stat(executable).st_mode
    mode |= stat.S_IXUSR | stat.S_IXGRP
    os.chmod(executable, stat.S_IMODE(mode))

    return ForwardModel.from_config_file(config_file, name)


def empty_list_if_none(_list):
    return [] if _list is None else _list


def default_name_if_none(name):
    return DEFAULT_NAME if name is None else name


def create_std_file(config, std="stdout", job_index=None):
    if job_index is None:
        if config[std]:
            return f"{config[std]}"
        else:
            return f'{config["name"]}.{std}'
    else:
        if config[std]:
            return f"{config[std]}.{job_index}"
        else:
            return f'{config["name"]}.{std}.{job_index}'


def validate_forward_model(forward_model, forward_model_config):
    assert forward_model.name == default_name_if_none(forward_model_config["name"])
    assert forward_model.executable == forward_model_config["executable"]
    assert forward_model.target_file == forward_model_config["target_file"]
    assert forward_model.error_file == forward_model_config["error_file"]
    assert forward_model.start_file == forward_model_config["start_file"]
    assert forward_model.stdout_file == create_std_file(
        forward_model_config, std="stdout"
    )
    assert forward_model.stderr_file == create_std_file(
        forward_model_config, std="stderr"
    )
    assert forward_model.stdin_file == forward_model_config["stdin"]
    assert (
        forward_model.max_running_minutes == forward_model_config["max_running_minutes"]
    )
    assert forward_model.arglist == empty_list_if_none(forward_model_config["argList"])
    if forward_model_config["environment"] is None:
        assert forward_model.environment == ForwardModel.default_env
    else:
        assert (
            forward_model.environment.keys()
            == forward_model_config["environment"].keys()
        )
        for key in forward_model_config["environment"]:
            assert (
                forward_model.environment[key]
                == forward_model_config["environment"][key]
            )


def generate_job_from_dict(forward_model_config):
    forward_model_config = copy.deepcopy(forward_model_config)
    forward_model_config["executable"] = os.path.join(
        os.getcwd(), forward_model_config["executable"]
    )
    forward_model = _generate_job(
        forward_model_config["name"],
        forward_model_config["executable"],
        forward_model_config["target_file"],
        forward_model_config["error_file"],
        forward_model_config["start_file"],
        forward_model_config["stdout"],
        forward_model_config["stderr"],
        forward_model_config["stdin"],
        forward_model_config["environment"],
        forward_model_config["argList"],
        forward_model_config["max_running_minutes"],
    )

    validate_forward_model(forward_model, forward_model_config)
    return forward_model


def set_up_forward_model(joblist) -> List[ForwardModel]:
    return [generate_job_from_dict(job) for job in joblist]


def verify_json_dump(joblist, config, selected_jobs, run_id):
    expected_default_env = {
        "_ERT_ITERATION_NUMBER": "0",
        "_ERT_REALIZATION_NUMBER": "0",
        "_ERT_RUNPATH": "./",
    }
    assert "config_path" in config
    assert "config_file" in config
    assert run_id == config["run_id"]
    assert len(selected_jobs) == len(config["jobList"])

    for job_index, selected_job in enumerate(selected_jobs):
        job = joblist[selected_job]
        loaded_job = config["jobList"][job_index]

        # Since no argList is loaded as an empty list by forward_model
        arg_list_back_up = job["argList"]
        job["argList"] = empty_list_if_none(job["argList"])

        # Since name is set to default if none provided by forward_model
        name_back_up = job["name"]
        job["name"] = default_name_if_none(job["name"])

        for key in json_keywords:
            if key in ["stdout", "stderr"]:
                assert (
                    create_std_file(job, std=key, job_index=job_index)
                    == loaded_job[key]
                )
            elif key == "executable":
                assert job[key] in loaded_job[key]
            elif key == "environment" and job[key] is None:
                assert loaded_job[key] == expected_default_env
            elif key == "environment" and job[key] is not None:
                for k in job[key]:
                    if k not in ForwardModel.default_env:
                        assert job[key][k] == loaded_job[key][k]
                    else:
                        assert job[key][k] == ForwardModel.default_env[k]
                        assert loaded_job[key][k] == expected_default_env[k]
            else:
                assert job[key] == loaded_job[key]

        job["argList"] = arg_list_back_up
        job["name"] = name_back_up


@pytest.mark.usefixtures("use_tmpdir")
def test_config_path_and_file(context):
    run_id = "test_config_path_and_file_in_jobs_json"

    jobs_json = ErtConfig(
        forward_model_list=set_up_forward_model([]),
        substitution_list=context,
        user_config_file="path_to_config_file/config.ert",
    ).forward_model_data_to_json(
        run_id,
    )
    assert "config_path" in jobs_json
    assert "config_file" in jobs_json
    assert jobs_json["config_path"] == "path_to_config_file"
    assert jobs_json["config_file"] == "config.ert"


@pytest.mark.usefixtures("use_tmpdir")
def test_no_jobs(context):
    run_id = "test_no_jobs_id"

    data = ErtConfig(
        forward_model_list=set_up_forward_model([]),
        substitution_list=context,
        user_config_file="path_to_config_file/config.ert",
    ).forward_model_data_to_json(
        run_id,
    )

    verify_json_dump([], data, [], run_id)


@pytest.mark.usefixtures("use_tmpdir")
def test_transfer_arg_types(context):
    with open("FWD_MODEL", "w", encoding="utf-8") as f:
        f.write("EXECUTABLE ls\n")
        f.write("MIN_ARG 2\n")
        f.write("MAX_ARG 6\n")
        f.write("ARG_TYPE 0 INT\n")
        f.write("ARG_TYPE 1 FLOAT\n")
        f.write("ARG_TYPE 2 STRING\n")
        f.write("ARG_TYPE 3 BOOL\n")
        f.write("ARG_TYPE 4 RUNTIME_FILE\n")
        f.write("ARG_TYPE 5 RUNTIME_INT\n")
        f.write("ENV KEY1 VALUE2\n")
        f.write("ENV KEY2 VALUE2\n")

    job = ForwardModel.from_config_file("FWD_MODEL")
    run_id = "test_no_jobs_id"

    config = ErtConfig(
        forward_model_list=[job], substitution_list=context
    ).forward_model_data_to_json(run_id)

    printed_job = config["jobList"][0]
    assert printed_job["min_arg"] == 2
    assert printed_job["max_arg"] == 6
    assert printed_job["arg_types"] == [
        "INT",
        "FLOAT",
        "STRING",
        "BOOL",
        "RUNTIME_FILE",
        "RUNTIME_INT",
    ]


@pytest.mark.usefixtures("use_tmpdir")
def test_one_job(joblist, context):
    for i, job in enumerate(joblist):
        run_id = "test_one_job"

        data = ErtConfig(
            forward_model_list=set_up_forward_model([job]),
            substitution_list=context,
        ).forward_model_data_to_json(run_id)
        verify_json_dump(joblist, data, [i], run_id)


def run_all(joblist, context):
    run_id = "run_all"
    data = ErtConfig(
        forward_model_list=set_up_forward_model(joblist),
        substitution_list=context,
    ).forward_model_data_to_json(run_id)

    verify_json_dump(joblist, data, range(len(joblist)), run_id)


@pytest.mark.usefixtures("use_tmpdir")
def test_all_jobs(joblist, context):
    run_all(joblist, context)


@pytest.mark.usefixtures("use_tmpdir")
def test_various_null_fields(joblist, context):
    for key in [
        "target_file",
        "error_file",
        "start_file",
        "stdout",
        "stderr",
        "max_running_minutes",
        "argList",
        "environment",
        "stdin",
    ]:
        joblist[0][key] = None
        run_all(joblist, context)


@pytest.mark.usefixtures("use_tmpdir")
def test_status_file(joblist, context):
    run_id = "test_no_jobs_id"
    with open(JOBS_FILE, "w", encoding="utf-8") as fp:
        json.dump(
            ErtConfig(
                forward_model_list=set_up_forward_model(joblist),
                substitution_list=context,
            ).forward_model_data_to_json(run_id),
            fp,
        )

    with open("status.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "start_time": None,
                "jobs": [
                    {
                        "status": "Success",
                        "start_time": 1519653419.0,
                        "end_time": 1519653419.0,
                        "name": "SQUARE_PARAMS",
                        "error": None,
                        "current_memory_usage": 2000,
                        "max_memory_usage": 3000,
                    }
                ],
                "end_time": None,
                "run_id": "",
            },
            f,
        )

    status = ForwardModelStatus.try_load("")
    for job in status.jobs:
        assert isinstance(job.start_time, datetime.datetime)
        assert isinstance(job.end_time, datetime.datetime)


@pytest.mark.usefixtures("use_tmpdir")
def test_that_values_with_brackets_are_ommitted(caplog, joblist, context):
    forward_model_list: List[ForwardModel] = set_up_forward_model(joblist)
    forward_model_list[0].environment["ENV_VAR"] = "<SOME_BRACKETS>"
    run_id = "test_no_jobs_id"

    data = ErtConfig(
        forward_model_list=forward_model_list, substitution_list=context
    ).forward_model_data_to_json(run_id)

    assert "Environment variable ENV_VAR skipped due to" in caplog.text
    assert "ENV_VAR" not in data["jobList"][0]["environment"]


@pytest.mark.usefixtures("use_tmpdir")
@pytest.mark.parametrize(
    "job, forward_model, expected_args",
    [
        pytest.param(
            dedent(
                """
            EXECUTABLE echo
            ARGLIST WORD_A
            """
            ),
            "FORWARD_MODEL job_name",
            ["WORD_A"],
            id="No argument",
        ),
        pytest.param(
            dedent(
                """
            EXECUTABLE echo
            ARGLIST <ARGUMENTA>
            """
            ),
            dedent(
                """
            DEFINE <ARGUMENTA> foo
            FORWARD_MODEL job_name
            """
            ),
            ["foo"],
            id="Global arguments are used inside job definition",
        ),
        pytest.param(
            dedent(
                """
            EXECUTABLE echo
            ARGLIST <ARGUMENT>
            """
            ),
            "FORWARD_MODEL job_name(<ARGUMENT>=yy)",
            ["yy"],
            id="With argument",
        ),
        pytest.param(
            dedent(
                """
            EXECUTABLE echo
            DEFAULT <ARGUMENTA> DEFAULT_ARGA_VALUE
            ARGLIST <ARGUMENTA> <ARGUMENTB> <ARGUMENTC>
                """
            ),
            "DEFINE <TO_BE_DEFINED> <ARGUMENTB>\n"
            "FORWARD_MODEL job_name(<ARGUMENTA>=configured_argumentA,"
            " <TO_BE_DEFINED>=configured_argumentB)",
            [
                "configured_argumentA",
                "<ARGUMENTB>",
                "<ARGUMENTC>",
            ],
            id="Keywords in argument list are not substituted, "
            "so argument B gets no value",
        ),
        pytest.param(
            dedent(
                """
            EXECUTABLE echo
            DEFAULT <ARGUMENTA> DEFAULT_ARGA_VALUE
            ARGLIST <ARGUMENTA> <ARGUMENTB> <ARGUMENTC>
                """
            ),
            dedent(
                """
            DEFINE <ARGUMENTB> DEFINED_ARGUMENTB_VALUE
            FORWARD_MODEL job_name(<ARGUMENTB>=configured_argumentB)
            """
            ),
            ["DEFAULT_ARGA_VALUE", "configured_argumentB", "<ARGUMENTC>"],
            id="Resolved argument given by argument list, not overridden by global",
        ),
        pytest.param(
            dedent(
                """
            EXECUTABLE echo
            DEFAULT <ARGUMENTA> DEFAULT_ARGA_VALUE
            ARGLIST <ARGUMENTA> <ARGUMENTB> <ARGUMENTC>
            """
            ),
            "FORWARD_MODEL job_name()",
            ["DEFAULT_ARGA_VALUE", "<ARGUMENTB>", "<ARGUMENTC>"],
            id="No args, parenthesis, gives default argument A",
        ),
        pytest.param(
            dedent(
                """
            EXECUTABLE echo
            DEFAULT <ARGUMENTA> DEFAULT_ARGA_VALUE
            ARGLIST <ARGUMENTA> <ARGUMENTB> <ARGUMENTC>
            """
            ),
            "FORWARD_MODEL job_name",
            ["DEFAULT_ARGA_VALUE", "<ARGUMENTB>", "<ARGUMENTC>"],
            id="No args, gives default argument A",
        ),
        pytest.param(
            dedent(
                """
            EXECUTABLE echo
            ARGLIST <ITER>
            """
            ),
            "FORWARD_MODEL job_name(<ITER>=<ITER>)",
            ["0"],
            id="This style of args works without infinite substitution loop.",
        ),
        pytest.param(
            dedent(
                """
            EXECUTABLE echo
            ARGLIST <ECLBASE>
            """
            ),
            "FORWARD_MODEL job_name(<ECLBASE>=A/<ECLBASE>)",
            ["A/ECLBASE0"],
            id="The NOSIM job takes <ECLBASE> as args. Expect no infinite loop.",
        ),
    ],
)
def test_forward_model_job(job, forward_model, expected_args):
    with open("job_file", "w", encoding="utf-8") as fout:
        fout.write(job)

    with open("config_file.ert", "w", encoding="utf-8") as fout:
        # Write a minimal config file
        fout.write(
            dedent(
                """
        NUM_REALIZATIONS 1
        """
            )
        )
        fout.write("INSTALL_JOB job_name job_file\n")
        fout.write(forward_model)

    ert_config = ErtConfig.from_file("config_file.ert")

    forward_model = ert_config.forward_model_list
    assert len(forward_model) == 1
    assert (
        ert_config.forward_model_data_to_json(
            "",
            0,
            0,
        )["jobList"][0]["argList"]
        == expected_args
    )


@pytest.mark.usefixtures("use_tmpdir")
def test_that_config_path_is_the_directory_of_the_main_ert_config():
    os.mkdir("jobdir")
    with open("jobdir/job_file", "w", encoding="utf-8") as fout:
        fout.write(
            dedent(
                """
            EXECUTABLE echo
            ARGLIST <CONFIG_PATH>
            """
            )
        )

    with open("config_file.ert", "w", encoding="utf-8") as fout:
        # Write a minimal config file
        fout.write("NUM_REALIZATIONS 1\n")
        fout.write("INSTALL_JOB job_name jobdir/job_file\n")
        fout.write("FORWARD_MODEL job_name")

    ert_config = ErtConfig.from_file("config_file.ert")

    assert ert_config.forward_model_data_to_json(
        "",
        0,
        0,
    )["jobList"][0]["argList"] == [os.getcwd()]


@pytest.mark.usefixtures("use_tmpdir")
@pytest.mark.parametrize(
    "job, forward_model, expected_args",
    [
        pytest.param(
            dedent(
                """
            EXECUTABLE echo
            MIN_ARG    1
            MAX_ARG    6
            ARG_TYPE 0 STRING
            ARG_TYPE 1 BOOL
            ARG_TYPE 2 FLOAT
            ARG_TYPE 3 INT
            """
            ),
            "SIMULATION_JOB job_name Hello True 3.14 4",
            ["Hello", "True", "3.14", "4"],
            id="Not all args",
        ),
        pytest.param(
            dedent(
                """
            EXECUTABLE echo
            MIN_ARG    1
            MAX_ARG    2
            ARG_TYPE 0 STRING
            ARG_TYPE 0 STRING
                    """
            ),
            "SIMULATION_JOB job_name word <E42>",
            ["word", "<E42>"],
            id="Some args",
        ),
        pytest.param(
            dedent(
                """
            EXECUTABLE echo
            MIN_ARG    1
            MAX_ARG    2
            ARG_TYPE 0 STRING
            ARG_TYPE 0 STRING
            ARGLIST <ARGUMENTA> <ARGUMENTB>
                    """
            ),
            "SIMULATION_JOB job_name arga argb",
            ["arga", "argb"],
            id="simulation job with arglist",
        ),
    ],
)
def test_simulation_job(job, forward_model, expected_args):
    with open("job_file", "w", encoding="utf-8") as fout:
        fout.write(job)

    with open("config_file.ert", "w", encoding="utf-8") as fout:
        # Write a minimal config file
        fout.write("NUM_REALIZATIONS 1\n")
        fout.write("INSTALL_JOB job_name job_file\n")
        fout.write(forward_model)

    ert_config = ErtConfig.from_file("config_file.ert")
    assert len(ert_config.forward_model_list) == 1
    job_data = ert_config.forward_model_data_to_json(
        "",
        0,
        0,
    )["jobList"][0]
    assert job_data["argList"] == expected_args


@pytest.mark.usefixtures("use_tmpdir")
def test_that_private_over_global_args_gives_logging_message(caplog):
    caplog.set_level(logging.INFO)
    with open("job_file", "w", encoding="utf-8") as fout:
        fout.write(
            dedent(
                """
            EXECUTABLE echo
            ARGLIST <ARG>
            ARG_TYPE 0 STRING
            """
            )
        )

    with open("config_file.ert", "w", encoding="utf-8") as fout:
        # Write a minimal config file
        fout.write("NUM_REALIZATIONS 1\n")
        fout.write("DEFINE <ARG> A\n")
        fout.write("INSTALL_JOB job_name job_file\n")
        fout.write("FORWARD_MODEL job_name(<ARG>=B)")

    ert_config = ErtConfig.from_file("config_file.ert")
    job_data = ert_config.forward_model_data_to_json("", 0, 0)["jobList"][0]
    assert len(ert_config.forward_model_list) == 1
    assert job_data["argList"] == ["B"]
    assert "Private arg '<ARG>':'B' chosen over global 'A'" in caplog.text


@pytest.mark.usefixtures("use_tmpdir")
def test_that_private_over_global_args_does_not_give_logging_message_for_argpassing(
    caplog,
):
    caplog.set_level(logging.INFO)
    with open("job_file", "w", encoding="utf-8") as fout:
        fout.write(
            dedent(
                """
            EXECUTABLE echo
            ARGLIST <ARG>
            ARG_TYPE 0 STRING
            """
            )
        )

    with open("config_file.ert", "w", encoding="utf-8") as fout:
        # Write a minimal config file
        fout.write("NUM_REALIZATIONS 1\n")
        fout.write("DEFINE <ARG> A\n")
        fout.write("INSTALL_JOB job_name job_file\n")
        fout.write("FORWARD_MODEL job_name(<ARG>=<ARG>)")

    ert_config = ErtConfig.from_file("config_file.ert")

    job_data = ert_config.forward_model_data_to_json("", 0, 0)["jobList"][0]
    assert len(ert_config.forward_model_list) == 1
    assert job_data["argList"] == ["A"]
    assert "Private arg '<ARG>':'<ARG>' chosen over global 'A'" not in caplog.text


@pytest.mark.usefixtures("use_tmpdir")
@pytest.mark.parametrize(
    "job, forward_model, expected_args",
    [
        pytest.param(
            dedent(
                """
            EXECUTABLE echo
            ARGLIST <ARG>
            """
            ),
            "DEFINE <ENV> $ENV\nFORWARD_MODEL job_name(<ARG>=<ENV>)",
            ["env_value"],
            id="Test that the environment variable $ENV is put into the forward model",
        ),
    ],
)
def test_that_environment_variables_are_set_in_forward_model(
    monkeypatch, job, forward_model, expected_args
):
    monkeypatch.setenv("ENV", "env_value")
    with open("job_file", "w", encoding="utf-8") as fout:
        fout.write(job)

    with open("config_file.ert", "w", encoding="utf-8") as fout:
        # Write a minimal config file
        fout.write(
            dedent(
                """
        NUM_REALIZATIONS 1
        """
            )
        )
        fout.write("INSTALL_JOB job_name job_file\n")
        fout.write(forward_model)

    ert_config = ErtConfig.from_file("config_file.ert")

    forward_model_list = ert_config.forward_model_list
    assert len(forward_model_list) == 1
    assert (
        ert_config.forward_model_data_to_json(
            "",
            0,
            0,
        )["jobList"][0]["argList"]
        == expected_args
    )
