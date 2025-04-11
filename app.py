import os
import asyncio
import chainlit as cl
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.memory import ConversationBufferMemory
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.callbacks.manager import CallbackManager
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain.callbacks.base import BaseCallbackHandler
from mcp_server_config import SERVER_CONFIGS # Import shared config

import base64
import tempfile
from copy import deepcopy
from langchain_community.tools import tool
from langchain_core.pydantic_v1 import BaseModel, Field
import json
import logging # Added missing import

# load environment variables
load_dotenv()
OPENAI_MODEL = os.getenv("MODEL", "gpt-4o-mini")

async def create_mcp_client_with_retry(client_config, max_retries=3):
    """
    Try to create MCP client, retry if failed
    
    Args:
        client_config: MCP client config
        max_retries: max retry times
        
    Returns:
        tuple: (client, tools) or (None, None)
    """
    for attempt in range(max_retries):
        try:
            mcp_client = MultiServerMCPClient(client_config)
            await mcp_client.__aenter__()
            
            #try to get tools list, verify connection success
            try:
                tools = mcp_client.get_tools()
                if not tools:
                    print("Warning: tools list is empty")
                    tools = []
                return mcp_client, tools
            except Exception as tool_error:
                print(f"Failed to get tools list: {tool_error}")
                # try to exit gracefully
                try:
                    await mcp_client.__aexit__(None, None, None)
                except Exception as exit_error:
                    print(f"Client exit error: {exit_error}")
                raise tool_error
                
        except Exception as e:
            print(f"Failed to create MCP client (attempt {attempt+1}/{max_retries}): {e}")

            # if not the last attempt, wait for a while and retry
            if attempt < max_retries - 1:
                await asyncio.sleep(3)
    
    return None, None

# function to load server config from file
def load_server_config():
    """Load server config from file"""
    config_file = "server_config.txt"
    if not os.path.exists(config_file):
        print(f"Can't find config file {config_file}, using default config")
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
                print(f"Invalid config line: {line}")
                continue
            
            name, port, transport = parts
            if name in SERVER_CONFIGS:
                SERVER_CONFIGS[name]["port"] = int(port)
                SERVER_CONFIGS[name]["transport"] = transport
        
        return True
    except Exception as e:
        print(f"Error loading config file: {e}")
        return False

# custom callback handler, to stream output to Chainlit message
class ChainlitStreamingCallbackHandler(BaseCallbackHandler):
    """Stream LLM output to Chainlit message"""
    
    def __init__(self, cl_response_message):
        self.cl_response_message = cl_response_message
        self.tokens = []
        
    def on_llm_new_token(self, token: str, **kwargs):
        """Process new tokens"""
        self.tokens.append(token)
        # update the message on the UI
        content = "".join(self.tokens)
        asyncio.create_task(self.cl_response_message.update(content=content))
        
    def on_llm_end(self, response, **kwargs):
        """Process LLM response end"""
        self.tokens = []

