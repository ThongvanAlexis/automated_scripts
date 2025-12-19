
import os
import time

def get_last_run_time_path(script_name, report_folder):
    return os.path.join(report_folder, f"{script_name}_last_exe_time.txt")

def write_last_run_time(script_name, report_folder):
    """
    call this at the end of each script
    """
    with open(get_last_run_time_path(script_name, report_folder), "w") as f:
        f.write(str(time.time()))

def is_time_to_run(script_name, report_folder, delay_between_run_in_seconds):
    """
    Call this at the beginning of each script (before write_last_run_time)
    if false, do not run
    """
    filename = get_last_run_time_path(script_name, report_folder)
    if not os.path.exists(filename):
        return True

    current_time = time.time()
    with open(filename, "r") as f:
        last_exe_time = float(f.read())
    return (current_time - last_exe_time) > delay_between_run_in_seconds