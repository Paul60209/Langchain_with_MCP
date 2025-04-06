import os
import asyncio
from typing import Dict, List, Any, Optional
from langchain.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from dotenv import load_dotenv

# 加載環境變量
load_dotenv()

class MCPClientManager:
    """管理多個MCP服務器的客戶端連接"""
    
    def __init__(self, servers_config: Dict[str, Dict[str, Any]]):
        """
        初始化MCP客戶端管理器
        
        Args:
            servers_config: 服務器配置字典，格式為:
                {
                    "server_name": {
                        "command": "python",
                        "args": ["path/to/server.py"],
                        "transport": "stdio", # 或 "sse"
                        "url": "http://localhost:8000/sse"  # 僅SSE需要
                    }
                }
        """
        self.servers_config = servers_config
        self.client = None
        self._tools_cache = []
        
    async def initialize(self):
        """初始化所有MCP服務器的連接"""
        if self.client is None:
            self.client = MultiServerMCPClient(self.servers_config)
            await self.client.__aenter__()
            self._tools_cache = self.client.get_tools()
        return self._tools_cache
        
    async def close(self):
        """關閉所有MCP服務器的連接"""
        if self.client is not None:
            await self.client.__aexit__(None, None, None)
            self.client = None
            self._tools_cache = []
            
    def get_tools(self) -> List[BaseTool]:
        """獲取所有可用的工具"""
        if not self._tools_cache and self.client:
            self._tools_cache = self.client.get_tools()
        return self._tools_cache
        
    @classmethod
    def create_with_local_servers(cls, servers_list: List[str]):
        """
        使用本地服務器列表創建客戶端管理器
        
        Args:
            servers_list: 服務器Python文件路徑列表，可能包含命令行參數
            
        Returns:
            MCPClientManager 實例
        """
        server_config = {}
        for i, server_path in enumerate(servers_list):
            # 分割命令行參數
            parts = server_path.split(' ')
            main_path = parts[0]
            args = parts[1:] if len(parts) > 1 else []
            
            # 獲取基本文件名作為服務器名稱
            server_name = os.path.basename(main_path).replace('.py', '')
            
            # 組合參數列表
            server_args = [main_path] + args
            
            server_config[server_name] = {
                "command": "python",
                "args": server_args,
                "transport": "stdio"
            }
        return cls(server_config)

    @classmethod
    def create_with_remote_servers(cls, servers_list: List[Dict[str, str]]):
        """
        使用遠程SSE服務器列表創建客戶端管理器
        
        Args:
            servers_list: 服務器配置列表，格式為:
                [
                    {"name": "server1", "url": "http://localhost:8001/sse", "transport": "sse"},
                    {"name": "server2", "url": "http://localhost:8002/sse", "transport": "sse"}
                ]
                
        Returns:
            MCPClientManager 實例
        """
        server_config = {}
        for server in servers_list:
            server_config[server["name"]] = {
                "url": server["url"],
                "transport": server.get("transport", "sse")
            }
        return cls(server_config) 