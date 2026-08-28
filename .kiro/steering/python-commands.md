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
