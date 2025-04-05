import os
import asyncio
import chainlit as cl
from typing import List
from utils import MCPClientManager

def get_server_port(server_path, default_port=8000):
    """
    從服務器路徑中提取端口參數
    
    Args:
        server_path: 服務器路徑，可能包含port參數
        default_port: 默認端口
        
    Returns:
        提取的端口號
    """
    parts = server_path.split(' ')
    for i, part in enumerate(parts):
        if part == '--port' and i+1 < len(parts):
            try:
                return int(parts[i+1])
            except ValueError:
                pass
    return default_port

def get_server_base_name(server_path):
    """
    從服務器路徑中提取基本文件名
    
    Args:
        server_path: 服務器路徑，可能包含命令行參數
        
    Returns:
        基本文件名
    """
    main_path = server_path.split(' ')[0]
    return os.path.basename(main_path)

async def create_server_selector(available_servers: List[str]):
    """
    創建一個服務器選擇器UI組件
    
    Args:
        available_servers: 可用服務器路徑列表
    """
    # 創建選擇器元素
    selector = cl.Select(
        id="server-selector",
        label="選擇MCP服務器",
        values=[
            cl.SelectOption(
                value=server_path,
                label=get_server_base_name(server_path).replace('.py', '')
            )
            for server_path in available_servers
        ],
        initial_value=available_servers,
        multiple=True
    )
    
    # 發送選擇器到界面
    await selector.send()
    
    return selector

@cl.action_callback("server-selection")
async def on_server_selection(action):
    """
    處理服務器選擇更改
    
    Args:
        action: 用戶行為
    """
    # 獲取選擇的服務器
    selected_servers = action.value
    
    # 顯示更新消息
    await cl.Message(f"正在更新MCP服務器連接，請稍候...").send()
    
    # 重新初始化MCP客戶端
    global mcp_manager
    
    # 關閉現有連接
    old_manager = cl.user_session.get("mcp_manager")
    if old_manager:
        await old_manager.close()
    
    # 創建新連接
    mcp_manager = MCPClientManager.create_with_local_servers(selected_servers)
    tools = await mcp_manager.initialize()
    
    # 更新會話中的管理器
    cl.user_session.set("mcp_manager", mcp_manager)
    
    # 更新代理執行器的工具
    agent_executor = cl.user_session.get("agent_executor")
    if agent_executor:
        agent_executor.tools = tools
    
    # 顯示連接成功消息
    server_names = [get_server_base_name(server).replace('.py', '') for server in selected_servers]
    await cl.Message(f"已成功連接到以下服務器: {', '.join(server_names)}").send()
    
    await action.ack()

async def setup_server_selection():
    """設置服務器選擇界面"""
    # 獲取可用的MCP服務器
    available_servers = [
        os.path.join("MCP_Servers", "weather_server.py") + " --port 8001",
        os.path.join("MCP_Servers", "sql_query_server.py") + " --port 8002",
        os.path.join("MCP_Servers", "ppt_translator_server.py") + " --port 8003"
    ]
    
    # 創建選擇器
    selector = await create_server_selector(available_servers)
    
    # 創建操作按鈕
    update_button = cl.Button(
        name="更新服務器連接",
        onclick=cl.Action(name="server-selection", value=selector.initial_value)
    )
    
    # 發送按鈕
    await update_button.send() 