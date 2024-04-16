import importlib
import os
from pathlib import Path


def extract_executable(filename):
    with open(filename, "r", encoding="utf-8") as filehandle:
        for line in filehandle.readlines():
            splitline = line.strip().split()
            if len(splitline) > 1 and splitline[0] == "EXECUTABLE":
                return splitline[1]
    return None


def file_exist_and_is_executable(file_path):
    return os.path.isfile(file_path) and os.access(file_path, os.X_OK)


def test_validate_scripts():
    fm_path = (
        Path(importlib.util.find_spec("ert.shared").origin).parent
        / "share/ert/forward-models"
    )
    for fm_dir in os.listdir(fm_path):
        fm_dir = os.path.join(fm_path, fm_dir)
        # get all sub-folder in forward-models
        if os.path.isdir(fm_dir):
            files = os.listdir(fm_dir)
            for fn in files:
                fn = os.path.join(fm_dir, fn)
                # get all files in sub-folders
                if os.path.isfile(fn):
                    # extract executable (if any)
                    executable_script = extract_executable(fn)
                    if executable_script is not None:
                        assert file_exist_and_is_executable(
                            os.path.join(fm_dir, executable_script)
                        )
