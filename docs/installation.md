# Installation Guide

ADEval can be installed locally using `pip` or deployed via `Docker`.

## Prerequisites

- Python 3.9+
- pip (Python package manager)
- Docker (optional, for containerized deployment)

---

## Local Installation

To install ADEval for development or local use:

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/ap-mic-inc/ADEval.git
   cd ADEval
   ```

2. **Install in Editable Mode**:
   ```bash
   pip install -e .
   ```
   *Note: Using `-e` allows changes in the source code to be immediately reflected in the installed command.*

---

## Docker Deployment

If you prefer a clean, containerized environment:

1. **Build the Image**:
   ```bash
   docker build -t adeval:latest .
   ```

2. **Run the Container**:
   We recommend mounting a volume to persist your experiment data:
   ```bash
   docker run -d \
     -p 8080:8080 \
     -v $(pwd)/.adeval:/app/data/.adeval \
     --name adeval \
     adeval:latest
   ```

---

## Verification

After installation, run the following command to verify it's working:
```bash
adeval --help
```
You should see a list of available commands, including `ui`.
