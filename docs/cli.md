# CLI Reference

ADEval v0.2.0 introduces a powerful command-line interface for automation, CI/CD integration, and quick testing.

## Global Commands

### `adeval --help`
Show the main help message with all available commands.

### `adeval config`
Manage global settings like the default API URL, User ID, and App Name.
- `--url`: Set default Agent API URL.
- `--user`: Set default User ID.
- `--app`: Set default App Name.

Example:
```bash
adeval config --url "http://localhost:8000" --user "dev_01"
```

## Experiment Operations

### `adeval list`
List all experiments stored in the local `.adeval/experiments` directory.

### `adeval inspect <EXP_ID>`
Preview the details of an experiment, including all test cases and their current status, without running them.

### `adeval import <FILE.csv>`
Import test cases from a CSV file to create a new experiment.
- `--name`: Specify a custom name for the experiment.

### `adeval export <EXP_ID>`
Export experiment results to a CSV file for reporting.
- `--output`: Specify the output path.

### `adeval run <EXP_ID>`
Execute all test cases in an experiment and show a real-time progress and a final summary.
- `--verbose`: Show full raw response details on failure.

### `adeval delete <EXP_ID>`
Permanently remove an experiment's data.

## Utility Commands

### `adeval test "<QUESTION>"`
Quickly test a single question against the agent without creating an experiment.
- `--url`: Override the default API URL.
- `--app`: Override the default App Name.

### `adeval ui`
Launch the Web Interface.
- `--port`: Custom port (default: 8080).
- `--host`: Bind address (default: 127.0.0.1).
