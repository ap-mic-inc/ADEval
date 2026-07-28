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
- `--concurrency`、`-c`：同時執行的題數，預設 1。各題彼此獨立（每題自建 session），
  但**只對承受得住併發的後端安全**——自架的 LiteLLM proxy 常是序列處理，一題卡住就會
  骨牌式逾時，那類後端請維持 1。
- `--timeout`：每題等待 `/run` 的秒數，預設 120。工具回傳量大或模型較慢時要調高。

### `adeval delete <EXP_ID>`
永久刪除實驗數據。

### `adeval stats <EXP_ID>`
顯示已執行實驗的工具使用指標。
- `--mcp`、`-m`：MCP server URL。提供後會讀取工具的 `readOnlyHint`，額外計算唯讀遵循度。
- `--header`、`-H` / `--token`：連線 MCP server 的認證資訊。
- `--json`：輸出原始 JSON，方便接後續處理。

指標定義：

| 指標 | 定義 |
| --- | --- |
| 有工具呼叫率 | 實際解析到 functionCall 的題數／已執行題數 |
| 函式名正確率 | 預期工具名稱全部出現在實際呼叫中的題數／有填 Expected Tools 的題數 |
| 名稱+參數全對率 | 同上，但連參數也要相符 |
| 呼叫工具次數吻合度 | 實際呼叫次數與預期次數的接近程度（多呼叫、少呼叫都會扣分）。只看次數，不看用了哪些工具；**先探索再動作的模型會因步數變多而降低** |
| 唯讀遵循度 | 沒有在「題目未要求」的情況下呼叫寫入工具的題數／已執行題數 |
| 呈現品質 | LLM judge 對「答案呈現」的平均分——只評格式清晰度、可讀性、是否直接回答，**不評工具選擇**（那已由上面兩軸涵蓋），也忽略事實正確性 |
| 答案正確率 | 把回覆與「實際執行預期工具所得到的真實資料」比對，由 LLM 判斷是否如實反映。與呈現品質**刻意正交**：格式漂亮但數字是編的，前者高分、後者 0 分 |

需要「答案正確率」時，測資的 `expectedAnswer` 要先填入事實依據（執行該題 `expectedTools` 的真實回傳）；未填的題目不列入計算，該軸會從雷達圖上消失而不是顯示 0%。

### `adeval rejudge <EXP_ID>...`
用目前的 judge prompt 重新評分已執行過的實驗，**不重新呼叫 agent**（直接讀已儲存的答案）。改過 judge prompt、或想把多個實驗拉到同一套評分標準時很有用。
- 可一次傳多個實驗 ID。
- `--judge-model`：judge 用的 Gemini 模型。
- `--key`：Gemini API 金鑰（也可由 `GEMINI_API_KEY` 提供）。

### `adeval rescore <EXP_ID>...`
用目前的比對規則重新判定 PASS/FAIL，**不重新呼叫 agent**。改過比對邏輯後，可把舊實驗拉到同一套語意上，不必再花一次跑分的成本。
- `--verify-args / --no-verify-args`：PASS/FAIL 是否要求參數相符。

### `adeval rescore-answers <EXP_ID>... --dataset <測資 EXP_ID>`
比對已儲存的回覆與工具真實回傳，評出「答案正確率」，**不重新呼叫 agent**。
跑分結果本身不帶 `expectedAnswer`（那是測資的欄位），因此需要用 `--dataset` 指定提供事實依據的測資實驗，程式會以題目文字對回去。
- `--judge-model`、`--key`：同 `rejudge`。

正確率一律採**子集判定**：預期工具全部出現即算命中，模型額外的偵察呼叫不扣分。這與 `run` 的 PASS/FAIL（集合完全相等）不同——後者會把「先 list 再 inspect」這種合理行為判為失敗。

### `adeval benchmark <EXP_ID>`
用同一份資料集比較多個模型，每個模型各存成一個名為 `<資料集> @ <app>` 的實驗。
- `--app`、`-a`：要比較的 app（模型），可重複指定；不給則自動抓 `/list-apps` 的全部。
- `--mcp`、`-m` / `--header` / `--token`：同 `stats`，用來計算唯讀遵循度。
- `--judge / --no-judge`：是否用 LLM judge 評分（預設開啟）。
- `--verify-args / --no-verify-args`：PASS/FAIL 是否要求參數相等（預設不要求）。

```bash
adeval benchmark exp_abc123 \
  --app gemini_3_flash_preview --app gemini_3_6_flash \
  --mcp http://127.0.0.1:8000/mcp --token "$MY_MCP_TOKEN"
```

跑完會印出各指標的並排比較表，並可在 Web UI 的 **BENCHMARK** 分頁勾選這些實驗，疊成雷達圖。

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
