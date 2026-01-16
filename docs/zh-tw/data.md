# 資料管理

ADEval 優先考慮本地資料的所有權，所有的實驗資料都會保留在你的機器上。

## 儲存位置
預設情況下，ADEval 會在你執行 `adeval ui` 指令的目錄中建立一個 `.adeval/` 資料夾。

## 資料夾結構
```text
.adeval/
└── experiments/
    ├── exp_20240101_120000.json
    ├── exp_test_scenario_A.json
    └── ...
```

## JSON 綱要 (Schema)
每個實驗檔案包含：
- `id`：唯一識別碼。
- `name`：人類可讀的名稱。
- `agent_url`：目標 API。
- `test_cases`：物件陣列，包含：
  - `question`
  - `expected_tools`
  - `expected_keywords`
  - `results`（過往執行的結果）

## 資料備份
只需複製 `.adeval/` 資料夾，即可備份或將實驗遷移至另一台機器。
