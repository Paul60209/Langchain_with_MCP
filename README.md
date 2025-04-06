# Langchain with MCP Integrated Application

## 1. Project Scope

This project primarily combines the Langchain framework, Chainlit user interface, and the Model Context Protocol (MCP) to build an AI application capable of utilizing external tools.

*   **Core Components:**
    *   A **client application (`app.py`)** based on Chainlit and Langchain Agent.
    *   Three independently running **MCP Tool Servers (`MCP_Servers/`)**:
        *   Weather Query (`weather_server.py`)
        *   Database Query (`sql_query_server.py`)
        *   PowerPoint Translation (`ppt_translator_server.py`)
    *   **Startup and Management Scripts (`run.py`, `run_server.py`, `run_client.py`)** to simplify the launch process.
*   **Communication Protocol:** Uses **MCP (Model Context Protocol)** as the standardized communication method between the client and tool servers (via SSE transport).
*   **Goal:** To provide a foundational platform for understanding and experimenting with the MCP Client-Server architecture, Langchain Agent and Tool interaction, and Chainlit UI integration.

## 2. Quick Start

### 2.1. Environment Setup

1.  **Python Version:** Ensure you have Python 3.10 or higher installed.
2.  **Install Dependencies:** Open a terminal in the project root directory and run the following command to install all necessary Python packages:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Set Environment Variables (Important):**
    *   Find the `.env_example` file in the project root directory.
    *   **Copy** it and **rename** the copy to `.env`.
    *   **Edit the `.env` file** and fill in your own API keys and database settings:
        *   `OPENAI_API_KEY`: Your OpenAI API key (used for PPT translation).
        *   `OPENWEATHER_API_KEY`: Your OpenWeatherMap API key (used for weather query).
        *   `CLEARDB_DATABASE_URL`: Your MySQL database connection URL, format: `mysql://user:password@host:port/dbname` (used for database query).
        *   `USER_AGENT`: (Optional, might be needed by OpenWeather) Set a User-Agent string.

### 2.2. Start MCP Servers

**Using the Launcher**

1.  In the terminal at the project root directory, run:
    ```bash
    python run.py
    ```
2.  When the menu prompt appears, enter `1` (Start servers only) or `3` (Start servers and client), then press Enter.
3.  The servers (Weather, SQL, PPT Translator) will start in the background, listening on default ports 8001, 8002, 8003 respectively. The script automatically checks ports and writes the running configuration to `server_config.txt`.
4.  **Note:** The servers run persistently in the background. Closing this terminal **will not** stop the servers.
5.  **Stop Servers:** Press `Ctrl+C` in the terminal where `run.py` was executed if you chose option 3, or manage the background processes separately if you chose option 1. *(Correction: Need a better way to stop background servers - `run_server.py` handles this)*. To stop servers started by `run_server.py` (or option 1/3 of `run.py`), press `Ctrl+C` in the terminal running `run_server.py` or the main `run.py`.

### 2.3. Start Chainlit Client

**Prerequisite:** Ensure the MCP servers have been started according to step 2.2.

**Using the Launcher**

1.  In the terminal at the project root directory, run:
    ```bash
    python run.py
    ```
2.  When the menu prompt appears, enter `2` (Start client only) or `3` (Start servers and client), then press Enter.
3.  The script will automatically execute `chainlit run app.py`.
4.  Wait for Chainlit to finish starting, then open the provided URL (usually `http://localhost:8000`) in your browser.
5.  **Stop Client:** Press `Ctrl+C` in the terminal running the Chainlit client.

## 3. Tool Descriptions

The Langchain Agent (`app.py`) automatically discovers and uses the following tools provided by the MCP servers via the MCP Client:

### 3.1. Weather Query

*   **Function:** Queries real-time weather information (temperature, humidity, conditions, wind speed) for a specified city.
*   **Server Script:** `MCP_Servers/weather_server.py`
*   **Tool Name (Used by Agent):** `query_weather`
*   **Main Dependency:** OpenWeatherMap API (requires `OPENWEATHER_API_KEY` in `.env`)
*   **Example Client Connection Config (if connecting independently):**
    ```json
    {
      "mcpServers": {
        "weather": {
          "url": "http://localhost:8001/sse", // Or the deployed public URL
          "transport": "sse"
        }
      }
    }
    ```

