---

[ 開源專案 ] ADEval - 驗測 Google ADK AI Agent 工具使用能力評測工具

---

[ 開源專案 ] ADEval - 驗測 Google ADK AI Agent 工具使用能力評測工具

---

I. 前言：開發「穩定」 AI Agent 很困難？
身為開發者，我們都知道使用 Google 所推出的 Agent Development Kit (ADK) 或各種 LLM 框架來搭建一個 AI Agent 並不難。真正的挑戰在於：如何確保 Agent 的行為是可預測且穩定的？
在實際的業務場景中，Agent 可能今天調用了正確的工具，明天卻因為 Prompt 的細微變化、模型更新或 Context 的干擾，導致流程與結果偏移。如果我們只靠手動對話來測試，效率低且難以覆蓋所有邊界情況。
這就是我當初開發 ADEval 的初衷 - - 一個專為 AI 代理設計的系統化評測工具，讓開發者能以「自動化」與「視覺化」雙軌並行的方式，深度掌控 Agent 的每一個行為。

---

II. Github: ADEval
ADEval 是一款專為使用 Google Agent Development Kit (ADK) 的開發者設計的評測工具。它提供直觀的 Web UI 與強大的 CLI，讓您可以系統化地測試 Agent 的 Question-Tools-Answer (問題 -> 工具 -> 回答) 流程，並支持實驗管理、批量測試與完整的追蹤紀錄。
1. Github 連結
GitHub - ap-mic-inc/ADEval: Google ADK Evaluation Service（Docker + HTML）
Google ADK Evaluation Service（Docker + HTML）. Contribute to ap-mic-inc/ADEval development by creating an account on…github.com
2. 專案文件
ADEval/docs at main · ap-mic-inc/ADEval
Google ADK Evaluation Service（Docker + HTML）. Contribute to ap-mic-inc/ADEval development by creating an account on…github.com

---

III. 核心理念：Question-Tools-Answer 驗證架構
在評測 AI Agent 時，單純比對最後的文字回覆（Answer）是遠遠不夠的。一個高品質的 Agent 必須在正確的時機，以正確的參數調用正確的工具（Tools）。
ADEval 圍繞著 Question-Tools-Answer 邏輯進行設計：
1. Question：輸入的問題、特定的 User ID 以及必要的 Session State（狀態保存）。
2. Tools：自動驗證 Agent 是否調用了預期的工具。我們支援智慧參數比對- - 即使 JSON 參數的順序不同，只要數值與邏輯一致，即可判定通過。
3. Answer：透過關鍵字匹配或語意檢查，確保最終回覆符合業務規範。
以下是我繪製出來的 ADEval 使用邏輯流程圖，讓你從開始到輸出能夠有一個好的邏輯。
ADEval 使用邏輯流程圖

---

IV. 雙模式操作：滿足開發與自動化的全場景
ADEval 同時提供了直觀的 Web UI 與強大的 CLI 指令介面，讓您在開發除錯與 CI/CD 自動化流程之間無縫切換。
1. Web UI：視覺化追蹤與即時除錯
對於開發者來說，觀察 Agent 的思考過程至關重要。ADEval 的 Web 介面提供了一個強大的「Playground」，讓您可以即時輸入問題並觀察結果。
其中最受歡迎的功能是 Visual Tracing (視覺化追蹤)。我們將複雜的 API Response 事件流轉化為「深色終端風格」的檢視器，您可以一鍵展開原始 JSON，精確定位工具在哪個步驟調用失敗或產生偏差。
2. CLI 工具：CI/CD 與批次執行的利器
當您的實驗設計完成後，您不再需要打開瀏覽器。ADEval 提供了完整的命令行工具，適合整合進自動化腳本：
全域配置 (adeval config)：設定預設的 API URL 與開發者身份，節省重複輸入時間。
快速測試 (adeval test)：無需建立實驗，直接對 Agent 進行壓力測試或邏輯驗證。
批量執行與報告 (adeval run / export)：執行整場實驗，並在結束後獲得精確的統計報告。

---

V. 深度功能解析
1. 實驗管理與批次評測
您可以將不同的測試場景組織為「實驗（Experiments）」。支援透過 CSV 檔案 批次匯入數十甚至數百個測試案例。在執行過程中，ADEval 會提供即時進度條與通過率統計。
2. 本地數據擁有權
ADEval 優先考慮隱私與效能。所有的實驗數據、執行紀錄與設定檔都保存在本地的 .adeval/ 資料夾中。這意味著您的測試資料不會上雲，且您可以輕鬆地備份或遷移整個測試題庫。
3. 智慧比對邏輯
在 Tools 驗證中，我們支援「順序無感化」的比對。例如 Agent 調用了 get_weather(city="Taipei", unit="c")，即便預期順序不同，ADEval 也能精確判斷其行為是否符合規格。

---

VI. 如何開始使用？
ADEval 已經開源並發佈，您可以直接透過 Python 環境輕鬆安裝：
# 複製儲存庫
git clone https://github.com/ap-mic-inc/ADEval.git
cd ADEval
# 以可編輯模式安裝
pip install -e .
安裝完成後，只需輸入 adeval ui 即可開啟網頁介面，或使用 adeval --help 查看強大的 CLI 指令集。

---

VII. 結語
開發出能自然對話的 AI Agent 只是起點，確保其在複雜商業場景中的穩定性與可預測性，才是真正考驗開發者實力的挑戰。ADEval 的誕生與開源，正是為了解決開發團隊在驗測、除錯與上線維護過程中的核心痛點。
總結來說，ADEval 為開發者帶來了以下三大關鍵價值：
精準的行為掌控： 捨棄單純的比對文字，透過嚴謹的 Question -> Tools -> Answer 驗證架構與智慧比對邏輯，確保 Agent 不只會「說對話」，更能「做對動作」。
靈活的工作流程： 雙軌並行的設計完美涵蓋了從開發到上線的全生命週期。您可以先用 Web UI 進行視覺化除錯與行為追蹤，再利用 CLI 無縫整合進 CI/CD 流水線進行自動化批次回歸測試。
安全與高效兼備： 本地化的數據儲存確保了測試資料庫的隱私與安全性，同時智慧無感化的參數比對大幅降低了因 JSON 順序不同而導致的誤判。

如果您正致力於使用 Google ADK 打造高品質的企業級 AI 應用，ADEval 將會是您不可或缺的測試利器。歡迎立即前往 GitHub 複製專案親自體驗，為您的 Agent 建立一套專屬的自動化測試標準！也歡迎給予專案一顆 Star (⭐) 支持，或提交 Issue 與 PR，與開源社群一起打造更強大的 AI 評測生態。

---

I am Simon
大家好，我是 Simon 劉育維，是一位 AI 領域解決方案專家，目前也擔任 Google GenAI 領域開發者專家 (GDE)，期待能夠幫助企業導入人工智慧相關技術解決問題。如果這篇文章對您有幫助，請在 Medium 上按一下鼓勵，並追蹤我的個人帳號，這樣您就可以隨時閱讀我所撰寫的文章。歡迎在我的 Linkedin 上留言提供意見，並與我一起討論有關人工智慧的主題，期待能夠對大家有所幫助！
My Personal Website: https://simonliuyuwei.my.canva.site/link-in-bio