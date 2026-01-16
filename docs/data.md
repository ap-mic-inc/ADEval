# Data Management

ADEval prioritizes local data ownership. All your experiment data stays on your machine.

## Storage Location
By default, ADEval creates a `.adeval/` folder in the directory where you run the `adeval ui` command.

## Folder Structure
```text
.adeval/
└── experiments/
    ├── exp_20240101_120000.json
    ├── exp_test_scenario_A.json
    └── ...
```

## JSON Schema
Each experiment file contains:
- `id`: Unique identifier.
- `name`: Human-readable name.
- `agent_url`: The target API.
- `test_cases`: Array of objects containing:
  - `question`
  - `expected_tools`
  - `expected_keywords`
  - `results` (from previous runs)

## Backing up Data
Simply copy the `.adeval/` folder to back up or move your experiments to another machine.
