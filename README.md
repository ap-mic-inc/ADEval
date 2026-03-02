# ADEval - Google Agent Development Kit (ADK) AI Agent Evaluation System 🤖

[English Version](README.md) | [繁體中文版](README_zhtw.md)

ADEval is an evaluation tool designed specifically for developers using the Google Agent Development Kit (ADK). It provides an intuitive **Web UI** and a powerful **CLI** that allow you to systematically test your Agent's **Q-Tools-A (Question -> Tools -> Answer)** flow, supporting experiment management, batch testing, and comprehensive tracing.

**GitHub Repository:** [https://github.com/ap-mic-inc/ADEval](https://github.com/ap-mic-inc/ADEval)  
**Detailed Documentation:** [docs/index.md](docs/index.md)

![Playground](snapshot/playground.png)
![Batch Evaluation](snapshot/batch_evaluation.png)

## 🌟 Key Features

- **Designed for Google ADK**: Fully compatible with ADK's `/run` and `/list-apps` API specifications.
- **Dual Mode Support (New in v0.2.0)**: Seamlessly switch between **Visual Web UI** and **Headless CLI** for different development stages.
- **Experiment Management**:
  - Support for multiple independent experiments, with data automatically saved in the local `.adeval/` folder.
  - Complete records of experiment names, User ID, Agent API URL, and all test cases.
- **Q-Tools-A Validation**:
  - **Question (Q)**: Flexible configuration of test questions and Session State.
  - **Tools**: Automatic validation of whether the Agent invoked the expected tools (supporting order-independent smart comparison).
  - **Answer (A)**: Keyword matching to ensure Agent responses meet expectations.
- **Visual Tracing**:
  - One-click expansion of raw API responses, displaying the full JSON event stream in a dark terminal-style view.
- **Modern Interface**:
  - Support for **Dark / Light Mode** switching.
  - High-quality responsive UI built with Vue.js 3 and Tailwind CSS.

## 🚀 Quick Start

### 1. Installation
Clone the repository and install in editable mode:

```bash
git clone https://github.com/ap-mic-inc/ADEval.git
cd ADEval
pip install -e .
```

### 2. CLI Usage (Powerful & Headless)
ADEval v0.2.0 introduces a comprehensive CLI for automation and CI/CD:

- **Configure Defaults**: `adeval config --url "http://localhost:8000" --user "tester"`
- **Quick Test**: `adeval test "What's the weather today?"`
- **Import CSV**: `adeval import my_cases.csv --name "Regression_Test"`
- **Run & Export**: `adeval run <EXP_ID>` and then `adeval export <EXP_ID> -o results.csv`
- **Inspect**: `adeval inspect <EXP_ID>` to preview cases in terminal.

### 3. Launch Web UI
Run the following command to start the evaluation interface:

```bash
adeval ui
```
The default URL is: `http://127.0.0.1:8080`. You can customize the port via `--port 8081`.

## 🐳 Docker Deployment

If you prefer using Docker, use the following commands to build and run:

### 1. Build Docker Image
```bash
docker build -t adeval:latest .
```

### 2. Run Container
It is recommended to mount a local directory to persist experiment data:

```bash
docker run -d \
  -p 8080:8080 \
  -v $(pwd)/.adeval:/app/data/.adeval \
  --name adeval \
  adeval:latest
```

## 📂 Data Storage Structure

All experiment data is stored in the `.adeval` folder under your execution directory:

```text
.adeval/
├── experiments/    # Experiment JSON files (UTF-8)
└── config.json     # Global CLI configurations
```

## 🛠️ Tech Stack

- **Backend**: FastAPI (Python) - Handles API proxying and data persistence.
- **Frontend**: Vue.js 3 + Tailwind CSS - Responsive SPA.
- **CLI**: Typer + Rich - Modern command-line interface.

## VIII. About the Author

**Simon Liu**  
APMIC MLOps Engineer x Google Developer Expert (GDE) in AI

A technology enthusiast in the field of artificial intelligence solutions, focusing on assisting enterprises in implementing generative AI, MLOps, and Large Language Model (LLM) technologies to drive digital transformation and practical technological implementation.

Currently also a Google Developer Expert (GDE) in the GenAI field, actively participating in technology communities, promoting the application and development of AI technology through technical articles, speeches, and practical experience sharing. To date, he has published over a hundred technical articles on platforms like Medium, covering topics such as generative AI, RAG, and AI Agents, and has served as a speaker at numerous technical seminars, sharing practical applications of AI and generative AI.

**Related Links:**
- APMIC Official Website: [https://www.apmic.ai/](https://www.apmic.ai/)
- Personal Social Media Links: [https://simonliuyuwei.my.canva.site/link-in-bio](https://simonliuyuwei.my.canva.site/link-in-bio)

## IX. License

This project is licensed under the Apache License 2.0. See the [LICENSE](LICENSE) file for details.

---
ADEval - Making Google ADK Agent evaluation simpler and more professional.
