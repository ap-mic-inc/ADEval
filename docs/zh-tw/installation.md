# 安裝指南

ADEval 可以透過 `pip` 在本地安裝，或透過 `Docker` 進行部署。

## 系統需求

- Python 3.9+
- pip (Python 套件管理工具)
- Docker (選配，用於容器化部署)

---

## 本地安裝

若要在本地環境使用或開發 ADEval：

1. **複製儲存庫**：
   ```bash
   git clone https://github.com/ap-mic-inc/ADEval.git
   cd ADEval
   ```

2. **以開發模式安裝**：
   ```bash
   pip install -e .
   ```
   *註：使用 `-e` 參數可以讓源碼的修改即時反映在已安裝的指令中。*

---

## Docker 部署

如果你偏好乾淨且容器化的環境：

1. **建置映像檔**：
   ```bash
   docker build -t adeval:latest .
   ```

2. **執行容器**：
   建議掛載本地目錄以持久化保存實驗資料：
   ```bash
   docker run -d \
     -p 8080:8080 \
     -v $(pwd)/.adeval:/app/data/.adeval \
     --name adeval \
     adeval:latest
   ```

---

## 驗證安裝

安裝完成後，執行以下指令驗證是否成功：
```bash
adeval --help
```
你應該會看到可用指令的列表，包含 `ui`。
