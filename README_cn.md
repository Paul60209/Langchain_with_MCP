# Langchain with MCP 整合應用

## 1. 專案範疇 (Project Scope)

本專案主要結合 Langchain 框架、Chainlit 使用者介面以及模型上下文協議 (MCP)，建立一個能夠利用外部工具的 AI 應用。

*   **核心組件:**
    *   一個基於 Chainlit 和 Langchain Agent 的**客戶端應用 (`app.py`)**。
    *   三個獨立運行的 **MCP 工具伺服器 (`MCP_Servers/`)**：
        *   天氣查詢 (`weather_server.py`)
        *   資料庫查詢 (`sql_query_server.py`)
        *   PowerPoint 翻譯 (`ppt_translator_server.py`)
    *   **啟動與管理腳本 (`run.py`, `run_server.py`, `run_client.py`)**，簡化啟動流程。
*   **通訊協議:** 使用 **MCP (Model Context Protocol)** 作為客戶端與工具伺服器之間的標準化通訊方式 (透過 SSE 傳輸)。
*   **目標:** 提供一個理解和實驗 MCP Client-Server 架構、Langchain Agent 與 Tool 互動、以及 Chainlit UI 整合的基礎平台。

## 2. 快速開始 (Quick Start)

### 2.1. 環境準備

1.  **Python 版本:** 確保您已安裝 Python 3.10 或更高版本。
2.  **安裝依賴:** 在專案根目錄開啟終端，執行以下命令安裝所有必要的 Python 套件：
    ```bash
    pip install -r requirements.txt
    ```
3.  **設定環境變數 (重要):**
    *   在專案根目錄找到 `.env_example` 文件。
    *   將其**複製**並**重新命名**為 `.env`。
    *   **編輯 `.env` 檔案**，填入您自己的 API 金鑰和資料庫設定：
        *   `OPENAI_API_KEY`: 您的 OpenAI API 金鑰 (用於 PPT 翻譯)。
        *   `OPENWEATHER_API_KEY`: 您的 OpenWeatherMap API 金鑰 (用於天氣查詢)。
        *   `CLEARDB_DATABASE_URL`: 您的 MySQL 資料庫連接 URL，格式為 `mysql://user:password@host:port/dbname` (用於資料庫查詢)。
        *   `USER_AGENT`: (可選，OpenWeather 可能需要) 設定一個 User-Agent 字串。

### 2.2. 啟動 MCP 伺服器

**使用起動器進行啟動**

1.  在專案根目錄的終端中執行：
    ```bash
    python run.py
    ```
2.  當看到提示選單時，輸入 `1` (僅啟動伺服器) 或 `3` (同時啟動伺服器和客戶端)，然後按 Enter。
3.  伺服器 (Weather, SQL, PPT Translator) 將在背景啟動，分別監聽預設端口 8001, 8002, 8003。腳本會自動檢查端口並將運行配置寫入 `server_config.txt`。
4.  **說明:** 伺服器會在背景持續運行。關閉此終端**不會**停止伺服器。
5.  **停止伺服器:** 在終端器按下 `Ctrl+C`。


### 2.3. 啟動 Chainlit 客戶端

**前提：** 請確保 MCP 伺服器已經依照步驟 2.2 啟動。

**使用啟動器進行啟動**

1.  在專案根目錄的終端中執行：
    ```bash
    python run.py
    ```
2.  當看到提示選單時，輸入 `2` (僅啟動客戶端) 或 `3` (同時啟動伺服器和客戶端)，然後按 Enter。
3.  腳本將自動執行 `chainlit run app.py`。
4.  等待 Chainlit 啟動完成，然後在瀏覽器中開啟其提供的 URL (通常是 `http://localhost:8000`)。
5.  **停止伺服器:** 在終端器按下 `Ctrl+C`。

## 3. 工具說明 (Tool Descriptions)

Langchain Agent (`app.py`) 會自動透過 MCP Client 發現並使用以下由 MCP 伺服器提供的工具：

### 3.1. 天氣查詢 (Weather Query)

*   **功能：** 查詢指定城市的即時天氣資訊 (溫度、濕度、天氣狀況、風速)。
*   **伺服器腳本：** `MCP_Servers/weather_server.py`
*   **工具名稱 (Agent 使用)：** `query_weather`
*   **主要依賴：** OpenWeatherMap API (需要 `.env` 中的 `OPENWEATHER_API_KEY`)
*   **客戶端連接配置範例 (如果獨立連接)：**
    ```json
    {
      "mcpServers": {
        "weather": {
          "url": "http://localhost:8001/sse", // 或部署後的公開 URL
          "transport": "sse"
        }
      }
    }
    ```

### 3.2. 資料庫查詢 (SQL Query)

