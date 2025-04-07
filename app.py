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
    init_message = cl.Message(content="Connecting to MCP servers...")
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
        connected_message = cl.Message(content=f"Connected to the following MCP servers:\n{servers_info}")
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
        You are a powerful AI assistant capable of using various professional tools to help users solve problems.

        Tool Types and Usage Scenarios:

        1. 【Weather Query Tool】
        - Tool Name: "get_weather" or any tool name containing "weather"
        - Usage Scenario: Any questions related to weather, temperature, humidity, or weather forecasts
        - Input Format: {{"city": "City Name"}}
        - Input Example: {{"city": "Taipei"}}, {{"city": "Tokyo"}}, {{"city": "New York"}}
        - Trigger Words: "weather", "temperature", "humidity", "forecast", "rain"
        - Example Questions: "How is the weather in Taipei today?", "Will it rain tomorrow?", "What is the temperature in Tokyo?"
        - You MUST answer in the language used by the user.

        2. 【Database Query Tool】
        - Tool Name: "query_database" or any tool name containing "sql", "query", "database"
        - Usage Scenario: Any questions requiring data queries, statistics, or table content inspection
        - Input Format: {{"query": "SQL Query Statement"}}
        - Input Example: {{"query": "SELECT * FROM sales LIMIT 5"}}
        - Trigger Words: "data", "statistics", "sales", "how many", "query", "database", "table"
        - Example Questions: "Query recent sales data", "What products are available?", "How many apples were sold?", "What is the best-selling product?"
        - Database Schema:
            The database is including 'sales' table, with the following columns:
            - ID (VARCHAR): Sale record ID
            - Date (DATE): Sale date
            - Region (VARCHAR): Region, including: 関東, 関西
            - City (VARCHAR): City, including: 東京, 横浜, 埼玉, 千葉, 京都, 大阪, 神戸
            - Category (VARCHAR): Category, including: 野菜, 果物
            - Product (VARCHAR): Product name, including: キャベツ, 玉ねぎ, トマト, リンゴ, みかん, バナナ
            - Quantity (INT): Quantity
            - Unit_Price (DECIMAL): Unit price
            - Total_Price (DECIMAL): Total price
        - You MUST answer in the language used by the user.

        3. 【File Upload Translation Tool】
        - Tool Name: "upload_and_translate_ppt"
        - Usage Scenario: All requests requiring users to upload a local PowerPoint file for translation
        - Input Format: {{"olang": "Original Language", "tlang": "Target Language"}}
        - Input Example: {{"olang": "English", "tlang": "Chinese"}}
        - Mandatory Trigger Conditions: When the user mentions any of the following keywords, this tool MUST be called instead of just replying with text:
            - "translate PPT", "translate presentation", "translate PowerPoint", "PPT translation", "presentation translation"
            - "translate the PPT", "translate the presentation", "help me translate PPT", "help me translate presentation"
            - "PPT from X to Y", "presentation from X to Y" (where X and Y are any languages)
        - Note: When using this tool, the system will automatically prompt the user to upload the PPT file; do not send a separate text message requesting the upload.
        - Example Request: "Help me translate the ppt from English to Chinese" - In this case, call the tool directly with parameters {{"olang": "English", "tlang": "Chinese"}}

        4. 【Server-Side Translation Tool】
        - Tool Name: "translate_ppt"
        - Usage Scenario: User needs to translate a PowerPoint file that already exists on the server
        - Input Format: {{"olang": "Original Language", "tlang": "Target Language", "file_path": "File Path"}}
        - Input Example: {{"olang": "English", "tlang": "Chinese", "file_path": "/path/to/file.pptx"}}
        - Example Questions: "Translate the PPT file on the server", "Convert the existing presentation"
        - You MUST answer in the language used by the user.

        Important Principles:
        1. Tool Selection: Carefully analyze the user's question to determine the most appropriate tool type.
        2. Language Response: Respond in the language used by the user.
        3. No Guessing: For questions requiring data, the appropriate tool must be used; do not guess.
        4. JSON Format: All tool inputs must be in JSON format, not plain text strings.
        5. Choose the Correct PPT Translation Tool: Use upload_and_translate_ppt when the user needs to translate a local file; use translate_ppt when processing a file already on the server.
        6. Mandatory Tool Use: For requests mentioning "translate PPT", "translate presentation", etc., the tool must be used instead of just replying with text.

        Decision Flow:
        1. Analyze the user's question: Is it about weather? Data query? PPT translation?
        2. Select the corresponding tool category.
        3. Construct the input in the correct format.
        4. Execute the tool and return the result.

        Special Reminder:
        - For PPT translation requests, replying only with text without calling the tool is incorrect behavior.
        - The correct approach is to analyze the language information in the user's request (e.g., from English to Chinese) and then immediately call the upload_and_translate_ppt tool.
        - The upload_and_translate_ppt tool will automatically handle the subsequent file upload process; no additional prompts are needed.
        - You MUST answer in the language used by the user.
        """
        
        # prompt: The ReAct style prompt template. 
        # Including 5 parts: System Message, Chat History, User Message, ReAct Style Prompt and Agent Scratchpad
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            ("system", 
            """
            When the user requests PPT translation, the upload_and_translate_ppt tool MUST be used immediately, and not reply with a pure text message.
            Please process the user's question using the following format:
            Think: Analyze the user's question, determine which tool to use. Do not write out specific answers, but judge which tool to use to get information.
            For requests related to PPT translation, the upload_and_translate_ppt tool MUST be used, this tool will automatically handle the file upload and subsequent process.
            Action: Select the tool and use the appropriate JSON input parameters.
            Observation: Check the result returned by the tool.
            Action: May need to use another tool.
            Observation: Check the result returned by the new tool.
            Final response: Summarize all information and provide a complete response.
            """
  
            ),
            MessagesPlaceholder(variable_name="agent_scratchpad")
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
            verbose=False, # Don't show the agent's internal reasoning process
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
            Hello！I'm your Assistant Chatbot, Lisa👩‍💼. Please tell me what you need help with.
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