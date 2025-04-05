import json
import os
import pymysql
import dotenv
import argparse
from typing import Any, Dict, List
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
import pathlib

# 解析命令行參數
parser = argparse.ArgumentParser(description='SQL查詢MCP服務器')
parser.add_argument('--port', type=int, default=8002, help='服務器監聽端口 (默認: 8002)')
args = parser.parse_args()

# 設置環境變數，讓 FastMCP 使用指定的端口
os.environ["MCP_SSE_PORT"] = str(args.port)

# 載入環境變數 - 確保明確指定 .env 檔案的位置
current_dir = pathlib.Path(__file__).parent.parent
env_path = current_dir / '.env'
print(f"嘗試載入環境變數檔案: {env_path}")
dotenv.load_dotenv(dotenv_path=env_path)

# 列印所有環境變數以進行偵錯
print(f"環境變數 CLEARDB_DATABASE_URL: {os.getenv('CLEARDB_DATABASE_URL', '未設定')}")
print(f"環境變數 OPENWEATHER_API_KEY: {os.getenv('OPENWEATHER_API_KEY', '未設定')}")  # 用於比較

# 創建 FastAPI 應用
app = FastAPI()

# 初始化 MCP 伺服器
mcp = FastMCP("SQLQueryServer")

def parse_mysql_url(db_url: str) -> Dict[str, Any]:
    """
    解析 MySQL URL 字串並返回連接參數。
    
    :param db_url: MySQL URL 字串 (格式: mysql://user:pass@host:port/dbname)
    :return: 包含連接參數的字典
    """
    # 移除 URL 前綴
    db_url = db_url.replace('mysql://', '')
    
    # 解析用戶認證
    if '@' in db_url:
        auth, rest = db_url.split('@')
        user = auth.split(':')[0]
        password = auth.split(':')[1] if ':' in auth else None
    else:
        user = 'root'
        password = None
        rest = db_url

    # 解析主機和資料庫名稱
    if '/' in rest:
        host_port, dbname = rest.split('/')
    else:
        host_port = rest
        dbname = None

    # 解析主機和端口
    if ':' in host_port:
        host, port_str = host_port.split(':')
        port = int(port_str)
    else:
        host = host_port
        port = 3306

    return {
        "host": host,
        "user": user,
        "password": password,
        "database": dbname,
        "port": port
    }

