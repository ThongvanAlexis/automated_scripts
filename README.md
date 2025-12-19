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
