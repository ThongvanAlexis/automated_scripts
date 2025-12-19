import os
import sys
import subprocess
import datetime
from typing import List, Tuple, Optional

AUTOSCRIPTS_DIRNAME = "autoscripts"
ORCHESTRATOR_LOGS_DIRNAME = "orchestrator_logs"

SKIP_PYTHON_BASENAMES_SET = {
    "__init__.py",
    "common.py",
    "secret_manager.py",
    "secret_manager_local.py",
}

SCRIPT_TIMEOUT_SECS = 55 * 60  # keep under 1 hour to avoid overlapping scheduled runs

def now_timestamp_for_filename() -> str:
    # Windows-safe timestamp (no ":" characters)
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def ensure_dir_exists(dir_path: str) -> None:
    os.makedirs(dir_path, exist_ok=True)

def list_python_file_paths_in_dir(autoscripts_dir: str) -> List[str]:
    """
    Returns absolute file paths of all .py files directly inside autoscripts_dir
    (non-recursive), excluding SKIP_PYTHON_BASENAMES_SET.
    Uses os.scandir for speed.
    """
    python_file_paths: List[str] = []

    try:
        with os.scandir(autoscripts_dir) as entries:
            for entry in entries:
                entry_name = entry.name

                if not entry.is_file(follow_symlinks=False):
                    continue

                if not entry_name.lower().endswith(".py"):
                    continue

                if entry_name in SKIP_PYTHON_BASENAMES_SET:
                    continue

                python_file_paths.append(entry.path)
    except PermissionError as exc:
        raise PermissionError(f"Permission denied while scanning: {autoscripts_dir}") from exc

    python_file_paths.sort(key=lambda path: os.path.basename(path).lower())
    return python_file_paths

def write_text_file(file_path: str, lines: List[str]) -> None:
    with open(file_path, "w", encoding="utf-8") as file:
        for line in lines:
            file.write(line)
            if not line.endswith("\n"):
                file.write("\n")

def append_text_file(file_path: str, lines: List[str]) -> None:
    with open(file_path, "a", encoding="utf-8") as file:
        for line in lines:
            file.write(line)
            if not line.endswith("\n"):
                file.write("\n")

def run_script(
    script_abs_path: str,
    autoscripts_root_dir: str,
    logs_dir: str,
) -> Tuple[int, Optional[str], Optional[str], float]:
    """
    Runs one script as a subprocess.
    Returns: (return_code, stdout_log_path, stderr_log_path, duration_secs)
    """
    script_basename = os.path.basename(script_abs_path)
    script_stem = os.path.splitext(script_basename)[0]

    stdout_log_path = os.path.join(logs_dir, f"{script_stem}.stdout.txt")
    stderr_log_path = os.path.join(logs_dir, f"{script_stem}.stderr.txt")

    command_args = [sys.executable, script_abs_path]

    start_time = datetime.datetime.now()
    try:
        process = subprocess.run(
            command_args,
            cwd=autoscripts_root_dir,  # important: keeps ./reports working
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=SCRIPT_TIMEOUT_SECS,
        )
        duration_secs = (datetime.datetime.now() - start_time).total_seconds()

        write_text_file(stdout_log_path, [process.stdout or ""])
        write_text_file(stderr_log_path, [process.stderr or ""])

        return process.returncode, stdout_log_path, stderr_log_path, duration_secs

    except subprocess.TimeoutExpired as exc:
        duration_secs = (datetime.datetime.now() - start_time).total_seconds()
        write_text_file(stdout_log_path, [(exc.stdout or ""), "\n[orchestrator] TIMEOUT\n"])
        write_text_file(stderr_log_path, [(exc.stderr or ""), "\n[orchestrator] TIMEOUT\n"])
        return 124, stdout_log_path, stderr_log_path, duration_secs

    except Exception as exc:
        duration_secs = (datetime.datetime.now() - start_time).total_seconds()
        write_text_file(stdout_log_path, [""])
        write_text_file(stderr_log_path, [f"[orchestrator] Exception while running {script_abs_path}: {exc}"])
        return 125, stdout_log_path, stderr_log_path, duration_secs

def main() -> int:
    orchestrator_dir = os.path.dirname(os.path.abspath(__file__))
    autoscripts_root_dir = os.path.join(orchestrator_dir, AUTOSCRIPTS_DIRNAME)

    if not os.path.isdir(autoscripts_root_dir):
        raise RuntimeError(f"autoscripts folder not found: {autoscripts_root_dir}")

    logs_root_dir = os.path.join(orchestrator_dir, ORCHESTRATOR_LOGS_DIRNAME)
    ensure_dir_exists(logs_root_dir)

    run_timestamp = now_timestamp_for_filename()
    run_logs_dir = os.path.join(logs_root_dir, run_timestamp)
    ensure_dir_exists(run_logs_dir)

    orchestrator_run_log_path = os.path.join(run_logs_dir, "orchestrator_run_log.txt")
    last_summary_path = os.path.join(logs_root_dir, "last_run_summary.txt")

    python_file_paths = list_python_file_paths_in_dir(autoscripts_root_dir)

    header_lines = [
        f"Orchestrator started: {run_timestamp}",
        f"Python executable: {sys.executable}",
        f"autoscripts root: {autoscripts_root_dir}",
        f"Found scripts: {len(python_file_paths)}",
        "",
        "Scripts to run (in order):",
    ]
    for script_path in python_file_paths:
        header_lines.append(f" - {os.path.basename(script_path)}")
    header_lines.append("")

    write_text_file(orchestrator_run_log_path, header_lines)

    any_failures = False
    results_lines: List[str] = ["Results:"]

    for script_abs_path in python_file_paths:
        script_basename = os.path.basename(script_abs_path)
        append_text_file(orchestrator_run_log_path, [f"== Running: {script_basename} =="])

        return_code, stdout_log_path, stderr_log_path, duration_secs = run_script(
            script_abs_path=script_abs_path,
            autoscripts_root_dir=autoscripts_root_dir,
            logs_dir=run_logs_dir,
        )

        status = "OK" if return_code == 0 else "FAILED"
        if return_code != 0:
            any_failures = True

        result_line = (
            f"{status} rc={return_code} duration={duration_secs:.2f}s "
            f"script={script_basename} "
            f"stdout={os.path.basename(stdout_log_path)} "
            f"stderr={os.path.basename(stderr_log_path)}"
        )

        append_text_file(orchestrator_run_log_path, [result_line, ""])
        results_lines.append(result_line)

    footer_lines = [
        "",
        f"Orchestrator finished: {now_timestamp_for_filename()}",
        f"Overall status: {'FAILED' if any_failures else 'OK'}",
        f"Run log: {orchestrator_run_log_path}",
    ]
    append_text_file(orchestrator_run_log_path, footer_lines)

    summary_lines = header_lines + results_lines + footer_lines
    write_text_file(last_summary_path, summary_lines)

    return 1 if any_failures else 0

if __name__ == "__main__":
    try:
        exit_code = main()
        raise SystemExit(exit_code)
    except Exception as exc:
        orchestrator_dir = os.path.dirname(os.path.abspath(__file__))
        logs_root_dir = os.path.join(orchestrator_dir, ORCHESTRATOR_LOGS_DIRNAME)
        ensure_dir_exists(logs_root_dir)

        crash_timestamp = now_timestamp_for_filename()
        crash_log_path = os.path.join(logs_root_dir, f"orchestrator_crash_{crash_timestamp}.txt")
        write_text_file(crash_log_path, [f"Orchestrator crashed: {exc}"])
        raise