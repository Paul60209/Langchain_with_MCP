import os
import pymysql
import dotenv
import argparse
from typing import Any, Dict, List
from mcp.server.fastmcp import FastMCP
import pathlib

# Parse command line arguments
parser = argparse.ArgumentParser(description='SQL Query MCP Server')
parser.add_argument('--port', type=int, default=8002, help='Server listening port (default: 8002)')
args = parser.parse_args()

# Set environment variable for FastMCP to use the specified port
os.environ["MCP_SSE_PORT"] = str(args.port)

# Load environment variables - ensure the location of the .env file is specified explicitly
current_dir = pathlib.Path(__file__).parent.parent
env_path = current_dir / '.env'
print(f"Attempting to load environment variables file: {env_path}")
dotenv.load_dotenv(dotenv_path=env_path)

# Initialize MCP Server
mcp = FastMCP("SQLQueryServer")

def parse_mysql_url(db_url: str) -> Dict[str, Any]:
    """
    Parse a MySQL URL string and return connection parameters.

    :param db_url: MySQL URL string (format: mysql://user:pass@host:port/dbname)
    :return: Dictionary containing connection parameters
    """
    # Remove URL prefix
    db_url = db_url.replace('mysql://', '')
    
    # Parse user authentication
    if '@' in db_url:
        auth, rest = db_url.split('@')
        user = auth.split(':')[0]
        password = auth.split(':')[1] if ':' in auth else None
    else:
        user = 'root'
        password = None
        rest = db_url

    # Parse host and database name
    if '/' in rest:
        host_port, dbname = rest.split('/')
    else:
        host_port = rest
        dbname = None

    # Parse host and port
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
    Execute SQL query and return results.

    :param query: SQL query statement
    :return: Query results or error message
    """
    # Try to get the database connection string from environment variables
    db_url = os.getenv('CLEARDB_DATABASE_URL', None)
    
    # If not in environment variables, use a default value (please replace with your actual database connection string)
    if not db_url:
        # Use a hardcoded database connection string as a fallback
        # Format: mysql://username:password@hostname:port/database_name
        db_url = "mysql://root:password@localhost:3306/testdb"
        print(f"Warning: Using default database connection string. It is recommended to set CLEARDB_DATABASE_URL in the .env file.")

    try:
        # Parse database connection parameters
        db_params = parse_mysql_url(db_url)
        
        # Connect to the database
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
                # Convert to a serializable list format
                return [dict(row) for row in result]
        finally:
            connection.close()

    except Exception as e:
        return {"error": f"Error executing query: {str(e)}"}

def format_query_result(result: List[Dict[str, Any]] | Dict[str, str]) -> str:
    """
    Format SQL query results into readable text.

    :param result: SQL query result or error message
    :return: Formatted query result
    """
    # If the result contains an error message, return it directly
    if isinstance(result, dict) and "error" in result:
        return f"⚠️ Error: {result['error']}"

    # If the result is an empty list, return an appropriate message
    if not result:
        return "The query returned no data."

    # If the result is a list, format it appropriately
    if isinstance(result, list):
        # Get all column names
        columns = list(result[0].keys())
        
        # Create the header
        header = " | ".join(columns)
        separator = "-" * len(header)
        
        # Create the table rows
        rows = []
        for row in result:
            row_values = [str(row.get(col, "N/A")) for col in columns]
            rows.append(" | ".join(row_values))
        
        # Combine the table
        table = f"{header}\\n{separator}\\n" + "\\n".join(rows)
        
        # Add a summary
        summary = f"\\nTotal {len(result)} records"
        
        return table + summary

    # If the result type is unclear, convert to string
    return str(result)

@mcp.tool()
async def query_database(query: str) -> str:
    """
    Execute SQL query and return formatted results, supporting queries on the sales database.

    ## Usage Scenario
    - Querying sales data for analysis
    - Getting sales statistics for regions, cities, or products
    - Comparing sales performance across different time periods
    - Analyzing sales trends for product categories

    ## Parameter Description
    :param query: SQL query statement (only SELECT operations are supported)

    ## Database Structure
    The database contains a 'sales' table with the following fields:
    - ID (VARCHAR): Sales record ID
    - Date (DATE): Sales date
    - Region (VARCHAR): Region, values include: 関東, 関西
    - City (VARCHAR): City, values include: 東京, 横浜, 埼玉, 千葉, 京都, 大阪, 神戸
    - Category (VARCHAR): Category, values include: 野菜, 果物
    - Product (VARCHAR): Product name, e.g., キャベツ, 玉ねぎ, トマト, リンゴ, みかん, バナナ
    - Quantity (INT): Sales quantity
    - Unit_Price (DECIMAL): Unit price
    - Total_Price (DECIMAL): Total price

    ## Input Example
    - "SELECT * FROM sales LIMIT 5" - Query the first 5 sales records
    - "SELECT Region, SUM(Total_Price) FROM sales GROUP BY Region" - Calculate total sales by region
    - "SELECT Product, SUM(Quantity) FROM sales WHERE Category='果物' GROUP BY Product ORDER BY SUM(Quantity) DESC" - Query the best-selling products in the fruit category
    - "SELECT City, AVG(Unit_Price) FROM sales WHERE Product='リンゴ' GROUP BY City" - Query the average unit price of apples in each city

    ## Notes
    - Only SELECT and other read operations are supported; modifying the database is not allowed.
    - Query results will be automatically formatted into a readable table.
    - More complex queries may take a few seconds to process.

    :return: Formatted query result
    """
    # Check if it is a SELECT query
    if not query.strip().lower().startswith("select"):
        return "⚠️ Security Restriction: Only SELECT query operations are supported. Modifying the database is not allowed."
    
    # Execute the query
    result = await execute_sql(query)
    
    # Format the result
    return format_query_result(result)

@mcp.resource("database://schema")
async def get_database_schema() -> str:
    """
    Get the database schema as a resource.
    """
    try:
        # Query all tables
        tables_result = await execute_sql("SHOW TABLES")
        
        if isinstance(tables_result, dict) and "error" in tables_result:
            return f"Error getting database schema: {tables_result['error']}"
        
        # Build schema description
        schema = []
        for table_row in tables_result:
            table_name = list(table_row.values())[0]  # Get table name
            
            # Query table structure
            table_schema_result = await execute_sql(f"DESCRIBE {table_name}")
            if isinstance(table_schema_result, dict) and "error" in table_schema_result:
                schema.append(f"Table {table_name} schema query error: {table_schema_result['error']}")
                continue
            
            # Format table structure
            field_descriptions = []
            for field in table_schema_result:
                field_name = field.get('Field', 'unknown')
                field_type = field.get('Type', 'unknown')
                is_null = field.get('Null', '')
                key = field.get('Key', '')
                default = field.get('Default', '')
                
                field_desc = f"  - {field_name} ({field_type})"
                if key == 'PRI':
                    field_desc += " [Primary Key]"
                if is_null == 'NO':
                    field_desc += " [Not Null]"
                if default:
                    field_desc += f" [Default: {default}]"
                
                field_descriptions.append(field_desc)
            
            # Add to schema description
            schema.append(f"Table: {table_name}\\n" + "\\n".join(field_descriptions))
        
        return "\\n\\n".join(schema)
        
    except Exception as e:
        return f"Error getting database schema: {str(e)}"

# Run MCP Server
if __name__ == "__main__":
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from mcp.server.sse import SseServerTransport
    
    print(f"Starting SQL Query Server on port {args.port}")
    
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
            # SSE endpoint
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/mcp/", app=sse.handle_post_message)
        ]
    )
    
    # Start the application using uvicorn
    uvicorn.run(starlette_app, host="0.0.0.0", port=args.port)
