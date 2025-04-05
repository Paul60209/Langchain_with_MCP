# LangChain MCP Chainlit 整合應用

這個項目整合了 LangChain、MCP（Model Context Protocol）和 Chainlit，創建了一個強大的對話式 AI 應用。

## 功能特點

- **多 MCP 服務器支持**：可同時連接到多個 MCP 服務器，擴展功能
- **互動式界面**：使用 Chainlit 提供美觀的用戶界面
- **動態工具選擇**：可在運行時更改連接的 MCP 服務器
- **強大的智能體**：基於 LangChain 的 ReAct 代理，能夠理解任務並選擇合適的工具

## 預設服務器

該應用預設連接到以下 MCP 服務器：

- **天氣查詢服務器**：提供全球天氣查詢功能
- **SQL 查詢服務器**：提供數據庫查詢功能
- **PPT 翻譯服務器**：提供 PPT 文件翻譯功能

## 安裝和運行

### 先決條件

- Python 3.8 或更高版本
- 安裝所有依賴項

### 安裝

```bash
# 克隆存儲庫
git clone https://github.com/yourusername/langchain_with_MCP.git
cd langchain_with_MCP

# 安裝依賴項
pip install -r requirements.txt
```

### 設置環境變量

創建 `.env` 文件並配置以下變量：

```
MODEL = "gpt-4o-mini"
OPENAI_API_KEY = "your_openai_api_key"
OPENWEATHER_API_KEY = "your_openweather_api_key"
USER_AGENT = "your_app/1.0"
OPENWEATHER_API_BASE = "https://api.openweathermap.org/data/2.5/weather"
CLEARDB_DATABASE_URL = "mysql://user:password@host:port/db"
```

### 運行應用

```bash
# 使用運行腳本啟動
python run.py

# 或直接使用 Chainlit 啟動
chainlit run app.py
```

## 使用方法

1. 啟動應用後，打開瀏覽器訪問 `http://localhost:8000`
2. 使用服務器選擇器選擇要連接的 MCP 服務器
3. 在聊天框中輸入問題或要求
4. AI 助手將分析請求並使用合適的工具生成回應

## 添加新的 MCP 服務器

要添加新的 MCP 服務器：

1. 在 `MCP_Servers` 目錄中創建新的服務器文件
2. 啟動應用時，新服務器會自動顯示在選擇器中

## 技術架構

- **Chainlit**：提供前端用戶界面
- **LangChain**：提供 LLM 應用開發框架
- **MCP**：提供標準化的模型上下文協議
- **langchain_mcp_adapters**：連接 LangChain 和 MCP 服務器的適配器

## 幫助和支持

如有問題或需要幫助，請提交 GitHub Issue 或聯繫項目維護者。

## 許可證

本項目使用 MIT 許可證 - 詳見 LICENSE 文件。
