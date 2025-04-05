import os
import asyncio
import subprocess
import time
import signal
import httpx
import threading
import chainlit as cl
from chainlit.element import Element
from chainlit.sync import run_sync
from langchain.agents import AgentExecutor, create_react_agent, create_openai_tools_agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.memory import ConversationBufferMemory
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.prompts import PromptTemplate
from langchain.agents.output_parsers import ReActJsonSingleInputOutputParser
from langchain.callbacks.manager import CallbackManager
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain.callbacks.base import BaseCallbackHandler
import base64
import tempfile
from copy import deepcopy
import logging
from langchain_community.tools import tool
from langchain_core.pydantic_v1 import BaseModel, Field
import json

# 加載環境變量
load_dotenv()

# MCP 伺服器配置
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

# 配置 OpenAI 模型
OPENAI_MODEL = os.getenv("MODEL", "gpt-4o-mini")

async def check_server_health(url, retries=5, delay=2):
    """
    檢查伺服器健康狀態
    
    Args:
        url: 伺服器 URL
        retries: 重試次數
        delay: 每次重試之間的延遲（秒）
        
    Returns:
        bool: 伺服器是否健康
    """
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=5.0)
                # 只要伺服器返回任何響應，就認為是健康的
                print(f"健康檢查響應: {url} - 狀態碼: {response.status_code}")
                return True  # 如果能夠得到響應，就認為伺服器是健康的
        except Exception as e:
            print(f"健康檢查失敗 (嘗試 {attempt+1}/{retries}): {e}")
        
        if attempt < retries - 1:  # 如果不是最後一次嘗試
            await asyncio.sleep(delay)  # 等待一段時間再重試
    
    return False

