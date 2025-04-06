import os

SERVER_CONFIGS = {
    "weather": {
        "path": os.path.join("MCP_Servers", "weather_server.py"),
        "port": 8001,
        "transport": "sse"
    },
    "sql_query": {
        "path": os.path.join("MCP_Servers", "sql_query_server.py"),
        "port": 8002,
        "transport": "sse"
    },
    "ppt_translator": {
        "path": os.path.join("MCP_Servers", "ppt_translator_server.py"),
        "port": 8003,
        "transport": "sse"
    }
} 