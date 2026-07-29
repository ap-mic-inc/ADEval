# Key Features

ADEval is packed with features designed to make evaluating ADK agents efficient and reliable.

## 1. Experiment Management
Organize your testing into "Experiments". Each experiment can have its own configuration:
- **Agent URL**: The endpoint of your ADK agent.
- **User ID**: Contextual ID for the session.
- **Test Cases**: A collection of Q-Tools-A sequences.

## 2. Q-Tools-A Validation
This is the core of ADEval. It validates three critical parts of an agent's response:
- **Question (Q)**: The input prompt and session state.
- **Tools**: Did the agent call the expected tools? 
  - **Verify Args (Off)**: Only checks if the tool name exists in the actual execution flow.
  - **Verify Args (On)**: Performs a "smart comparison" that validates both the tool name and its arguments (supporting order-independent comparison).
- **Answer (A)**: Does the final response contain specific keywords?

## 3. Visual Tracing
Debugging an agent's event stream can be difficult. ADEval provides a dark-terminal style view to:
- Inspect raw JSON events.
- Track tool execution timing.
- Identify where the flow might have deviated.

## 4. Batch Evaluation
Import dozens or hundreds of test cases via CSV.
- **Import**: Easily load bulk test cases.
- **Export**: Generate reports or backup your question bank.
- **Progress Monitoring**: Real-time progress bars for long-running batch tests.

## 5. Cross-Model Comparison (Benchmark)

Overlay several experiments on one radar chart in the BENCHMARK tab.

- **Matrix picker**: Select by a model × dataset grid. Click a cell for a single experiment, a model name for all its datasets (to read the difficulty gradient), or a dataset name for every model (to compare across models). A flat row of chips becomes unusable once there are dozens of runs.
- **Focus one metric**: Click a radar axis label or any row of the metrics table and the panel switches to a ranking for that metric, marking the best value. Experiments without the metric are excluded rather than counted as 0, and the panel names which ones were left out.
- **Export standalone HTML**: Save the current comparison as a single HTML file. It **does not depend on this service** and pulls in no external resources, so it opens offline and can be forwarded as-is. The exported file keeps the matrix picker and metric focus, letting the recipient adjust which experiments to compare; printing switches it to a light background and hides the controls.

## 6. UI Customization
- **Dark/Light Mode**: Switch between themes for better accessibility.
- **Responsive Design**: Works well on desktops and tablets.