@cl.on_chat_start
async def on_chat_start():
    """Initialization program when chat starts"""
    
    # show the initialization message
    init_message = cl.Message(content="連接後端伺服器中...")
    await init_message.send()
    
    # load server config
    load_server_config()
    
    # create MCP client config
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
    
    # initialize MCP client (with retry)
    try:
        connecting_message = cl.Message(content="Connecting to MCP servers...")
        await connecting_message.send()
        mcp_client, tools = await create_mcp_client_with_retry(client_config)
        
        if not mcp_client or not tools:
            error_message = cl.Message(content="Failed to connect to MCP servers. Please ensure MCP servers are running (using run_server.py).")
            await error_message.send()
            return
        
        # save the client to the session
        cl.user_session.set("mcp_client", mcp_client)
        
        # add "PPT upload translation tool
        enhanced_tools = add_upload_ppt_tool(tools)
        
        
        # show the connected servers
        servers_info = "\n".join([f"- {name} (port: {config['port']})" for name, config in SERVER_CONFIGS.items()])
        connected_message = cl.Message(content=f"已經連結到以下伺服器:\n{servers_info}")
        await connected_message.send()
        
        # set the callback manager
        callback_manager = CallbackManager([
            StreamingStdOutCallbackHandler(),  # show the streaming output on console
        ])
        
        # update the model config, use specific version and add the callback manager
        llm = ChatOpenAI(
            model=OPENAI_MODEL,
            temperature=0,  # Make sure the LLM focus on higtest priority
            streaming=True,
            callback_manager=callback_manager,
            verbose=False # Don't show the LLM's internal reasoning process
        )
        memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
        system_message = """
你是台泥集團內部知識庫的智能問答助理，名叫「TCC AI助理」。你的主要任務是利用可用的工具來回答使用者關於台泥的問題。

你擁有多種工具來獲取資訊：

1.  **台泥文件檢索工具 (retrieve_tcc_docs)**：
    *   **用途**：當使用者詢問關於**台泥 (TCC)** 的內部資訊時，這是你的**主要工具**。例如：公司歷史、ESG 政策、經營理念、年度報告、產品規格、董事長談話、組織架構、內部規章等。
    *   **如何使用**：直接將使用者的自然語言查詢作為參數 `query` 傳遞給工具。
    *   **範例**：使用者問「台泥的 ESG 報告有哪些重點？」，你應該呼叫 `retrieve_tcc_docs(query="台泥的 ESG 報告有哪些重點？")`。
    *   **輸出處理**：工具會返回多個相關的文件片段。你需要仔細閱讀這些片段，**綜合資訊並用自己的話**、**以使用者提問的語言**來回答問題。**不要直接原文照搬返回的片段**。
    *   **觸發關鍵字**：台泥、TCC、公司、集團、歷史、政策、ESG、永續、環保、報告、經營、理念、產品、水泥、低碳、能源、轉型、供應商、人權、董事長、辜成允、張安平、內部稽核、公司治理... (以及其他與台泥業務、歷史、文化相關的詞彙)

2.  **資料庫查詢工具 (query_database / sql_query)**：
    *   **用途**：回答需要查詢結構化數據的問題，例如銷售數據、產品庫存等。
    *   **如何使用**：你需要將使用者的問題轉換成 **SQL 查詢語句** 作為參數 `query` 傳遞。
    *   **範例**：使用者問「查詢關東地區的蘋果銷售總量」，你應該呼叫 `query_database(query="SELECT SUM(Quantity) FROM sales WHERE Region = '関東' AND Product = 'リンゴ'")`。
    *   **資料庫結構 (Schema)**: (你需要知道有哪些表格和欄位才能寫出正確的 SQL)
        *   `sales` 表格: `ID`, `Date`, `Region` (関東, 関西), `City` (東京, 横浜, ...), `Category` (野菜, 果物), `Product` (キャベツ, リンゴ, ...), `Quantity`, `Unit_Price`, `Total_Price`
    *   **觸發關鍵字**：數據、統計、查詢、銷售、庫存、多少、最...的、列表、表格。

3.  **PPT 上傳翻譯工具 (upload_and_translate_ppt)**：
    *   **用途**：當使用者明確表示要**上傳本地的 PowerPoint (.ppt 或 .pptx) 檔案**並進行翻譯時使用。
    *   **如何使用**：你需要從使用者請求中提取**原始語言 (olang)** 和**目標語言 (tlang)**。
    *   **範例**：使用者說「幫我把這個 PPT 從英文翻成日文」，你應該呼叫 `upload_and_translate_ppt(olang="英文", tlang="日文")`。系統會自動提示使用者上傳檔案。
    *   **強制觸發**：只要提到「翻譯 PPT/簡報/PowerPoint」、「上傳 PPT/簡報翻譯」等類似字眼，**必須**使用此工具。
    *   **注意**：**不要**自己發訊息要求使用者上傳，工具會處理。

4.  **伺服器端 PPT 翻譯工具 (translate_ppt)**：
    *   **用途**：當使用者需要翻譯**已經存在於伺服器上**的 PowerPoint 檔案時使用。
    *   **如何使用**：需要提供**原始語言 (olang)**、**目標語言 (tlang)** 和**伺服器上的檔案路徑 (file_path)**。
    *   **範例**：使用者說「翻譯伺服器上 `/shared/report.pptx` 這個檔案，從中文到英文」，你應該呼叫 `translate_ppt(olang="中文", tlang="英文", file_path="/shared/report.pptx")`。

5.  **天氣查詢工具 (get_weather / query_weather)**：
    *   **用途**：回答關於特定城市的天氣狀況的問題。
    *   **如何使用**：提供**城市名稱 (city)**。
    *   **範例**：使用者問「倫敦現在天氣怎麼樣？」，你應該呼叫 `get_weather(city="London")`。
    *   **觸發關鍵字**：天氣、溫度、濕度、下雨、預報。

**通用處理原則**：
*   **優先級**：當問題**同時**涉及台泥內部資訊和其他方面 (如數據查詢) 時，**優先考慮使用 `retrieve_tcc_docs`** 來獲取最權威的內部答案。如果 `retrieve_tcc_docs` 沒有提供足夠的資訊，再考慮其他工具。
*   **澄清**：如果使用者的問題不明確，或者不確定該使用哪個工具，可以向使用者提問以澄清意圖。
*   **語言**：**始終使用使用者提問時所用的語言**來回答。
*   **誠實**：如果使用工具後仍然找不到答案，或者工具執行失敗，請告知使用者你無法找到相關資訊或遇到了問題。
*   **拒絕不相關請求**：你的主要職責是利用工具回答與台泥相關或工具能處理的問題。對於閒聊、寫詩、編故事等與工具無關的請求，應禮貌地拒絕。
"""
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        # Create the agent
        agent = create_openai_tools_agent(
            llm=llm,
            tools=enhanced_tools,
            prompt=prompt
        )
        
        # Create the agent executor
        agent_executor = AgentExecutor(
            agent=agent,
            tools=enhanced_tools,
            memory=memory,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=3,
            early_stopping_method="force",
            return_intermediate_steps=True # Show the intermediate steps on chainlit UI
        )
        
        # Save the agent executor to the user session
        cl.user_session.set("agent_executor", agent_executor)
        
        # Send the welcome message
        welcome_message = cl.Message(content=
            """
            您好！我是您的台泥小助理, 小泥👩‍💼. 有任何問題都歡迎向我詢問喔😊.
            """)
        await welcome_message.send()
    
    except Exception as e:
        error_message = cl.Message(content=f"Error initializing MCP client: {str(e)}")
        await error_message.send()
        import traceback
        traceback.print_exc()  # print the full error info on server side

