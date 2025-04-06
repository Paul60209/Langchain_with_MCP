import json
import httpx
import os
import dotenv
import argparse
from typing import Any
from mcp.server.fastmcp import FastMCP

# Parse command line arguments
parser = argparse.ArgumentParser(description='Weather Query MCP Server')
parser.add_argument('--port', type=int, default=8001, help='Server listening port (default: 8001)')
args = parser.parse_args()

# Set environment variable for FastMCP to use the specified port
os.environ["MCP_SSE_PORT"] = str(args.port)

dotenv.load_dotenv()

# Initialize MCP Server
mcp = FastMCP("WeatherServer")

# OpenWeather API Configuration
OPENWEATHER_API_BASE = os.getenv("OPENWEATHER_API_BASE")
API_KEY = os.getenv("OPENWEATHER_API_KEY") 
USER_AGENT = os.getenv("USER_AGENT")

async def fetch_weather(city: str) -> dict[str, Any] | None:
    """
    Fetch current weather information via OpenWeather API.
    :param city: City name (must use English, e.g., Taipei)
    :return: Dictionary with weather information; returns error message dict if an error occurs
    """
    params = {
        "q": city,
        "appid": API_KEY,
        "units": "metric",
        "lang": "en" # Language for description, changed from zh_cn to en
    }
    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(OPENWEATHER_API_BASE, params=params, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()  # Return dict
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP error: {e.response.status_code}"}
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

def format_weather(data: dict[str, Any] | str) -> str:
    """
    Format weather information into readable text.
    :param data: Weather data (dict or json str)
    :return: Extracted and readable weather information
    """
    # If input is str, convert to dict first
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception as e:
            return f"Could not parse weather data: {e}"

    # If data contains an error, return the full error message directly
    if "error" in data:
        return f"⚠️ {data['error']}"

    # Extract data with fault tolerance
    city = data.get("name", "Unknown City")
    country = data.get("sys", {}).get("country", "Unknown Country")
    temp = data.get("main", {}).get("temp", "N/A")
    humidity = data.get("main", {}).get("humidity", "N/A")
    wind_speed = data.get("wind", {}).get("speed", "N/A")
    # weather can be a null list, so use [0] to provide a default dict
    weather_list = data.get("weather", [{}])
    description = weather_list[0].get("description", "Unknown")

    return (
        f"🌍 {city}, {country}\n"
        f"🌡 Temperature: {temp}°C\n"
        f"💧 Humidity: {humidity}%\n"
        f"🌬 Wind Speed: {wind_speed} m/s\n"
        f"🌤 Weather: {description}\n"
    )

@mcp.tool()
async def query_weather(city: str) -> str:
    """
    Query weather information for a specified city, providing current temperature, weather conditions, humidity, etc.

    ## Usage Scenario
    - Planning trips or outdoor activities
    - Checking the weather conditions of a specific city
    - Understanding weather trends to make decisions

    ## Parameter Description
    :param city: City name (must use English)

    ## Input Example
    - "Taipei" - Query weather for Taipei City
    - "Tokyo" - Query weather for Tokyo
    - "New York" - Query weather for New York
    - "London" - Query weather for London

    ## Notes
    - City name must be in English
    - For city names with spaces, keep the space (e.g., "New York")
    - Results include temperature, humidity, wind speed, etc.

    :return: Formatted weather information
    """
    data = await fetch_weather(city)
    return format_weather(data)

if __name__ == "__main__":
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from mcp.server.sse import SseServerTransport

    # Start the server using uvicorn
    print(f"Starting Weather Server on port {args.port}")

    # Create SSE transport
    sse = SseServerTransport("/mcp/")

    # Define SSE connection handler function
    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp._mcp_server.run(
                streams[0],
                streams[1],
                mcp._mcp_server.create_initialization_options()
            )

    # Create Starlette application
    starlette_app = Starlette(
        routes=[
            # Ensure the /sse endpoint can correctly handle GET requests
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/mcp/", app=sse.handle_post_message)
        ]
    )

    # Start the application using uvicorn
    uvicorn.run(starlette_app, host="0.0.0.0", port=args.port)