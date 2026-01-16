# API 參考

ADEval 作為 ADK Agent 的代理與評估器，依賴標準的 ADK API 模式。

## 與 ADK 的互動

### 1. `/list-apps`
ADEval 使用此端點來探索可用的 Agent 或功能（若端點支援）。

### 2. `/run`
這是測試時使用的主要端點。ADEval 會傳送：
- `input`：問題或提示詞。
- `session_id`：用於狀態管理。
- `state`：選配的 Session 狀態變數。

ADEval 接著會監聽伺服器傳送事件 (SSE) 或 JSON 串流，以提取工具呼叫與最終回答。

## 評估邏輯

### 工具比對 (Tool Matching)
工具比對邏輯會比較 `tool_name` 與 `arguments`。
- **彈性參數**：如果參數名稱一致但順序不同，ADEval 仍會視為比對成功。

### 關鍵字比對 (Keyword Matching)
這是一個簡單但有效的方法，用來檢查 Agent 的最終文字回覆中是否包含必要的字串。
