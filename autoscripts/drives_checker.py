import os
import subprocess
import json
import traceback
import requests

from common import is_time_to_run, write_last_run_time

try:
    # this one is ignored so that I don't push my implementation
    from secret_manager_local import get_secret
except ImportError:
    # this one is a stub to show what needs to be done
    from secret_manager import get_secret

"""
python Python3.11.3

Requires :
  smartctl.exe installed (on windows), get it here : https://www.smartmontools.org/

checks all drives on the computer
  - write a report
  - send a mail if there is an issue

you need to implement get_secret() in common.py, or put the password in clear in you script, it's your call
"""

SEND_MAIL = True

ONE_DAY_IN_SECS = 24*60*60
SCRIPT_NAME = "drive_smart_scanner"
REPORT_DIR = "./reports"
REPORT_BASENAME = "drive_smart_scanner_report.txt"
ERROR_LOG_BASENAME = "drive_smart_scanner_error_log.txt"
REPORT_PATH = os.path.join(REPORT_DIR, REPORT_BASENAME)
ERROR_LOG_PATH = os.path.join(REPORT_DIR, ERROR_LOG_BASENAME)

SMARTCTL_COMMAND = "smartctl"

MAILGUN_API_KEY = None
MAILGUN_DOMAIN = None
MAILGUN_FROM = None
MAILGUN_TO = None

SMART_ATA_TABLE_COLUMNS = [
    ("ID", 5),
    ("Attribute name", 28),
    ("Current", 10),
    ("Worst", 7),
    ("Threshold", 10),
    ("Raw Values", 20),
]

SMART_NVME_TABLE_COLUMNS = [
    ("Attribute name", 28),
    ("value", 10),
]

def init_mail_settings():
    """
    so that an exception is not raised before being in main
    """
    global MAILGUN_API_KEY, MAILGUN_DOMAIN, MAILGUN_FROM, MAILGUN_TO
    MAILGUN_API_KEY = get_secret("mailgun_api_secret")
    MAILGUN_DOMAIN = get_secret("mailgun_domain")
    MAILGUN_FROM = f"<noreply@{MAILGUN_DOMAIN}>"
    MAILGUN_TO = get_secret("personal_email")

# === ATA drive ===
# we don't want the 'current' value to go below the treshold
REALLOCATED_SECTOR_COUNT_5_ID = 5
REPORTED_UNCORRECTABLE_ERRORS_187_BB_ID = 187
COMMAND_LINE_TIMEOUT_188_BC_ID = 188
CURRENT_PENDING_SECTOR_COUNT_197_C5_ID = 197
OFFLINE_UNCORRECTABLE_198_C6_ID = 198
# more conservative than regular tresholds
DANGEROUS_ATA_TRESHOLDS_BY_ID = {
    REALLOCATED_SECTOR_COUNT_5_ID: 60,
    REPORTED_UNCORRECTABLE_ERRORS_187_BB_ID: 60,
    COMMAND_LINE_TIMEOUT_188_BC_ID: 60,
    CURRENT_PENDING_SECTOR_COUNT_197_C5_ID: 60,
    OFFLINE_UNCORRECTABLE_198_C6_ID: 60
}

# === NVME drive ===
# treshold are inverted, we don't want the raw data to go above the raw value
DANGEROUS_NVME_TRESHOLDS_BY_NAME = {
    "critical_warning": 0,
    "media_errors": 0,
    "num_err_log_entries": 0,
    "warning_temp_time": 0,
    "critical_comp_time": 0,
    "percentage_used": 80, # means 80% of max TBW used
}

def is_hdd(report):
    return report["identity"]["interface"].lower() == "ata"

def format_table_row(values, widths):
    padded_values = []
    for value, width in zip(values, widths):
        text = str(value) if value is not None else "-"
        padded_values.append(text.ljust(width))
    return "| " + " | ".join(padded_values) + " |\n"

def write_error_log(lines):
    with open(ERROR_LOG_PATH, "a", encoding="utf-8") as f:
        for line in lines:
            f.write(line+"\n")

