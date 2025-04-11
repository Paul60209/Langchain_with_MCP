import os
import dotenv
import argparse
import json
from typing import List, Dict, Any
import chromadb
from mcp.server.fastmcp import FastMCP
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from mcp.server.sse import SseServerTransport
import logging
import traceback
from chromadb.utils import embedding_functions
import openai

# --- 加入Server Logs ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) #<-- 獲取腳本所在目錄
LOG_FILE = os.path.join(SCRIPT_DIR, "rag_server.log")  #<-- 使用絕對路徑

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

# --- 全域變數 ---
DEFAULT_PORT = 8004

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") 
OPENAI_EMBEDDING_MODEL_NAME = "text-embedding-3-small" # <-- 與 embed.py 保持一致

CHROMA_DB_PATH = "RAG/chroma_db"
COLLECTION_NAME = "tcc_documents"

N_RESULTS = 3
# ----------------

dotenv.load_dotenv()

# 解析命令列參數，並設定port
parser = argparse.ArgumentParser(description='RAG MCP Server using ChromaDB')
parser.add_argument('--port', type=int, default=DEFAULT_PORT, help=f'Server listening port (default: {DEFAULT_PORT})')
args = parser.parse_args()
os.environ["MCP_SSE_PORT"] = str(args.port)

# 初始化 MCP Server
mcp = FastMCP("rag_server")

# 初始化 OpenAI Embedding
openai_ef = None
try:
    # 使用 ChromaDB 內建的輔助函數來創建 Embedding Function
    openai_ef = embedding_functions.OpenAIEmbeddingFunction(
        api_key=OPENAI_API_KEY,
        model_name=OPENAI_EMBEDDING_MODEL_NAME
    )
    logging.info(f"已初始化 OpenAI Embedding Function，使用模型: {OPENAI_EMBEDDING_MODEL_NAME}")
except NameError as ne:
    # 特別捕捉 NameError，通常是因為 import 失敗
    logging.error(f"初始化 OpenAI Embedding Function 時發生 NameError (可能缺少 import): {ne}")
    logging.exception("詳細錯誤資訊:")
except Exception as e:
    logging.error(f"初始化 OpenAI Embedding Function 時發生錯誤: {e}")
    logging.exception("詳細錯誤資訊:")

# 初始化 ChromaDB Client 和 Collection
collection = None
try:
    logging.info(f"正在初始化 ChromaDB Client，路徑: {CHROMA_DB_PATH}")
    persistent_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    logging.info("ChromaDB Client 初始化成功。")

    logging.info(f"正在獲取 Collection: '{COLLECTION_NAME}'")
    collection = persistent_client.get_collection(name=COLLECTION_NAME)
    logging.info(f"成功獲取 Collection '{collection.name}', 包含 {collection.count()} 個項目。")
except Exception as e:
    logging.error(f"錯誤：初始化 ChromaDB 或獲取 Collection 時失敗: {e}")
    logging.exception("詳細錯誤資訊:")
    logging.error("請確保 RAG/chroma_db 資料夾存在且包含有效的 Collection。伺服器將無法處理 RAG 請求。")

# 格式化檢索結果
def format_retrieved_docs(results: Dict[str, Any]) -> str:
    """
    將 ChromaDB 檢索結果格式化為單一字串。
    參數:
        results (Dict[str, Any]): ChromaDB collection.query 的返回結果。
    返回:
        str: 格式化後的文本，包含多個檢索到的文件片段。
    """
    documents = results.get('documents', [[]])[0] # results['documents'] 是 [[doc1, doc2,...]]
    distances = results.get('distances', [[]])[0] # results['distances'] 是 [[dist1, dist2,...]]
    ids = results.get('ids', [[]])[0]             # results['ids'] 是 [[id1, id2,...]]

    if not documents:
        return "抱歉，找不到相關的文件片段。"

    formatted_output = "根據資料庫，找到以下相關資訊：\n\n"
    for i, doc in enumerate(documents):
        formatted_output += f"--- 相關片段 {i+1} (ID: {ids[i]}, Distance: {distances[i]:.4f}) ---\n"
        formatted_output += f"{doc}\n\n"

    return formatted_output.strip()

