import json
import httpx
import os
import dotenv
import argparse
from typing import Any
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

# from mcp.server.sse import sse_app

# 解析命令行參數
parser = argparse.ArgumentParser(description='天氣查詢MCP服務器')
parser.add_argument('--port', type=int, default=8001, help='服務器監聽端口 (默認: 8001)')
args = parser.parse_args()

# 設置環境變數，讓 FastMCP 使用指定的端口
os.environ["MCP_SSE_PORT"] = str(args.port)

dotenv.load_dotenv()

# 創建 FastAPI 應用
app = FastAPI()

# 初始化 MCP 服务器
mcp = FastMCP("WeatherServer")

# OpenWeather API 配置
OPENWEATHER_API_BASE = os.getenv("OPENWEATHER_API_BASE")
API_KEY = os.getenv("OPENWEATHER_API_KEY") 
USER_AGENT = os.getenv("USER_AGENT")

async def fetch_weather(city: str) -> dict[str, Any] | None:
    """
    透過 OpenWeather API 獲取當天天氣資訊。
    :param city: 城市名稱（需使用英文，如 Taipei）
    :return: 天氣資訊dict；如果出現error則返回error訊息
    """
    params = {
        "q": city,
        "appid": API_KEY,
        "units": "metric",
        "lang": "zh_cn"
    }
    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(OPENWEATHER_API_BASE, params=params, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()  # 返回dict
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP 錯誤: {e.response.status_code}"}
        except Exception as e:
            return {"error": f"發生錯誤: {str(e)}"}

def format_weather(data: dict[str, Any] | str) -> str:
    """
    將天氣資訊轉為易讀文本。
    :param data: 天氣數據(dict or json str)
    :return: 提取後的易讀天氣資訊
    """
    # 如果input為str，先轉為dict
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception as e:
            return f"無法解析天氣數據: {e}"

    # 如果發現data內包含error，直接返回完整錯誤訊息
    if "error" in data:
        return f"⚠️ {data['error']}"

    # 提取資料，並進行容錯性處理
    city = data.get("name", "未知城市")
    country = data.get("sys", {}).get("country", "未知國家")
    temp = data.get("main", {}).get("temp", "N/A")
    humidity = data.get("main", {}).get("humidity", "N/A")
    wind_speed = data.get("wind", {}).get("speed", "N/A")
    # weather 可能null list，因此用 [0] 來提供default dict
    weather_list = data.get("weather", [{}])
    description = weather_list[0].get("description", "未知")

    return (
        f"🌍 {city}, {country}\n"
        f"🌡 溫度: {temp}°C\n"
        f"💧 濕度: {humidity}%\n"
        f"🌬 風速: {wind_speed} m/s\n"
        f"🌤 天氣: {description}\n"
    )

@mcp.tool()
async def query_weather(city: str) -> str:
    """
    查詢指定城市的天氣資訊，提供當前溫度、天氣狀況、濕度等資料。
    
    ## 使用場景
    - 規劃旅行或戶外活動
    - 查詢特定城市的天氣狀況
    - 了解天氣趨勢以做出決策
    
    ## 參數說明
    :param city: 城市名稱（需使用英文）
    
    ## 輸入範例
    - "Taipei" - 查詢台北市天氣
    - "Tokyo" - 查詢東京天氣
    - "New York" - 查詢紐約天氣
    - "London" - 查詢倫敦天氣
    
    ## 注意事項
    - 城市名稱必須使用英文
    - 對於有空格的城市名稱，請保留空格（例如："New York"）
    - 結果包含溫度、濕度、風速等信息
    
    :return: 格式化後的天氣資訊
    """
    data = await fetch_weather(city)
    return format_weather(data)

# # 將 MCP 伺服器掛載到 FastAPI 應用
# app.mount("/mcp", sse_app(mcp))

if __name__ == "__main__":
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from mcp.server.sse import SseServerTransport
    
    # 使用 uvicorn 啟動 FastAPI 應用
    print(f"啟動天氣服務器 在端口 {args.port}")
    
    # 創建 SSE 傳輸
    sse = SseServerTransport("/mcp/")
    
    # 定義 SSE 連接處理函數
    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp._mcp_server.run(
                streams[0], 
                streams[1],
                mcp._mcp_server.create_initialization_options()
            )
    
    # 定義健康檢查端點
    async def health_check(request):
        from starlette.responses import JSONResponse
        return JSONResponse({"status": "ok"})
    
    # 創建 Starlette 應用
    starlette_app = Starlette(
        routes=[
            # 確保 /sse 端點能夠正確處理 GET 請求
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/mcp/", app=sse.handle_post_message),
            # 添加健康檢查端點
            Route("/health", endpoint=health_check, methods=["GET"]),
        ]
    )
    
    # 使用 uvicorn 啟動應用
    uvicorn.run(starlette_app, host="0.0.0.0", port=args.port)