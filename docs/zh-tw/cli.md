# CLI 指令參考

ADEval v0.2.0 引入了強大的命令行介面 (CLI)，適用於自動化、CI/CD 整合以及快速測試。

## 全域指令

### `adeval --help`
顯示包含所有可用指令的主幫助訊息。

### `adeval config`
管理全域設定，如預設的 API URL、User ID 和 App Name。
- `--url`：設定預設的 Agent API URL。
- `--user`：設定預設的 User ID。
- `--app`：設定預設的 App Name。

範例：
```bash
adeval config --url "http://localhost:8000" --user "dev_01"
```

## 實驗操作

### `adeval list`
列出存儲在本地 `.adeval/experiments` 目錄中的所有實驗。

### `adeval inspect <EXP_ID>`
預覽實驗詳情，包括所有測試案例及其當前狀態（無需執行即可查看內容）。

### `adeval import <檔案.csv>`
從 CSV 檔案匯入測試案例，建立新的實驗。
- `--name`：為實驗指定自定義名稱。

### `adeval export <EXP_ID>`
將實驗結果匯出為 CSV 檔案以供報告使用。
- `--output`：指定輸出路徑。

### `adeval run <EXP_ID>`
執行實驗中的所有測試案例，並顯示即時進度與最終統計報告。
- `--verbose`：在測試失敗時顯示完整的 API 原始回應細節。

### `adeval delete <EXP_ID>`
永久刪除實驗數據。

## 資料生成

### `adeval gendata --mcp <MCP_URL>`
連線至 MCP server 讀取工具定義，再用 Gemini 生成一組實驗。
- `--mcp`、`-m`：MCP server 的 URL，需包含 endpoint 路徑（例如 `http://127.0.0.1:8000/mcp`）。
- `--header`、`-H`：額外的 HTTP 標頭，格式為 `'Key: Value'`，可重複指定。MCP server 有啟用驗證時必填。
- `--token`：Bearer token 簡寫，等同 `-H 'Authorization: Bearer <token>'`，也可由環境變數 `MCP_AUTH_TOKEN` 提供。
- `--num`、`-n`：要生成的測試案例數量（預設 5）。
- `--tools`：每個案例預期的工具呼叫次數，設為 `1` 可強制生成單步驟問題。
- `--lang`：生成問句的語言（預設 `zh-tw`）。
- `--desc`：額外指示，用來把生成方向導向特定情境。
- `--app`：指派給生成案例的 App Name。
- `--key`：Gemini API 金鑰，也可由環境變數 `GEMINI_API_KEY` 提供。

需要驗證時的範例：
```bash
adeval gendata --mcp http://127.0.0.1:8000/mcp \
  --token "$MY_MCP_TOKEN" \
  --num 20 --app docker_agent
```

終端機只會印出標頭名稱，不會印出其內容值。

## 公用工具指令

### `adeval test "<問句>"`
快速對 Agent 進行單一問題測試，無需建立實驗。
- `--url`：覆寫預設的 API URL。
- `--app`：覆寫預設的 App Name。

### `adeval ui`
啟動 Web 介面。
- `--port`：自定義連接埠 (預設為 8080)。
- `--host`：綁定位址 (預設為 127.0.0.1)。