async def create_mcp_client_with_retry(client_config, max_retries=3):
    """
    嘗試創建 MCP 客戶端，如果失敗則重試
    
    Args:
        client_config: MCP 客戶端配置
        max_retries: 最大重試次數
        
    Returns:
        tuple: (客戶端, 工具列表) 或 (None, None)
    """
    for attempt in range(max_retries):
        try:
            # 不使用timeout參數
            mcp_client = MultiServerMCPClient(client_config)
            await mcp_client.__aenter__()
            
            # 嘗試獲取工具列表，驗證連接成功
            try:
                tools = mcp_client.get_tools()
                if not tools:
                    print("警告: 工具列表為空")
                    tools = []
                return mcp_client, tools
            except Exception as tool_error:
                print(f"獲取工具列表失敗: {tool_error}")
                # 嘗試優雅退出
                try:
                    await mcp_client.__aexit__(None, None, None)
                except Exception as exit_error:
                    print(f"客戶端退出錯誤: {exit_error}")
                raise tool_error
                
        except Exception as e:
            print(f"創建 MCP 客戶端失敗 (嘗試 {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                # 如果不是最後一次嘗試，等待一段時間再重試
                await asyncio.sleep(3)
    
    return None, None

# 添加將服務器配置保存到文件的函數
def save_server_config():
    """將伺服器配置保存到文件"""
    config_file = "server_config.txt"
    with open(config_file, "w") as f:
        for name, config in SERVER_CONFIGS.items():
            f.write(f"{name}:{config['port']}:{config['transport']}\n")
    print(f"伺服器配置已保存到 {config_file}")

# 從文件加載服務器配置
def load_server_config():
    """從文件加載伺服器配置"""
    config_file = "server_config.txt"
    if not os.path.exists(config_file):
        print(f"找不到配置文件 {config_file}，使用默認配置")
        return False
    
    try:
        with open(config_file, "r") as f:
            lines = f.readlines()
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split(":")
            if len(parts) != 3:
                print(f"無效的配置行: {line}")
                continue
            
            name, port, transport = parts
            if name in SERVER_CONFIGS:
                SERVER_CONFIGS[name]["port"] = int(port)
                SERVER_CONFIGS[name]["transport"] = transport
        
        print("已從配置文件加載伺服器配置")
        return True
    except Exception as e:
        print(f"加載配置文件時出錯: {e}")
        return False

# 自定義回調處理器，用於將輸出串流到Chainlit消息
class ChainlitStreamingCallbackHandler(BaseCallbackHandler):
    """將LLM的輸出流式傳輸到Chainlit消息"""
    
    def __init__(self, cl_response_message):
        self.cl_response_message = cl_response_message
        self.tokens = []
        
    def on_llm_new_token(self, token: str, **kwargs):
        """處理新生成的token"""
        self.tokens.append(token)
        # 更新界面上的消息
        content = "".join(self.tokens)
        asyncio.create_task(self.cl_response_message.update(content=content))
        
    def on_llm_end(self, response, **kwargs):
        """LLM響應結束的處理"""
        self.tokens = []

@cl.on_chat_start
async def on_chat_start():
    """聊天開始時的初始化程序"""
    
    # 顯示初始化消息
    init_message = cl.Message(content="正在連接到 MCP 伺服器...")
    await init_message.send()
    
    # 加載伺服器配置
    load_server_config()
    
    # 創建 MCP 客戶端配置
    client_config = {}
    
    for name, config in SERVER_CONFIGS.items():
        if config["transport"] == "sse":
            client_config[name] = {
                "url": f"http://localhost:{config['port']}/sse",
                "transport": "sse"
            }
        else:
            client_config[name] = {
                "command": "python",
                "args": [config["path"], "--port", str(config["port"])],
                "transport": "stdio"
            }
    
    # 初始化 MCP 客戶端（帶重試）
    try:
        connecting_message = cl.Message(content="正在連接到 MCP 伺服器...")
        await connecting_message.send()
        mcp_client, tools = await create_mcp_client_with_retry(client_config)
        
        if not mcp_client or not tools:
            error_message = cl.Message(content="連接 MCP 伺服器失敗。請確保 MCP 伺服器已運行 (使用 run_server.py)。")
            await error_message.send()
            return
        
        # 將客戶端保存到會話
        cl.user_session.set("mcp_client", mcp_client)
        
        # 增加前端本地PPT上傳翻譯工具
        print("\n===== 添加前端工具 =====")
        print(f"原始工具列表: {[t.name for t in tools]}")
        enhanced_tools = add_upload_ppt_tool(tools)
        print(f"增強後工具列表: {[t.name for t in enhanced_tools]}")
        print(f"新增的工具: upload_and_translate_ppt")
        print("=========================\n")
        
        # 顯示已連接的伺服器
        servers_info = "\n".join([f"- {name} (端口: {config['port']})" for name, config in SERVER_CONFIGS.items()])
        connected_message = cl.Message(content=f"已連接到以下 MCP 伺服器:\n{servers_info}")
        await connected_message.send()
        
        # 設置回調管理器
        callback_manager = CallbackManager([
            StreamingStdOutCallbackHandler(),  # 將流式輸出顯示到控制台
        ])
        
        # 更新模型配置，使用特定版本並添加回調管理器
        llm = ChatOpenAI(
            model="gpt-4o-mini-2024-07-18",  # 使用特定版本模型
            temperature=0,  # 零溫度確保一致性
            streaming=True,
            callback_manager=callback_manager,
            verbose=True
        )
        memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
        
        # 獲取工具名稱列表
        tool_names = [tool.name for tool in enhanced_tools]
        
        # 創建系統消息
        system_message = """你是一個強大的AI助手，可以使用多種專業工具來幫助用戶解決問題。

工具種類和使用場景：

1. 【天氣查詢工具】
   - 工具名稱: "get_weather" 或包含 "weather" 的工具名
   - 使用場景: 任何與天氣、溫度、濕度、氣象預報相關的問題
   - 輸入格式: {{"city": "城市名稱"}}
   - 輸入範例: {{"city": "Taipei"}}, {{"city": "Tokyo"}}, {{"city": "New York"}}
   - 觸發詞: "天氣", "weather", "下雨", "溫度", "氣溫", "濕度", "預報"
   - 範例問題: "台北今天天氣如何?", "明天會下雨嗎?", "東京的氣溫是多少?"

2. 【資料庫查詢工具】
   - 工具名稱: "query_database" 或包含 "sql", "query", "database" 的工具名
   - 使用場景: 任何需要查詢數據、統計資料、資料表內容的問題
   - 輸入格式: {{"query": "SQL查詢語句"}}
   - 輸入範例: {{"query": "SELECT * FROM sales LIMIT 5"}}
   - 觸發詞: "數據", "資料", "銷售", "統計", "多少", "查詢", "資料庫", "表格"
   - 範例問題: "查詢最近的銷售數據", "有哪些產品?", "賣出了多少蘋果?", "最暢銷的產品是什麼?"
   - 資料庫結構：
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

3. 【檔案上傳翻譯工具】
   - 工具名稱: "upload_and_translate_ppt"
   - 使用場景: 需要用戶上傳本地PowerPoint檔案進行翻譯的所有請求
   - 輸入格式: {{"olang": "原始語言", "tlang": "目標語言"}}
   - 輸入範例: {{"olang": "英文", "tlang": "中文"}}
   - 強制觸發條件: 當用戶提到以下任何關鍵詞時，必須調用此工具而不是只回覆文本
     - "翻譯PPT", "翻譯簡報", "翻譯PowerPoint", "PPT翻譯", "簡報翻譯"
     - "將PPT翻譯", "將簡報翻譯", "幫我翻譯PPT", "幫我翻譯簡報"
     - "PPT從X翻譯為Y", "簡報從X翻成Y" (X和Y為任何語言)
   - 注意: 使用此工具時，系統會自動提示用戶上傳PPT檔案，無需另外發送文本訊息請求上傳
   - 範例請求: "幫我將ppt從英文翻譯為中文" - 此時應直接調用工具並提供參數 {{"olang": "英文", "tlang": "中文"}}

4. 【伺服器端翻譯工具】
   - 工具名稱: "translate_ppt"
   - 使用場景: 用戶需要翻譯已存在於伺服器上的PowerPoint文件
   - 輸入格式: {{"olang": "原始語言", "tlang": "目標語言", "file_path": "檔案路徑"}}
   - 輸入範例: {{"olang": "英文", "tlang": "中文", "file_path": "/path/to/file.pptx"}}
   - 範例問題: "翻譯伺服器上的PPT檔案", "轉換已存在的演示文稿"

重要原則:
1. 工具選擇: 仔細分析用戶問題，判斷最合適的工具類型
2. 語言回應: 以用戶使用的語言回應
3. 不要猜測: 對於需要數據的問題，必須使用適當的工具而不是猜測
4. JSON格式: 所有工具輸入必須是JSON格式，不能是純文字字串
5. 選擇正確的PPT翻譯工具: 當用戶需要翻譯本地檔案時，必須使用 upload_and_translate_ppt；當處理伺服器上已有的檔案時，使用 translate_ppt
6. 強制使用工具: 對於提到"翻譯PPT"、"翻譯簡報"等內容的請求，必須使用工具而不是只回覆文字訊息

決策流程:
1. 分析用戶問題是關於: 天氣? 數據查詢? PPT翻譯?
2. 選擇對應的工具類別
3. 構建正確格式的輸入
4. 執行工具並返回結果

特別提醒:
- 對於PPT翻譯請求，只回覆文字而不調用工具是錯誤的行為
- 正確做法是分析用戶請求中的語言信息(如從英文到中文)，然後立即調用upload_and_translate_ppt工具
- upload_and_translate_ppt工具會自動處理後續的檔案上傳流程，無需額外提示"""
        
        # 創建 ReAct 風格的提示模板
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            ("system", """當用戶請求翻譯PPT時，必須立即使用 upload_and_translate_ppt 工具，而不是回覆純文本消息。

請使用以下格式處理用戶問題：

思考: 分析用戶問題，確定需要使用什麼工具。不要寫出具體答案，而是判斷應該使用哪個工具獲取信息。
對於與翻譯PPT相關的請求，必須使用upload_and_translate_ppt工具，這個工具會自動處理文件上傳和後續流程。

行動: 選擇工具並使用適當的JSON輸入參數。

觀察: 查看工具返回的結果。

行動：可能需要使用另一個工具。

觀察：查看新工具的結果。

最終回應: 綜合所有信息，給出完整回應。使用繁體中文。"""),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
        
        # 創建代理 - 使用 OpenAI create_openai_tools_agent 代替 OpenAIFunctionsAgent
        agent = create_openai_tools_agent(
            llm=llm,
            tools=enhanced_tools,
            prompt=prompt
        )
        
        # 創建代理執行器，設置更高的max_iterations和verbose=True
        agent_executor = AgentExecutor(
            agent=agent,
            tools=enhanced_tools,
            memory=memory,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=5,
            early_stopping_method="force",  # 如果達到最大迭代次數，強制停止
            return_intermediate_steps=True  # 返回中間步驟，便於調試
        )
        
        # 存儲到用戶會話
        cl.user_session.set("agent_executor", agent_executor)
        
        # 發送歡迎消息
        welcome_message = cl.Message(content="您好！我是基於 MCP 的智能助手。請問有什麼我可以幫您的？")
        await welcome_message.send()
    
    except Exception as e:
        error_message = cl.Message(content=f"初始化 MCP 客戶端時出錯: {str(e)}")
        await error_message.send()
        import traceback
        traceback.print_exc()  # 在伺服器端打印完整錯誤信息

@cl.on_message
async def on_message(message: cl.Message):
    """處理用戶消息"""
    # 獲取代理執行器
    agent_executor = cl.user_session.get("agent_executor")
    
    # 保存當前消息 ID 到用戶會話
    cl.user_session.set("message_id", message.id)
    
    # 在終端打印用戶訊息
    print(f"\n[用戶] {message.content}\n")
    
    if agent_executor is None:
        error_message = cl.Message(content="抱歉，MCP 客戶端尚未初始化，請重新開始對話。")
        await error_message.send()
        return
    
    # 創建響應消息
    response = cl.Message(content="思考中...")
    await response.send()
    
    try:
        print("-" * 40)
        print(f"開始處理問題: {message.content}")
        
        # 創建用於此消息的Chainlit回調處理器
        chainlit_callback = ChainlitStreamingCallbackHandler(response)
        
        # 為此次調用創建特定的回調管理器
        msg_callback_manager = CallbackManager([
            StreamingStdOutCallbackHandler(),  # 控制台輸出
            chainlit_callback  # Chainlit界面輸出
        ])
        
        # 執行代理並捕獲輸出
        print(f"\n===== 執行代理 - 處理用戶輸入: '{message.content}' =====")
        result = await agent_executor.ainvoke(
            {"input": message.content},
            {"callbacks": msg_callback_manager}
        )
        
        # 檢查結果結構
        print(f"代理執行結果keys: {result.keys()}")
        
        # 獲取最終輸出
        output = result.get("output", "沒有回應")
        
        # 記錄中間步驟
        if "intermediate_steps" in result:
            print("\n中間步驟詳情:")
            for i, step in enumerate(result["intermediate_steps"]):
                print(f"  步驟 {i+1}:")
                action = step[0]
                observation = step[1]
                print(f"    工具: {getattr(action, 'tool', 'unknown')}")
                print(f"    工具類型: {type(action).__name__}")
                print(f"    輸入: {getattr(action, 'tool_input', 'unknown')}")
                print(f"    輸入類型: {type(getattr(action, 'tool_input', None)).__name__}")
                print(f"    結果: {observation[:100]}..." if len(str(observation)) > 100 else f"    結果: {observation}")
                
        else:
            print("警告: 沒有中間步驟信息")
        
        # 在終端顯示 AI 回應
        print(f"\n[AI 最終回應]\n{output}\n")
        print("="*50)
        
        # 確保最終回應顯示完整
        response.content = output
        await response.update()
        
    except Exception as e:
        print(f"處理請求時出錯: {str(e)}")
        print(f"錯誤類型: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        
        # 更新消息內容
        response.content = f"處理您的請求時發生錯誤: {str(e)}"
        await response.update()

@cl.on_chat_end
async def on_chat_end():
    """聊天結束時的清理程序"""
    # 獲取 MCP 客戶端
    mcp_client = cl.user_session.get("mcp_client")
    if mcp_client:
        try:
            print("正在關閉 MCP 客戶端...")
            await mcp_client.__aexit__(None, None, None)
            print("MCP 客戶端已關閉")
        except Exception as e:
            print(f"關閉 MCP 客戶端時出錯: {str(e)}")
            import traceback
            traceback.print_exc()
    
    print("客戶端已關閉，MCP 伺服器仍在運行")

def add_upload_ppt_tool(tools):
    """將MCP的工具轉換為前端可用的格式，並添加本地PPT翻譯工具"""
    # 直接使用工具原有的描述，不做修改
    enhanced_tools = [deepcopy(tool) for tool in tools]
    
    # 使用pydantic BaseModel定義工具參數
    class TranslatePPTParams(BaseModel):
        olang: str = Field(
            None, 
            description="原始文件的語言", 
        )
        tlang: str = Field(
            None, 
            description="要翻譯成的目標語言", 
        )
    
    # 添加本地PPT翻譯工具 - 不再使用 name 參數
    @tool
    async def upload_and_translate_ppt(olang: str, tlang: str) -> str:
        """將PowerPoint檔案從一種語言翻譯為另一種語言。
        
        使用此工具讓用戶上傳PowerPoint檔案，並將其翻譯成指定的目標語言。
        系統會引導用戶上傳.pptx或.ppt檔案，然後進行翻譯處理。
        
        參數:
            olang: 原始語言，如 '英文'、'en'、'中文'、'zh-TW' 等
            tlang: 目標語言，如 '中文'、'zh-TW'、'英文'、'en' 等
        
        返回:
            翻譯結果的訊息以及檔案下載連結
        """
        print(f"正在處理 PPT 翻譯請求: 從 {olang} 到 {tlang}")
        
        try:
            # 調用處理函數
            result = await handle_ppt_translation(olang, tlang)
            return result
        except Exception as e:
            error_msg = f"處理翻譯請求時發生錯誤: {str(e)}"
            print(error_msg)
            return error_msg

    # 將工具添加到增強工具列表
    enhanced_tools.append(upload_and_translate_ppt)
    
    return enhanced_tools

# 處理PPT文件上傳和翻譯的函數
async def handle_ppt_translation(olang: str, tlang: str):
    """處理 PowerPoint 翻譯請求。
    
    參數:
        olang (str): 原始語言
        tlang (str): 目標語言
        
    返回:
        str: 翻譯結果消息
    """
    # 讓用戶上傳檔案
    file_msg = cl.AskFileMessage(
        content=f"請上傳要從{olang}翻譯到{tlang}的PowerPoint檔案。",
        accept=["application/vnd.ms-powerpoint", "application/vnd.openxmlformats-officedocument.presentationml.presentation"],
        max_size_mb=10,
        timeout=180
    )
    
    # 等待用戶上傳檔案
    file_response = await file_msg.send()
    
    # 檢查是否有上傳的檔案
    if not file_response:
        return "錯誤：未收到檔案或上傳超時，請稍後再試。"
    
    # AskFileResponse 處理
    if isinstance(file_response, list) and len(file_response) > 0:
        uploaded_file = file_response[0]
        file_name = uploaded_file.name
        file_path = uploaded_file.path
    else:
        return "錯誤：未能正確獲取上傳的檔案，請稍後再試。"
    
    # 確認檔案格式
    if not (file_name.lower().endswith('.pptx') or file_name.lower().endswith('.ppt')):
        return f"錯誤：不支援的檔案格式。請上傳.ppt或.pptx檔案，而不是 '{file_name}'。"
    
    # 通知用戶處理中
    await cl.Message(content=f"收到檔案 '{file_name}'，正在處理翻譯請求...").send()
    
    try:
        # 讀取文件內容
        with open(file_path, "rb") as f:
            file_content = f.read()
        
        # 將二進制文件內容轉換為 base64 字符串
        file_content_base64 = base64.b64encode(file_content).decode('utf-8')
        
        # 準備MCP客戶端調用參數
        params = {
            "olang": olang,
            "tlang": tlang,
            "file_content": file_content_base64,
            "file_name": file_name
        }
        
        # 獲取可用工具列表
        mcp_client = cl.user_session.get("mcp_client")
        tools = mcp_client.get_tools()
        translate_ppt_tool = None
        
        # 尋找翻譯工具
        for tool in tools:
            if tool.name == "translate_ppt":
                translate_ppt_tool = tool
                break
        
        # 調用翻譯工具
        if translate_ppt_tool:
            result = await translate_ppt_tool.ainvoke(params)
            
            # 檢查結果格式
            if isinstance(result, str):
                # 嘗試解析 JSON 字符串
                try:
                    result_dict = json.loads(result)
                    if result_dict.get("success", False):
                        # 從響應中提取文件內容和文件名
                        translated_file_content = result_dict.get("file_content")
                        translated_file_name = result_dict.get("file_name", "translated_document.pptx")
                        
                        # 將 base64 內容解碼為二進制
                        binary_content = base64.b64decode(translated_file_content)
                        
                        # 創建一個臨時文件
                        temp_dir = tempfile.gettempdir()
                        output_path = os.path.join(temp_dir, translated_file_name)
                        
                        with open(output_path, "wb") as f:
                            f.write(binary_content)
                        
                        # 創建文件元素 - 修改：明確設置mime類型
                        file_element = cl.File(
                            name=translated_file_name, 
                            path=output_path,
                            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation" 
                        )
                        
                        # 修改：先發送一個普通訊息
                        await cl.Message(content=f"翻譯完成！以下是翻譯後的檔案：").send()
                        
                        # 修改：單獨發送檔案元素
                        await file_element.send(for_id=None)
                        
                        return f"翻譯完成！已為您提供檔案 '{translated_file_name}' 的下載連結。"
                    else:
                        return f"翻譯錯誤：{result_dict.get('message', '未知錯誤')}"
                except json.JSONDecodeError:
                    # 不是 JSON 格式，直接返回
                    return result
            else:
                # 不是字符串形式的結果
                return f"翻譯完成，但結果格式異常：{str(result)}"
        else:
            return "無法找到翻譯工具，請確認 MCP 服務器已正確啟動。"
        
    except Exception as e:
        logging.exception("翻譯PPT時發生錯誤")
        return f"翻譯過程中發生錯誤: {str(e)}"

if __name__ == "__main__":
    try:
        # 直接從命令行運行時的入口
        cl.run()
    except KeyboardInterrupt:
        print("接收到鍵盤中斷，正在關閉客戶端...")
    finally:
        # 修改這裡，不要在結束時停止伺服器
        print("客戶端已關閉，MCP 伺服器仍在運行") 