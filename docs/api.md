# API Reference

ADEval acts as a proxy and evaluator for ADK agents. It relies on standard ADK API patterns.

## Interaction with ADK

### 1. `/list-apps`
ADEval uses this to discover available agents or capabilities if supported by the endpoint.

### 2. `/run`
This is the primary endpoint used for testing. ADEval sends:
- `input`: The question/prompt.
- `session_id`: For state management.
- `state`: Optional session state variables.

ADEval then listens to the server-sent events (SSE) or JSON stream to extract tool calls and the final answer.

## Evaluation Logic

### Tool Matching
The tool matching logic compares the `tool_name` and `arguments`.
- **Flexible Arguments**: If the arguments are provided in a different order but have the same values, ADEval considers it a match.

### Answer Keyword Matching
A simple but effective check to see if the agent's final text response contains required strings.
