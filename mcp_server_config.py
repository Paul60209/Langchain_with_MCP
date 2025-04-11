import os

# Shared server configurations
SERVER_CONFIGS = {
    # "weather": {
    #     "path": os.path.join("MCP_Servers", "weather_server.py"),
    #     "port": 8001,
    #     "transport": "sse"
    # },
    # "sql_query": {
    #     "path": os.path.join("MCP_Servers", "sql_query_server.py"),
    #     "port": 8002,
    #     "transport": "sse"
    # },
    # "ppt_translator": {
    #     "path": os.path.join("MCP_Servers", "ppt_translator_server.py"),
    #     "port": 8003,
    #     "transport": "sse"
    # },
    "rag_server": {
        "path": os.path.join("MCP_Servers", "rag_server.py"), # 您的 rag_server.py 路徑
        "port": 8004, # RAG 伺服器使用 8004
        "transport": "sse", # 使用 SSE 以便 Agent 整合
    }
} 