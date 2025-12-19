# What is this?

A lightweight way to run periodic Python scripts by simply dropping them into a folder, instead of creating and managing a service for each one.

An external orchestrator triggers all scripts at a fixed interval.

# How does it work?

The orchestrator executes every script in the folder on a schedule (for example, hourly).

Each script is responsible for deciding whether it should actually do anything when invoked.

This keeps the orchestration simple and pushes the execution logic to the script itself.

# Current implemented scripts

  - the_orchestrator.py
  - drive_checker.py
     - check every drive, write a report, send a mail if an issue is detected, once per day

# Guide to setup the orchestrator to run every 10 minutes on windows  
  
### Pick the Python you want Task Scheduler to use  
  
You need the full path to `python.exe` you want (system Python, venv Python, etc).  
  
### Create the scheduled task  
  
 - Press Win key, type Task Scheduler, open it.  
 - In the right panel, click Create Task…  
	- (Prefer Create Task over “Basic Task” — it exposes all options.)  
### General tab  
 - Name: Automated Scripts Orchestrator  
 - Description: Runs the_orchestrator.py every 10 minutes  
 - Security options:  
	- Choose Run whether user is logged on or not (recommended for a daemon-like setup)  
	- Check Run with highest privileges if any script needs admin rights (smartctl sometimes does)  
### Triggers tab (every 10 minutes)  
  
Click New…  
 - Begin the task: On a schedule  
 - Settings: Daily  
 - Start: pick a start time (now is fine)  
 - Check Repeat task every: 10 minutes  
 - for a duration of: Indefinitely  
 - Check Enabled  
 - Click OK  
  
### Actions tab (run Python with your orchestrator)  
  
Click New…  
 - Action: Start a program  
 - Program/script: full path to python.exe  
 - Add arguments: the full path to the orchestrator in quotes  
 - Start in the folder containing the_orchestrator.py  
Click OK.  
### Conditions tab (recommended)  
  - Uncheck Start the task only if the computer is on AC power (if you’re on a laptop and want it to run on battery too)  
  - You can keep the other defaults unless you have a reason to change them.  
### Settings tab (important for reliability)  
 - Allow task to be run on demand  
 - Run task as soon as possible after a scheduled start is missed  
 - If the task fails, restart every: 1 minute  
	 - Attempt to restart up to: 3 times  
 - stop the task if it runs longer than: 9 minutes
	 - that means that if all your tasks combined last longer than 10 minutes you should not run every 10 minutes  
	 - If the running task does not end when requested, force it to stop  
Click OK.  
### Test it immediately  
  
 - In Task Scheduler’s Task Scheduler Library, find your task.  
 - Right click → Run  
 - Verify logs were created by the orchestrator
	 - automated_scripts\orchestrator_logs\...