*   **功能：** 執行 SQL `SELECT` 語句查詢預先配置的銷售資料庫 (包含產品、地區、銷售額等資訊)。
*   **伺服器腳本：** `MCP_Servers/sql_query_server.py`
*   **工具名稱 (Agent 使用)：** `query_database`
*   **主要依賴：** MySQL 資料庫 (需要 `.env` 中的 `CLEARDB_DATABASE_URL`)
*   **客戶端連接配置範例 (如果獨立連接)：**
    ```json
    {
      "mcpServers": {
        "sql_query": {
          "url": "http://localhost:8002/sse", // 或部署後的公開 URL
          "transport": "sse"
        }
      }
    }
    ```

### 3.3. PPT 翻譯 (PPT Translator)

*   **功能：** 將 PowerPoint 檔案 (.ppt/.pptx) 從來源語言翻譯到目標語言，並盡力保留原始格式。
*   **伺服器腳本：** `MCP_Servers/ppt_translator_server.py`
*   **工具名稱 (Agent 使用)：**
    *   `translate_ppt`: 伺服器端的核心翻譯工具，接收 Base64 編碼的檔案內容。
    *   `upload_and_translate_ppt`: 在 `app.py` 中定義的前端輔助工具，觸發 Chainlit 的檔案上傳介面，並在收到檔案後調用 `translate_ppt`。Agent 被提示在用戶請求翻譯本地 PPT 時優先使用此工具。
*   **主要依賴：** OpenAI API (需要 `.env` 中的 `OPENAI_API_KEY`), `python-pptx`
*   **客戶端連接配置範例 (如果獨立連接)：**
    ```json
    {
      "mcpServers": {
        "ppt_translator": {
          "url": "http://localhost:8003/sse", // 或部署後的公開 URL
          "transport": "sse"
        }
      }
    }
    ```

## 4. 架構說明 (Architecture Structure)

本專案採用了清晰的**客戶端-伺服器 (Client-Server)** 架構，並利用 **MCP (Model Context Protocol)** 實現標準化通訊。

### High Level Architecture
![](images/Chatbot_Architecture(High%20Level).png)

### Function Level Architecture
![](images/Chatbot_Architecture(Function%20Level).png)
*   **啟動與管理層 (`run.py`, `run_server.py`, `run_client.py`):** 提供統一的啟動管理，`run_server.py` 負責獨立管理所有 MCP 工具伺服器子進程的生命週期。
*   **應用層 (Client - `app.py`):** 基於 **Chainlit** 的 Web UI，內嵌 **Langchain Agent** 作為核心，透過 **MCP Client Adapter** 與後端工具伺服器溝通。
*   **工具伺服器層 (MCP Servers - `MCP_Servers/*.py`):** 每個伺服器是獨立的 Python 進程，使用 **FastMCP** 實現 MCP 工具接口，並透過 **SSE** 提供通訊端點。
*   **通訊協議:** 客戶端與伺服器之間使用 **MCP over SSE**。
*   **配置管理:** 使用 `.env` 管理敏感配置，`server_config.txt` 記錄伺服器運行端口。
  
## 5. 專案技術 (Project Technologies)

*   **MCP (Model Context Protocol):** 作為客戶端與工具伺服器之間的標準化接口協議。
*   **Langchain:** 用於構建 LLM 應用的核心框架，特別是 Agent Executor 的實現。
*   **Chainlit:** 快速構建聊天機器人 UI 的 Python 框架。
*   **Langchain MCP Adapters:** 連接 Langchain Agent 和 MCP 工具的橋樑。
*   **FastAPI/Starlette/Uvicorn:** 構成 MCP 伺服器背後的 ASGI Web 框架和伺服器。
*   **OpenAI API:** 提供 LLM 和翻譯能力。
*   **Python-pptx:** 處理 PowerPoint 文件。
*   **Docker (可選部署):** 可以將各伺服器打包成 Docker 鏡像進行部署。

## 6. 專案授權 (Project License)

本專案採用 **Apache License 2.0** 授權。

您可以在專案根目錄下找到 `LICENSE` 文件以獲取完整的授權條款文本。簡單來說，這是一個寬鬆的開源授權，允許您自由使用、修改和分發程式碼（包括商業用途），但需要保留原始的版權和授權聲明。

## 7. 其他補充 (Additional Notes)

*   **部署:** 雖然專案目前設計為本地運行，但可以透過將 MCP 伺服器 Docker 化並部署到雲平台 (如 Google Cloud Run) 來實現公開訪問。屆時需要修改 `app.py` 中的伺服器連接配置。
*   **擴展:** 您可以參考現有伺服器的結構，輕鬆添加更多自定義的 MCP 工具伺服器。