@cl.on_message
async def on_message(message: cl.Message):
    """Process user message"""
    # get the agent executor
    agent_executor = cl.user_session.get("agent_executor")
    
    # save the current message ID to the user session
    cl.user_session.set("message_id", message.id)
    
    # print the user message on console
    print(f"\n[User] {message.content}\n")
    
    if agent_executor is None:
        error_message = cl.Message(content="Sorry, the MCP client is not initialized yet. Please start the conversation again.")
        await error_message.send()
        return
    
    # create the response message
    response = cl.Message(content="Thinking...")
    await response.send()
    
    try:
        print("-" * 40)
        print(f"Start processing the question: {message.content}")
        
        # create the Chainlit callback handler for this message
        chainlit_callback = ChainlitStreamingCallbackHandler(response)
        
        # create the specific callback manager for this invocation
        msg_callback_manager = CallbackManager([
            StreamingStdOutCallbackHandler(),  # console output
            chainlit_callback  # Chainlit UI output
        ])
        
        # execute the agent and capture the output
        print(f"\n===== Execute agent - Process user input: '{message.content}' =====")
        result = await agent_executor.ainvoke(
            {"input": message.content},
            {"callbacks": msg_callback_manager}
        )
        
        # check the result structure
        print(f"Agent execution result keys: {result.keys()}")
        
        # get the final output
        output = result.get("output", "No response")
        
        # display the AI response on console
        print(f"\n[AI final response]\n{output}\n")
        print("="*50)
        
        # ensure the final response is displayed completely
        response.content = output
        await response.update()
        
    except Exception as e:
        print(f"Error processing the request: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        
        # update the message content
        response.content = f"Error processing your request: {str(e)}"
        await response.update()

@cl.on_chat_end
async def on_chat_end():
    """Clean up the program when the chat ends"""
    # get the MCP client
    mcp_client = cl.user_session.get("mcp_client")
    if mcp_client:
        try:
            print("Closing the MCP client...")
            await mcp_client.__aexit__(None, None, None)
            print("MCP client closed")
        except Exception as e:
            print(f"Error closing the MCP client: {str(e)}")
            import traceback
            traceback.print_exc()
    
    print("Client closed, MCP server still running")

def add_upload_ppt_tool(tools):
    """Convert MCP tools to the format that can be used by the frontend, and add the local PPT translation tool"""
    # directly use the original description of the tool, without modification
    enhanced_tools = [deepcopy(tool) for tool in tools]
    
    # use pydantic BaseModel to define the tool parameters
    class TranslatePPTParams(BaseModel):
        olang: str = Field(
            None, 
            description="The language of the original file", 
        )
        tlang: str = Field(
            None, 
            description="The target language to translate to", 
        )
    
    # add the local PPT translation tool
    @tool
    async def upload_and_translate_ppt(olang: str, tlang: str) -> str:
        """Translate a PowerPoint file from one language to another.
        
        Use this tool to let the user upload a PowerPoint file, and translate it to the specified target language.
        The system will guide the user to upload a .pptx or .ppt file, and then process the translation.
        
        Parameters:
            olang: The original language, e.g. 'English', 'en', 'Chinese', 'zh-TW' etc.
            tlang: The target language, e.g. 'Chinese', 'zh-TW', 'English', 'en' etc.
        
        Returns:
            The message of the translation result and the file download link
        """
        print(f"Processing the PPT translation request: from {olang} to {tlang}")
        
        try:
            # call the processing function
            result = await handle_ppt_translation(olang, tlang)
            return result
        except Exception as e:
            error_msg = f"Error processing the translation request: {str(e)}"
            print(error_msg)
            return error_msg

    # add the tool to the enhanced tools list
    enhanced_tools.append(upload_and_translate_ppt)
    
    return enhanced_tools

# Process the PPT file upload and translation function
async def handle_ppt_translation(olang: str, tlang: str):
    """Process the PowerPoint translation request.
    
    Parameters:
        olang (str): The original language
        tlang (str): The target language
        
    Returns:
        str: The message of the translation result
    """
    # let the user upload the file
    file_msg = cl.AskFileMessage(
        content=f"Please upload the PowerPoint file to be translated from {olang} to {tlang}.",
        accept=["application/vnd.ms-powerpoint", "application/vnd.openxmlformats-officedocument.presentationml.presentation"],
        max_size_mb=10,
        timeout=180
    )
    
    # wait for the user to upload the file
    file_response = await file_msg.send()
    
    # check if there is an uploaded file
    if not file_response:
        return "Error: No file received or upload timeout, please try again later."
    
    # AskFileResponse processing
    if isinstance(file_response, list) and len(file_response) > 0:
        uploaded_file = file_response[0]
        file_name = uploaded_file.name
        file_path = uploaded_file.path
    else:
        return "Error: Unable to correctly obtain the uploaded file, please try again later."
    
    # confirm the file format
    if not (file_name.lower().endswith('.pptx') or file_name.lower().endswith('.ppt')):
        return f"Error: Unsupported file format. Please upload a .ppt or .pptx file, not '{file_name}'."
    
    # notify the user that the processing is in progress
    processing_msg = cl.Message(content=f"Received file '{file_name}', processing the translation request...")
    await processing_msg.send()
    
    try:
        # read the file content
        with open(file_path, "rb") as f:
            file_content = f.read()
        
        # convert the binary file content to a base64 string
        file_content_base64 = base64.b64encode(file_content).decode('utf-8')
        
        # prepare the MCP client invocation parameters
        params = {
            "olang": olang,
            "tlang": tlang,
            "file_content": file_content_base64,
            "file_name": file_name
        }
        
        # get the available tools list
        mcp_client = cl.user_session.get("mcp_client")
        tools = mcp_client.get_tools()
        translate_ppt_tool = None
        
        # find the translation tool
        for tool in tools:
            if tool.name == "translate_ppt":
                translate_ppt_tool = tool
                break
        
        # call the translation tool
        if translate_ppt_tool:
            result = await translate_ppt_tool.ainvoke(params)
            
            # check the result format
            if isinstance(result, str):
                # try to parse the JSON string
                try:
                    result_dict = json.loads(result)
                    if result_dict.get("success", False):
                        # extract the file content and file name from the response
                        translated_file_content = result_dict.get("file_content")
                        translated_file_name = result_dict.get("file_name", "translated_document.pptx")
                        
                        # decode the base64 content to binary
                        binary_content = base64.b64decode(translated_file_content)
                        
                        # create a temporary file
                        temp_dir = tempfile.gettempdir()
                        output_path = os.path.join(temp_dir, translated_file_name)
                        
                        with open(output_path, "wb") as f:
                            f.write(binary_content)
                        
                        # create a file element and send it in the message
                        file_element = cl.File(
                            name=translated_file_name,
                            path=output_path,
                            display="inline"  # use inline display
                        )
                        
                        # send the message with the element list
                        await cl.Message(
                            content="Translation completed! Here is the translated file:",
                            elements=[file_element]
                        ).send()
                        
                        return f"You can click the file link above to download the translated file '{translated_file_name}'."
                    else:
                        return f"Translation error: {result_dict.get('message', 'Unknown error')}"
                except json.JSONDecodeError:
                    # not JSON format, return directly
                    return result
            else:
                # not a string result
                return f"Translation completed, but the result format is abnormal: {str(result)}"
        else:
            return "Unable to find the translation tool, please ensure the MCP server is correctly started."
        
    except Exception as e:
        logging.exception("Error occurred during PPT translation")
        return f"Error occurred during PPT translation: {str(e)}"

if __name__ == "__main__":
    try:
        # the entry when running directly from the command line
        cl.run()
    except KeyboardInterrupt:
        print("Received keyboard interrupt, closing the client...")
    finally:
        # modify here, don't stop the server when ending
        print("Client closed, MCP server still running") 