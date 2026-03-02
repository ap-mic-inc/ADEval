# ADEval：打破 AI Agent 評測瓶頸，打造專業、系統化的 Q-Tools-A 驗證框架

### 為什麼開發 AI Agent 很容易，但「穩定」卻很難？

身為開發者，我們都知道使用 Google Agent Development Kit (ADK) 或各種 LLM 框架來搭建一個 AI Agent 並不難。真正的挑戰在於：**如何確保 Agent 的行為是可預測且穩定的？**

在實際的業務場景中，Agent 可能今天調用了正確的工具，明天卻因為 Prompt 的細微變化、模型更新或 Context 的干擾，導致流程偏移。如果我們只靠手動對話來測試，效率低且難以覆蓋所有邊界情況。

這就是我開發 **ADEval** 的初衷 —— 一個專為 AI 代理設計的系統化評測工具，讓開發者能以「自動化」與「視覺化」雙軌並行的方式，深度掌控 Agent 的每一個行為。

---

## 核心理念：Q-Tools-A 驗證架構

在評測 AI Agent 時，單純比對最後的文字回覆（Answer）是遠遠不夠的。一個高品質的 Agent 必須在正確的時機，以正確的參數調用正確的**工具（Tools）**。

ADEval 圍繞著 **Q-Tools-A** 邏輯進行設計：

1.  **Question (Q)**：輸入的問題、特定的 User ID 以及必要的 Session State（狀態保存）。
2.  **Tools**：自動驗證 Agent 是否調用了預期的工具。我們支援**智慧參數比對** —— 即使 JSON 參數的順序不同，只要數值與邏輯一致，即可判定通過。
3.  **Answer (A)**：通過關鍵字匹配或語意檢查，確保最終回覆符合業務規範。

---

## 雙模式操作：滿足開發與自動化的全場景

ADEval 同時提供了直觀的 **Web UI** 與強大的 **CLI 指令介面**，讓您在開發除錯與 CI/CD 自動化流程之間無縫切換。

### 1. 現代化 Web UI：視覺化追蹤與即時除錯

對於開發者來說，觀察 Agent 的思考過程至關重要。ADEval 的 Web 介面提供了一個強大的「Playground」，讓您可以即時輸入問題並觀察結果。

<snapshot>展示 ADEval 的 Playground 介面，包含左側實驗列表與中間的測試面板</snapshot>

其中最受歡迎的功能是 **Visual Tracing (視覺化追蹤)**。我們將複雜的 API Response 事件流轉化為「深色終端風格」的檢視器，您可以一鍵展開原始 JSON，精確定位工具在哪個步驟調用失敗或產生偏差。

<snapshot>展示 Visual Tracing 的深色終端檢視器，顯示 JSON 事件流</snapshot>

### 2. 強大 CLI：CI/CD 與批次執行的利器

當您的實驗設計完成後，您不再需要打開瀏覽器。ADEval 提供了完整的命令行工具，適合整合進自動化腳本：

*   **全域配置 (`adeval config`)**：設定預設的 API URL 與開發者身份，節省重複輸入時間。
*   **快速測試 (`adeval test`)**：無需建立實驗，直接對 Agent 進行壓力測試或邏輯驗證。
*   **批量執行與報告 (`adeval run / export`)**：執行整場實驗，並在結束後獲得精確的統計報告。

<snapshot>展示 CLI 執行 adeval run 結束後的 📊 EXPERIMENT SUMMARY 統計表格</snapshot>

---

## 深度功能解析

### 實驗管理與批次評測
您可以將不同的測試場景組織為「實驗（Experiments）」。支援透過 **CSV 檔案** 批次匯入數十甚至數百個測試案例。在執行過程中，ADEval 會提供即時進度條與通過率統計。

<snapshot>展示 Batch Evaluation 介面與即時進度條</snapshot>

### 本地數據擁有權
ADEval 優先考慮隱私與效能。所有的實驗數據、執行紀錄與設定檔都保存在本地的 `.adeval/` 資料夾中。這意味著您的測試資料不會上雲，且您可以輕鬆地備份或遷移整個測試題庫。

### 智慧比對邏輯
在 Tools 驗證中，我們支援「順序無感化」的比對。例如 Agent 調用了 `get_weather(city="Taipei", unit="c")`，即便預期順序不同，ADEval 也能精確判斷其行為是否符合規格。

---

## 如何開始使用？

ADEval 已經開源並發佈，您可以直接透過 Python 環境輕鬆安裝：

```bash
# 複製儲存庫
git clone https://github.com/ap-mic-inc/ADEval.git
cd ADEval

# 以可編輯模式安裝
pip install -e .
```

安裝完成後，只需輸入 `adeval ui` 即可開啟網頁介面，或使用 `adeval --help` 查看強大的 CLI 指令集。

---

## 結語

作為一名在 GenAI 領域持續深耕的 GDE 與 MLOps 工程師，我深知「可靠性」是 AI 應用落地的最後一哩路。**ADEval 不僅僅是一個工具，它代表了一種對 AI 質量管理（QA for AI）的專業態度。**

無論您是在建構一個簡單的聊天機器人，還是複雜的企業級 Agent 系統，ADEval 都能協助您建立一套可量化的評測標準，讓您的 AI 應用更加穩健。

如果您喜歡這個工具，歡迎到 GitHub 給我一個 Star，或在 Medium 下方與我分享您在 Agent 評測上遇到的挑戰！

---

**關於作者**
**Simon Liu**
APMIC MLOps 工程師 | Google Developer Expert (AI)
致力於推動生成式 AI、MLOps 與 AI Agents 的數位轉型實踐。

- **GitHub:** [https://github.com/ap-mic-inc/ADEval](https://github.com/ap-mic-inc/ADEval)
- **個人社群:** [https://simonliuyuwei.my.canva.site/link-in-bio](https://simonliuyuwei.my.canva.site/link-in-bio)
