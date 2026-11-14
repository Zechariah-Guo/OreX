---
inclusion: always
---

# Terminal Command Execution Rules

This project runs on Windows with cmd.exe. The terminal has a known issue where OSC 633 escape sequences cause output to be truncated or invisible. **All command output MUST be redirected to files and then read back.**

## Output Directory

All command output goes to `.kiro/tmp/`. This directory is gitignored.

## How to Run Commands

NEVER rely on terminal output directly. Always redirect to a file and read it:

```
.venv\Scripts\python.exe -m pytest tests/some_test.py -v > .kiro/tmp/test_output.txt 2>&1
```

Then read `.kiro/tmp/test_output.txt` to see results.

### Pattern for any command:

1. Run: `<command> > .kiro/tmp/<descriptive_name>.txt 2>&1`
2. Read the output file using the file reading tool
3. Delete the output file when done (keep the folder clean)

### Common commands:

- **pytest**: `set PYTHONPATH=src && .venv\Scripts\python.exe -m pytest <args> > .kiro/tmp/pytest_output.txt 2>&1`
- **import check**: `set PYTHONPATH=src && .venv\Scripts\python.exe -c "<code>" > .kiro/tmp/import_check.txt 2>&1`
- **pip install**: `.venv\Scripts\python.exe -m pip install <pkg> > .kiro/tmp/pip_output.txt 2>&1`
- **general**: `<command> > .kiro/tmp/cmd_output.txt 2>&1`

## Waiting for Commands (sentinel file, REQUIRED)

The terminal often returns early or shows nothing. NEVER poll with ping, sleep loops, or repeated "check again" commands. Queued waits lock up the terminal.

1. Run the command in the background with a done-marker (`run_in_background: true`):
   ```
   cmd /c "<command> > .kiro\tmp\out.txt 2>&1 & echo done > .kiro\tmp\done.flag"
   ```
2. Make exactly ONE wait call, with `timeout` of 120000 or more:
   ```
   powershell -NoProfile -Command "while (-not (Test-Path .kiro\tmp\done.flag)) { Start-Sleep 1 }"
   ```
3. Only after the wait returns, read `.kiro/tmp/out.txt` with the file reading tool.
4. Delete `out.txt` and `done.flag`.

Rules:
- Never have more than one wait command running at a time.
- Never read the output file before the wait call returns.
- If the wait times out, report that to the user and stop. Do NOT queue another wait or ping.
- Delete any stale `.kiro\tmp\done.flag` before starting a new command.

## Python Virtual Environment

- NEVER use `activate` scripts
- ALWAYS use the full venv path: `.venv\Scripts\python.exe`
- Set PYTHONPATH to `src` when importing app modules

## Exit Codes

- Ignore exit codes from the terminal tool. They are unreliable on this system.
- Determine success/failure ONLY from the content of the output file.
- If the output file shows all tests passed, it passed — regardless of what exit code the terminal reports.

## Cleanup

After reading an output file and confirming results, delete it to avoid clutter. The `.kiro/tmp/` folder should stay empty between tasks.
