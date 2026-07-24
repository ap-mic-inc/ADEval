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

### `adeval stats <EXP_ID>`
Show tool-use metrics for an experiment that has already been run.
- `--mcp`, `-m`: MCP server URL. When given, tools' `readOnlyHint` is read and read-only compliance is scored as well.
- `--header`, `-H` / `--token`: credentials for the MCP server.
- `--json`: emit raw JSON for further processing.

| Metric | Definition |
| --- | --- |
| Tool-call rate | Cases where a functionCall was parsed / cases run |
| Function-name accuracy | Cases where every expected tool name appears among the actual calls / cases with Expected Tools |
| Name+args accuracy | Same, but arguments must match too |
| Call efficiency | How close the actual number of calls is to the expected one (both over- and under-calling lose points) |
| Read-only compliance | Cases that touched no write-capable tool / cases run |
| Presentation quality | Average LLM judge score |

Accuracy uses **subset semantics**: every expected tool must appear, but extra exploratory calls are not penalised. This differs from `run`'s PASS/FAIL (set equality), which marks reasonable behaviour such as "list first, then inspect" as a failure.

### `adeval benchmark <EXP_ID>`
Run one dataset against several models. Each model is stored as its own experiment named `<dataset> @ <app>`.
- `--app`, `-a`: app (model) to benchmark. Repeatable; defaults to every app reported by `/list-apps`.
- `--mcp`, `-m` / `--header` / `--token`: as for `stats`, used to score read-only compliance.
- `--judge / --no-judge`: score presentation quality with an LLM judge (default on).
- `--verify-args / --no-verify-args`: whether argument equality decides PASS/FAIL (default off).

```bash
adeval benchmark exp_abc123 \
  --app gemini_3_flash_preview --app gemini_3_6_flash \
  --mcp http://127.0.0.1:8000/mcp --token "$MY_MCP_TOKEN"
```

Prints a side-by-side comparison table. The resulting experiments can be overlaid on a radar chart in the **BENCHMARK** tab of the Web UI.

## Data Generation

### `adeval gendata --mcp <MCP_URL>`
Connect to an MCP server, read its tool definitions, and use Gemini to generate an experiment.
- `--mcp`, `-m`: MCP server URL, including the endpoint path (e.g. `http://127.0.0.1:8000/mcp`).
- `--header`, `-H`: Extra HTTP header as `'Key: Value'`. Repeatable. Required for MCP servers behind authentication.
- `--token`: Bearer token shorthand, equivalent to `-H 'Authorization: Bearer <token>'`. Also readable from `MCP_AUTH_TOKEN`.
- `--num`, `-n`: Number of test cases to generate (default: 5).
- `--tools`: Target number of tool calls per case. `1` forces single-step questions.
- `--lang`: Language of the generated questions (default: `zh-tw`).
- `--desc`: Extra instructions to steer generation toward specific scenarios.
- `--app`: App Name assigned to the generated test cases.
- `--key`: Gemini API key. Also readable from `GEMINI_API_KEY`.

Authenticated example:
```bash
adeval gendata --mcp http://127.0.0.1:8000/mcp \
  --token "$MY_MCP_TOKEN" \
  --num 20 --app docker_agent
```

Only header names are echoed to the terminal, never their values.

## Utility Commands

### `adeval test "<QUESTION>"`
Quickly test a single question against the agent without creating an experiment.
- `--url`: Override the default API URL.
- `--app`: Override the default App Name.

### `adeval ui`
Launch the Web Interface.
- `--port`: Custom port (default: 8080).
- `--host`: Bind address (default: 127.0.0.1).
