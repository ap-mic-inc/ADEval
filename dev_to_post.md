# [Open Source] ADEval — A Tool for Evaluating Tool-Use Capabilities of Google ADK AI Agents

---

### I. Introduction: Why Building a "Stable" AI Agent is Hard
As developers, we all know that scaffolding an AI Agent using Google’s **Agent Development Kit (ADK)** or various LLM frameworks is relatively straightforward. The real challenge, however, lies in **ensuring the Agent's behavior is predictable and stable.**

In real-world business scenarios, an Agent might call the right tool today but deviate tomorrow due to slight prompt variations, model updates, or context interference. Relying solely on manual chat testing is inefficient and fails to cover critical edge cases.

This is why I built **ADEval** — a systematic evaluation tool designed specifically for AI Agents. It empowers developers to gain deep control over Agent behavior through a dual-track approach: **Automation** and **Visualization**.

---

### II. Github: ADEval
ADEval provides an intuitive Web UI and a powerful CLI, allowing you to systematically test your Agent's **Question-Tools-Answer (Q-Tools-A)** flow. It supports experiment management, batch testing, and comprehensive tracing.

1.  **Github Repository**
    [GitHub - ap-mic-inc/ADEval: Google ADK Evaluation Service](https://github.com/ap-mic-inc/ADEval)
2.  **Project Documentation**
    [ADEval Documentation](https://github.com/ap-mic-inc/ADEval/tree/main/docs)

---

### III. Core Philosophy: The Q-Tools-A Validation Framework
When evaluating an AI Agent, comparing the final text response (Answer) is simply not enough. A high-quality Agent must call the right **Tools** at the right time with the correct parameters.

ADEval is designed around the **Q-Tools-A** logic:
1.  **Question**: The input prompt, specific User ID, and necessary Session State (persistence).
2.  **Tools**: Automatically validates if the Agent invoked the expected tools. We support **Smart Argument Comparison** — even if the JSON parameter order differs, ADEval marks it as a match if the values and logic are consistent.
3.  **Answer**: Ensures the final response meets business requirements via keyword matching or semantic checks.

Below is the workflow logic diagram I designed for ADEval, ensuring a clear path from start to output:

<snapshot>ADEval Workflow Logic Diagram (Mermaid Chart)</snapshot>

---

### IV. Dual Mode: From Debugging to Production Automation
ADEval provides both an intuitive Web UI and a powerful CLI, allowing you to switch seamlessly between manual debugging and CI/CD automation.

#### 1. Web UI: Visual Tracing & Real-time Debugging
Observing an Agent's thought process is critical. The ADEval Web dashboard features a powerful **"Playground"** where you can input questions and observe results in real-time.

<snapshot>ADEval Playground Interface showing testing panels</snapshot>

The standout feature is **Visual Tracing**. We transform complex API response event streams into a "Dark Terminal Style" viewer. You can expand raw JSON with one click to pinpoint exactly where a tool call failed or deviated.

<snapshot>Visual Tracing Dark Terminal View showing JSON events</snapshot>

#### 2. CLI Tool: Powerhouse for CI/CD & Batch Execution
Once your experiments are defined, you no longer need a browser. ADEval offers a full-fledged command-line tool perfect for automation scripts:
*   **Global Configuration (`adeval config`)**: Set default API URLs and developer credentials to save time.
*   **Quick Test (`adeval test`)**: Perform stress tests or logic validation directly against the Agent without creating an experiment.
*   **Batch Execution & Reporting (`adeval run / export`)**: Execute entire experiment sets and receive precise statistical reports.

<snapshot>CLI output showing 'adeval run' statistical table</snapshot>

---

### V. Deep Dive into Features
1.  **Experiment Management & Batch Evaluation**: Import dozens or hundreds of test cases via **CSV files**. ADEval provides real-time progress bars and pass-rate statistics during execution.
2.  **Local Data Ownership**: Privacy and performance are priorities. All experiment data, logs, and configs are stored locally in the `.adeval/` folder. Your data stays on your machine.
3.  **Smart Comparison Logic**: In tool validation, we support **"Order-Independent"** comparison. If an Agent calls `get_weather(city="Taipei", unit="c")`, ADEval accurately judges it even if the internal parameter sequence differs.

---

### VI. Getting Started
ADEval is open-source and ready to use. You can install it easily via Python:

```bash
# Clone the repository
git clone https://github.com/ap-mic-inc/ADEval.git
cd ADEval

# Install in editable mode
pip install -e .
```
After installation, simply run `adeval ui` to launch the web interface or check out `adeval --help` for the full CLI suite.

---

### VII. Conclusion
Building an AI Agent that can chat naturally is just the beginning. Ensuring its stability and predictability in complex business scenarios is where the real engineering challenge lies. ADEval was born to solve the core pain points of testing, debugging, and maintaining Agent systems.

In summary, ADEval brings three key values to developers:
*   **Precise Behavioral Control**: Move beyond text matching to rigorous Tool-use validation.
*   **Flexible Workflow**: Covers the entire lifecycle from visual debugging to automated regression testing.
*   **Security & Efficiency**: Localized storage for privacy and smart matching to reduce false positives.

If you are building high-quality enterprise AI applications with Google ADK, ADEval is your indispensable testing companion. Give us a **Star (⭐)** on GitHub or submit an Issue/PR to help us build a stronger AI evaluation ecosystem!

---

**I am Simon**
Hi everyone, I am Simon Liu, an AI Solutions Expert and Google Developer Expert (GDE) in GenAI. I am dedicated to helping enterprises implement AI technologies to solve real-world problems. If this post was helpful, please follow me on Medium or connect with me on LinkedIn.

**My Personal Website:** [https://simonliuyuwei.my.canva.site/link-in-bio](https://simonliuyuwei.my.canva.site/link-in-bio)
