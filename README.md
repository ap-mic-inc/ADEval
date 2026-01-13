# ADEval - Agent Evaluation System 🤖

ADEval 是一款專為 AI Agent 開發者設計的評估工具。它提供了直觀的 Web UI，讓你能夠系統化地測試 Agent 的 **Q-Tools-A (Question -> Tools -> Answer)** 流程，並支援實驗管理、批次測試與完整追蹤（Tracing）。

## 🌟 功能亮點

- **實驗管理 (Experiment Management)**:
  - 支援多個獨立實驗，資料自動儲存於本地 `.adeval/` 資料夾。
  - 完整記錄實驗名稱、User ID、Agent API URL 與所有測試案例。
- **Q-Tools-A 驗證**:
  - **Question (Q)**: 靈活設定測試問題。
  - **Tools**: 自動驗證 Agent 是否呼叫了預期的工具（支援多工具無序驗證）。
  - **Answer (A)**: 關鍵字比對，確保 Agent 回答符合預期。
- **視覺化 Trace (追蹤)**:
  - 一鍵展開原始 API 回覆，以深色終端機風格顯示完整 JSON 事件流。
- **高效批次處理**:
  - 支援 CSV 檔案匯入測試案例。
  - 支援匯出「題庫備份」或「測試結果報告」。
  - 具備即時進度條與完成率統計。
- **現代化介面**:
  - 基於 Vue.js 3 與 Tailwind CSS 打造的高質感 UI。
  - 支援 UTF-8 編碼，完美顯示中文字符。

## 🚀 快速開始

### 1. 安裝環境
進入工具目錄並以開發模式安裝：

```bash
cd adeval-tool
pip install -e .
```

### 2. 啟動 UI
執行以下指令啟動評估介面：

```bash
adeval ui
```
預設網址為：`http://127.0.0.1:8080`

### 3. 進階啟動參數
你可以自定義啟動的 Port 或 Host：

```bash
adeval ui --port 8081 --host 0.0.0.0
```

## 🐳 Docker 部署

如果你偏好使用 Docker，可以使用以下指令進行建置與執行：

### 1. 建置 Docker 映像檔
在 `adeval-tool` 目錄下執行：

```bash
docker build -t adeval:latest .
```

### 2. 執行容器
建議掛載本地目錄以持久化保存實驗資料：

```bash
docker run -d \
  -p 8080:8080 \
  -v $(pwd)/.adeval:/app/data/.adeval \
  --name adeval \
  adeval:latest
```

## 📂 資料儲存結構

所有的實驗資料會儲存在你執行指令目錄下的 `.adeval` 資料夾中：

```text
.adeval/
└── experiments/
    ├── exp_xxxxxx.json    # 實驗資料 (UTF-8 JSON)
    └── ...
```

## 🛠️ 技術架構

- **Backend**: FastAPI (Python) - 負責 API 代理、靜態檔案託管與資料持久化。
- **Frontend**: Vue.js 3 + Tailwind CSS - 響應式單頁應用 (SPA)。
- **CLI**: Typer - 簡單易用的命令行工具。

---
ADEval - 讓 Agent 評估變得更簡單、更專業。