async def execute_sql(query: str) -> List[Dict[str, Any]] | Dict[str, str]:
    """
    執行 SQL 查詢並返回結果。
    
    :param query: SQL 查詢語句
    :return: 查詢結果或錯誤訊息
    """
    # 嘗試從環境變數獲取資料庫連接字串
    db_url = os.getenv('CLEARDB_DATABASE_URL', None)
    
    # 如果環境變數中沒有，使用預設值（請替換為您的實際資料庫連接字串）
    if not db_url:
        # 使用硬編碼的資料庫連接字串作為備用方案
        # 格式：mysql://username:password@hostname:port/database_name
        db_url = "mysql://root:password@localhost:3306/testdb"
        print(f"警告：使用預設資料庫連接字串。建議在 .env 檔案中設定 CLEARDB_DATABASE_URL。")

    try:
        # 解析資料庫連接參數
        db_params = parse_mysql_url(db_url)
        
        # 連接到資料庫
        connection = pymysql.connect(
            host=db_params["host"],
            user=db_params["user"],
            password=db_params["password"],
            database=db_params["database"],
            port=db_params["port"],
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

        try:
            with connection.cursor() as cursor:
                cursor.execute(query)
                result = cursor.fetchall()
                # 轉換為可序列化的列表格式
                return [dict(row) for row in result]
        finally:
            connection.close()

    except Exception as e:
        return {"error": f"執行查詢時發生錯誤: {str(e)}"}

def format_query_result(result: List[Dict[str, Any]] | Dict[str, str]) -> str:
    """
    將 SQL 查詢結果格式化為易讀文本。
    
    :param result: SQL 查詢結果或錯誤訊息
    :return: 格式化後的查詢結果
    """
    # 如果結果包含錯誤訊息，直接返回
    if isinstance(result, dict) and "error" in result:
        return f"⚠️ 錯誤: {result['error']}"

    # 如果結果為空列表，返回適當訊息
    if not result:
        return "查詢沒有返回任何資料。"

    # 如果結果是列表，進行適當格式化
    if isinstance(result, list):
        # 獲取所有列名
        columns = list(result[0].keys())
        
        # 創建表頭
        header = " | ".join(columns)
        separator = "-" * len(header)
        
        # 創建表格行
        rows = []
        for row in result:
            row_values = [str(row.get(col, "N/A")) for col in columns]
            rows.append(" | ".join(row_values))
        
        # 組合表格
        table = f"{header}\n{separator}\n" + "\n".join(rows)
        
        # 添加總結摘要
        summary = f"\n總共 {len(result)} 筆資料"
        
        return table + summary

    # 如果結果類型不明確，轉換為字符串
    return str(result)

@mcp.tool()
async def query_database(query: str) -> str:
    """
    執行 SQL 查詢並返回格式化結果，支援查詢銷售數據庫中的資料。
    
    ## 使用場景
    - 查詢銷售數據分析
    - 獲取區域、城市或產品的銷售統計
    - 比較不同時間段的銷售表現
    - 分析產品類別的銷售趨勢
    
    ## 參數說明
    :param query: SQL 查詢語句 (僅支援 SELECT 操作)
    
    ## 資料庫結構
    資料庫包含 'sales' 表，具有以下欄位：
    - ID (VARCHAR)：銷售記錄ID
    - Date (DATE)：銷售日期
    - Region (VARCHAR)：地區，值包括：関東, 関西
    - City (VARCHAR)：城市，值包括：東京, 横浜, 埼玉, 千葉, 京都, 大阪, 神戸
    - Category (VARCHAR)：類別，值包括：野菜, 果物
    - Product (VARCHAR)：產品名稱，如：キャベツ, 玉ねぎ, トマト, リンゴ, みかん, バナナ
    - Quantity (INT)：銷售數量
    - Unit_Price (DECIMAL)：單價
    - Total_Price (DECIMAL)：總價
    
    ## 輸入範例
    - "SELECT * FROM sales LIMIT 5" - 查詢前5筆銷售記錄
    - "SELECT Region, SUM(Total_Price) FROM sales GROUP BY Region" - 按地區統計銷售總額
    - "SELECT Product, SUM(Quantity) FROM sales WHERE Category='果物' GROUP BY Product ORDER BY SUM(Quantity) DESC" - 查詢水果類銷量最高的產品
    - "SELECT City, AVG(Unit_Price) FROM sales WHERE Product='リンゴ' GROUP BY City" - 查詢各城市蘋果的平均單價
    
    ## 注意事項
    - 僅支援 SELECT 等讀取操作，不支援修改資料庫的操作
    - 查詢結果將自動格式化為易讀的表格
    - 較複雜的查詢可能需要幾秒鐘處理時間
    
    :return: 格式化後的查詢結果
    """
    # 檢查是否為 SELECT 查詢
    if not query.strip().lower().startswith("select"):
        return "⚠️ 安全限制: 僅支援 SELECT 查詢操作，不允許修改資料庫。"
    
    # 執行查詢
    result = await execute_sql(query)
    
    # 格式化結果
    return format_query_result(result)

@mcp.resource("database://schema")
async def get_database_schema() -> str:
    """
    獲取資料庫結構作為資源。
    """
    try:
        # 查詢所有表格
        tables_result = await execute_sql("SHOW TABLES")
        
        if isinstance(tables_result, dict) and "error" in tables_result:
            return f"獲取資料庫結構時發生錯誤: {tables_result['error']}"
        
        # 建立結構描述
        schema = []
        for table_row in tables_result:
            table_name = list(table_row.values())[0]  # 獲取表名
            
            # 查詢表結構
            table_schema_result = await execute_sql(f"DESCRIBE {table_name}")
            if isinstance(table_schema_result, dict) and "error" in table_schema_result:
                schema.append(f"表 {table_name} 結構查詢錯誤: {table_schema_result['error']}")
                continue
            
            # 格式化表結構
            field_descriptions = []
            for field in table_schema_result:
                field_name = field.get('Field', 'unknown')
                field_type = field.get('Type', 'unknown')
                is_null = field.get('Null', '')
                key = field.get('Key', '')
                default = field.get('Default', '')
                
                field_desc = f"  - {field_name} ({field_type})"
                if key == 'PRI':
                    field_desc += " [主鍵]"
                if is_null == 'NO':
                    field_desc += " [非空]"
                if default:
                    field_desc += f" [預設值: {default}]"
                
                field_descriptions.append(field_desc)
            
            # 添加到結構描述
            schema.append(f"表: {table_name}\n" + "\n".join(field_descriptions))
        
        return "\n\n".join(schema)
        
    except Exception as e:
        return f"獲取資料庫結構時發生錯誤: {str(e)}"

# 執行 MCP 伺服器
if __name__ == "__main__":
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from mcp.server.sse import SseServerTransport
    
    print(f"啟動SQL查詢服務器 在端口 {args.port}")
    
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
            # SSE 端點
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/mcp/", app=sse.handle_post_message),
            # 添加健康檢查端點
            Route("/health", endpoint=health_check, methods=["GET"]),
        ]
    )
    
    # 使用 uvicorn 啟動應用
    uvicorn.run(starlette_app, host="0.0.0.0", port=args.port)