@mcp.tool()
async def retrieve_tcc_docs(query: str) -> str:
    """
    在台泥內部文件中檢索與使用者查詢相關的資訊。

    ## 使用情境
    - 當使用者詢問關於台泥的歷史、政策、ESG報告、經營者的話、產品資訊等內部知識時使用。
    - 用於回答無法直接透過常識或天氣/數據庫查詢工具回答的台泥相關問題。

    ## 參數說明
    :param query: 使用者的自然語言查詢 (例如：「台泥的環保政策是什麼？」、「介紹一下台泥的歷史」、「經營者的話提到什麼重點？」)。

    ## 輸入範例
    - "台泥 ESG"
    - "水泥的低碳轉型"
    - "辜成允董事長做了什麼"

    ## 注意事項
    - 這個工具會從內部的文本資料庫中尋找最相關的文件片段。
    - 返回的結果是多個相關片段的組合。

    :return: 包含多個相關文件片段的格式化字串。
    """
    logging.info(f"接收到 RAG 查詢: '{query}'")
    if not query:
        return "錯誤：查詢內容不能為空。"

    # 再次檢查 Collection 和 Embedding Function 是否已成功初始化
    if collection is None:
        logging.error("RAG 工具無法使用：ChromaDB Collection 未成功初始化。")
        return "抱歉，後端文件資料庫連接失敗，暫時無法查詢。"
    if openai_ef is None:
        logging.error("RAG 工具無法使用：OpenAI Embedding Function 未成功初始化 (可能是 API Key 或 import 問題)。")
        return "抱歉，後端 Embedding 功能連接失敗，暫時無法查詢。"

    try:
        # 步驟 1: 使用指定的 OpenAI Embedding Function 生成查詢向量
        logging.info(f"正在為查詢 '{query}' 生成 Embedding，使用模型: {OPENAI_EMBEDDING_MODEL_NAME}")
        query_embedding = openai_ef([query])

        # 檢查 Embedding 是否成功生成 (應返回 [[float, ...]])
        embedding_vector = None
        if query_embedding and len(query_embedding) > 0:
            embedding_vector = query_embedding[0]
        
        # 檢查內部向量是否有效 (適用於 list 或 numpy array)
        if embedding_vector is None or len(embedding_vector) == 0:
            logging.error("無法為查詢生成有效的 Embedding。請檢查 OpenAI API Key 和網路連線。")
            return "錯誤：無法為查詢生成有效的 Embedding。"
        # --- 檢查結束 --- 

        logging.info(f"查詢 Embedding 生成成功，維度: {len(embedding_vector)}")

        # 步驟 2: 使用 query_embeddings 進行檢索
        logging.info("正在使用 query_embeddings 進行 ChromaDB 查詢...")
        results = collection.query(
            query_embeddings=query_embedding,
            n_results=N_RESULTS,
            include=["documents", "distances"]
        )

        logging.info(f"檢索到 {len(results.get('documents', [[]])[0])} 個結果。")

        # 步驟 3: 格式化結果
        formatted_result = format_retrieved_docs(results)
        logging.info(f"返回結果:\n{formatted_result}") 
        return formatted_result

    except chromadb.errors.InvalidArgumentError as ive:
        logging.error(f"ChromaDB 參數錯誤 (可能是維度不匹配): {ive}")
        logging.exception("詳細錯誤資訊:")
        return f"抱歉，文件庫查詢時發生參數錯誤：{ive}。請聯繫管理員檢查 Embedding 設定。"
    except openai.RateLimitError as rle:
        logging.error(f"OpenAI API Rate Limit Exceeded: {rle}")
        return "抱歉，查詢過於頻繁，請稍後再試。"
    except openai.AuthenticationError as ae:
        logging.error(f"OpenAI API Authentication Error: {ae}")
        return "抱歉，後端 OpenAI API Key 設定錯誤，無法執行查詢。"
    except Exception as e:
        logging.error(f"執行 RAG 檢索時發生未知錯誤: {e}")
        logging.exception("詳細錯誤資訊:")
        return f"抱歉，檢索文件時發生未知的內部錯誤。"
# ----------------

if __name__ == "__main__":
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from mcp.server.sse import SseServerTransport
    
    logging.info(f"啟動 RAG Server 於埠號 {args.port}")
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