### 3.2. SQL Query

*   **Function:** Executes SQL `SELECT` statements to query a pre-configured sales database (containing product, region, sales figures, etc.).
*   **Server Script:** `MCP_Servers/sql_query_server.py`
*   **Tool Name (Used by Agent):** `query_database`
*   **Main Dependency:** MySQL Database (requires `CLEARDB_DATABASE_URL` in `.env`)
*   **Example Client Connection Config (if connecting independently):**
    ```json
    {
      "mcpServers": {
        "sql_query": {
          "url": "http://localhost:8002/sse", // Or the deployed public URL
          "transport": "sse"
        }
      }
    }
    ```

### 3.3. PPT Translator

*   **Function:** Translates PowerPoint files (.ppt/.pptx) from a source language to a target language, attempting to preserve the original formatting.
*   **Server Script:** `MCP_Servers/ppt_translator_server.py`
*   **Tool Names (Used by Agent):**
    *   `translate_ppt`: The core server-side translation tool, receives Base64 encoded file content.
    *   `upload_and_translate_ppt`: A front-end helper tool defined in `app.py` that triggers Chainlit's file upload interface and calls `translate_ppt` upon receiving the file. The Agent is prompted to prioritize this tool when the user requests translation of a local PPT.
*   **Main Dependencies:** OpenAI API (requires `OPENAI_API_KEY` in `.env`), `python-pptx`
*   **Example Client Connection Config (if connecting independently):**
    ```json
    {
      "mcpServers": {
        "ppt_translator": {
          "url": "http://localhost:8003/sse", // Or the deployed public URL
          "transport": "sse"
        }
      }
    }
    ```

## 4. Architecture Structure

This project adopts a clear **Client-Server** architecture, utilizing **MCP (Model Context Protocol)** for standardized communication.

### High Level Architecture
![](images/Chatbot_Architecture(High%20Level).png)

### Function Level Architecture
![](images/Chatbot_Architecture(Function%20Level).png)
*   **Launch & Management Layer (`run.py`, `run_server.py`, `run_client.py`):** Provides unified launch management. `run_server.py` independently manages the lifecycle of all MCP tool server subprocesses.
*   **Application Layer (Client - `app.py`):** A **Chainlit**-based Web UI, embedding a **Langchain Agent** as its core, communicating with backend tool servers via the **MCP Client Adapter**.
*   **Tool Server Layer (MCP Servers - `MCP_Servers/*.py`):** Each server is an independent Python process, implementing the MCP tool interface using **FastMCP**, and providing a communication endpoint via **SSE**.
*   **Communication Protocol:** **MCP over SSE** is used between the client and servers.
*   **Configuration Management:** Uses `.env` to manage sensitive configurations, `server_config.txt` records server running ports.

## 5. Project Technologies

*   **MCP (Model Context Protocol):** Serves as the standardized interface protocol between the client and tool servers.
*   **Langchain:** The core framework for building LLM applications, especially the implementation of Agent Executor.
*   **Chainlit:** A Python framework for quickly building chatbot UIs.
*   **Langchain MCP Adapters:** The bridge connecting Langchain Agent and MCP tools.
*   **FastAPI/Starlette/Uvicorn:** The ASGI web framework and server underlying the MCP servers.
*   **OpenAI API:** Provides LLM and translation capabilities.
*   **Python-pptx:** Handles PowerPoint files.
*   **Docker (Optional Deployment):** Each server can be packaged into Docker images for deployment.

## 6. Project License

This project is licensed under the **Apache License 2.0**.

You can find the full license text in the `LICENSE` file in the project root directory. In short, it's a permissive open-source license that allows you to freely use, modify, and distribute the code (including for commercial purposes), provided you retain the original copyright and license notices.

## 7. Additional Notes

*   **Deployment:** Although currently designed for local execution, the project can be made publicly accessible by Dockerizing the MCP servers and deploying them to a cloud platform (e.g., Google Cloud Run). The server connection configuration in `app.py` would need modification accordingly.
*   **Extension:** You can easily add more custom MCP tool servers by referencing the structure of the existing ones.