def run_command(command_args):
    process = subprocess.run(
        command_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    stdout = process.stdout or ""
    stderr = process.stderr or ""

    # smartctl often returns non-zero for warnings → accept if stdout exists
    if process.returncode != 0 and not stdout.strip():
        raise RuntimeError(
            f"Command failed with return code {process.returncode}: "
            f"{' '.join(command_args)}"
            f"stdout : {stdout}"
            f"stderr : {stderr}"
        )

    return stdout

def power_on_years_from_hours(power_on_hours):
    if power_on_hours is None:
        return None
    return round(power_on_hours / (24 * 365), 2)

def list_physical_drives():
    output = run_command([SMARTCTL_COMMAND, "--scan-open"])
    drives = []
    for line in output.splitlines():
        if line.startswith("/dev/"):
            drives.append(line.split()[0])
    return drives

def read_drive_json(drive_path):
    output = run_command([
        SMARTCTL_COMMAND,
        "-a",
        "-j",
        drive_path
    ])
    return json.loads(output)

def extract_identity(data):
    return {
        "disk_family": data.get("model_family"),
        "disk_name": data.get("model_name") or data.get("device", {}).get("model_name"),
        "serial_number": data.get("serial_number"),
        "firmware_version": data.get("firmware_version"),
        "interface": data.get("device").get("protocol"),
        "smart_status" : data.get("smart_status").get("passed"),
    }

def extract_power_info(data):
    power_on_hours = None
    power_on_count = None

    if "power_on_time" in data:
        power_on_hours = data["power_on_time"].get("hours")

    if "power_cycle_count" in data:
        power_on_count = data.get("power_cycle_count")

    return power_on_hours, power_on_count

def extract_smart_attributes_ata(data):
    attributes = []
    if "ata_smart_attributes" in data:
        for attr in data["ata_smart_attributes"]["table"]:
            attributes.append({
                "id": attr["id"],
                "name": attr["name"],
                "current": attr["value"],
                "worst": attr["worst"],
                "threshold": attr.get("thresh", None),
                "raw": attr["raw"]["value"],
            })
    return attributes

def extract_smart_attribute_nvme(data):
    attributes = []
    if "nvme_smart_health_information_log" in data:
        log = data["nvme_smart_health_information_log"]
        for key, value in log.items():
            attributes.append({
                "name": key,
                "value": value,
            })
    return attributes

def detect_issues_ata(attributes):
    issues = []

    for attr in attributes:
        if isinstance(attr["id"], int):
            if attr["id"] in DANGEROUS_ATA_TRESHOLDS_BY_ID:
                if attr["current"] < DANGEROUS_ATA_TRESHOLDS_BY_ID[attr["id"]]:
                    issues.append(attr)
                elif attr["raw"] > 0:
                    issues.append(attr)

    return issues

def detect_issues_nvme(attributes):
    issues = []

    for attr in attributes:
        attr_name = attr["name"]
        if attr_name in DANGEROUS_NVME_TRESHOLDS_BY_NAME and attr["value"] > DANGEROUS_NVME_TRESHOLDS_BY_NAME[attr_name]:
            issues.append(attr)

    return issues

def write_common_report_info(file, report):
    file.write(f"disk family : {report['identity']['disk_family']}\n")
    file.write(f"disk name : {report['identity']['disk_name']}\n")
    file.write(f"disk letter : {report['drive_path']}\n")
    file.write(f"firmware version : {report['identity']['firmware_version']}\n")
    file.write(f"serial number : {report['identity']['serial_number']}\n")
    file.write(f"disk name interface : {report['identity']['interface']}\n")
    file.write(f"power on count : {report['power_on_count']}\n")
    file.write(f"power on hours : {report['power_on_hours']}\n")
    file.write(f"power on years : {report['power_on_years']}\n")
    file.write(f"smart status is ok (according to smartctl) : {report['identity']['smart_status']}\n\n")

def write_ata_smart_report_info(file, report):
    file.write("SMART :\n\n")
    file.write("current : 0-100 score, higher is better\n")
    file.write("worst : historical minimum of 'current'\n")
    file.write("threshold : if current goes below that then it's bad\n")
    file.write("raw values : the actual value\n\n")
    headers = [col[0] for col in SMART_ATA_TABLE_COLUMNS]
    widths = [col[1] for col in SMART_ATA_TABLE_COLUMNS]

    file.write(format_table_row(headers, widths))
    file.write(format_table_row(["-" * w for w in widths], widths))

    for attr in report["attributes"]:
        row = [
            attr["id"],
            attr["name"],
            attr["current"],
            attr["worst"],
            attr["threshold"],
            attr["raw"],
        ]
        file.write(format_table_row(row, widths))

    file.write("\n")

def write_nvme_smart_report_info(file, report):
    file.write("SMART :\n\n")
    file.write("lower is better\n\n")
    headers = [col[0] for col in SMART_NVME_TABLE_COLUMNS]
    widths = [col[1] for col in SMART_NVME_TABLE_COLUMNS]

    file.write(format_table_row(headers, widths))
    file.write(format_table_row(["-" * w for w in widths], widths))

    for attr in report["attributes"]:
        row = [
            attr["name"],
            attr["value"],
        ]
        file.write(format_table_row(row, widths))

    file.write("\n")

def write_report(drive_reports):
    with open(REPORT_PATH, "w", encoding="utf-8") as file:
        for index, report in enumerate(drive_reports, start=1):
            file.write(f"{'-' * 28} DRIVE {index} {'-' * 28}\n")

            write_common_report_info(file, report)
            if is_hdd(report):
                write_ata_smart_report_info(file, report)
            else:
                write_nvme_smart_report_info(file, report)

def send_mail(subject, body):
    response = requests.post(
        f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
        auth=("api", MAILGUN_API_KEY),
        data={
            "from": MAILGUN_FROM,
            "to": MAILGUN_TO,
            "subject": subject,
            "text": body,
        },
        timeout=10
    )

    if response.status_code != 200:
        raise RuntimeError(f"Mailgun error: {response.text}")

def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    init_mail_settings()
    drive_paths = list_physical_drives()
    drive_reports = []
    global_issues = []
    for drive_path in drive_paths:
        data = read_drive_json(drive_path)

        identity = extract_identity(data)
        power_on_hours, power_on_count = extract_power_info(data)
        power_on_years = power_on_years_from_hours(power_on_hours)
        if identity["interface"].lower() == "ata":
            attributes = extract_smart_attributes_ata(data)
            issues = detect_issues_ata(attributes)
            if issues:
                global_issues.append(
                    ["ATA", drive_path, issues]
                )
        else:
            attributes = extract_smart_attribute_nvme(data)
            issues = detect_issues_nvme(attributes)
            if issues:
                global_issues.append(
                    ["NVME", drive_path, issues]
                )

        drive_reports.append({
            "drive_path": drive_path,
            "identity": identity,
            "power_on_hours": power_on_hours,
            "power_on_count": power_on_count,
            "power_on_years": power_on_years,
            "attributes": attributes,
        })

    write_report(drive_reports)

    if global_issues and SEND_MAIL:
        lines = ["SMART issues detected:\n"]
        for drive_type, drive_path, issues in global_issues:
            lines.append(f"Drive {drive_path}, type {drive_type}:")
            for issue in issues:
                lines.append(
                    f" - {issue}"
                )
            lines.append("")

        send_mail(
            subject="⚠ SMART issues detected on your system",
            body="\n".join(lines)
        )


if __name__ == "__main__":
    try:
        if is_time_to_run(SCRIPT_NAME, REPORT_DIR, ONE_DAY_IN_SECS):
            main()
            write_last_run_time(SCRIPT_NAME, REPORT_DIR)
    except Exception as e:
        write_last_run_time(SCRIPT_NAME, REPORT_DIR)
        err_log_lines = [
            str(e),
            traceback.format_exc()
        ]
        write_error_log(err_log_lines)
        try:
            if SEND_MAIL:
                send_mail(
                    subject="drives_checker from autoscripts failed",
                    body="read the error log in the report folder\n"
                )
        except:
            # not like we can do anything about it
            pass
