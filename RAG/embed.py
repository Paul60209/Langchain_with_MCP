import openai
import chromadb
import os
import re
import tiktoken # 用於估算 token 數
import uuid # 用於生成唯一的 ID

# --- 全域變數 ---
CHUNK_FILE = "RAG/data/tcc_chunks_sections_overlap.txt"
CHROMA_DB_PATH = "RAG/chroma_db" 
COLLECTION_NAME = "tcc_documents"

OPENAI_EMBEDDING_MODEL = "text-embedding-3-small" # OpenAI Embedding 模型
TIKTOKEN_ENCODING = "cl100k_base"    # text-embedding-3-small 使用的 encoding
EMBEDDING_BATCH_SIZE = 100           # 每次請求 OpenAI API 的批次大小
# ----------------

# --- 載入模型 ---
client = openai.OpenAI()
encoding = tiktoken.get_encoding(TIKTOKEN_ENCODING)

# --- 讀取 chunks ---
def load_chunks_from_file(filepath):
    """
    從指定檔案讀取 chunks。
    參數:
        filepath (str): 檔案路徑。
    返回:
        list[str]: 包含 chunk 文本的列表。
    """
    chunks = []
    current_chunk_lines = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith("--- Chunk") and line.strip().endswith("---"):
                    if current_chunk_lines:
                        chunk_text = "".join(current_chunk_lines).strip()
                        if chunk_text: # 確保不添加空 chunk
                            chunks.append(chunk_text)
                        current_chunk_lines = []
                elif line.strip(): # 只添加非空行
                    current_chunk_lines.append(line)

            # 處理檔案末尾最後一個 chunk
            if current_chunk_lines:
                 chunk_text = "".join(current_chunk_lines).strip()
                 if chunk_text:
                    chunks.append(chunk_text)

        print(f"成功從 {filepath} 讀取 {len(chunks)} 個 chunks。")
        return chunks
    except FileNotFoundError:
        print(f"錯誤：找不到 chunk 檔案 {filepath}")
        return None
    except Exception as e:
        print(f"讀取 chunk 檔案時發生錯誤: {e}")
        return None

# --- 獲取 Embeddings ---
def get_embeddings_for_chunks(texts, batch_size=100):
    """
    為 chunk 文本列表獲取 embedding 向量，支持分批處理。
    參數:
        texts (list[str]): chunk 文本列表。
        batch_size (int): 每次請求 OpenAI API 的批次大小。
    返回:
        list[list[float]] | None: embedding 向量的列表，若失敗則返回 None。
    """
    all_embeddings = []
    if not texts:
        return []

    total_tokens = 0
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i:i + batch_size]
        batch_tokens = sum(len(encoding.encode(text)) for text in batch_texts)
        total_tokens += batch_tokens
        print(f"正在獲取第 {i // batch_size + 1} 批 chunks (數量: {len(batch_texts)}, Tokens: {batch_tokens}) 的 embeddings...")
        try:
            response = client.embeddings.create(input=batch_texts, model=OPENAI_EMBEDDING_MODEL)
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)
        except openai.APIError as e:
            print(f"  - OpenAI API 返回錯誤: {e}")
            return None
        except Exception as e:
            print(f"  - 獲取 embedding 時發生錯誤: {e}")
            return None

    print(f"總共成功獲取 {len(all_embeddings)} 個 chunks 的 embedding。總 Token 數: {total_tokens}")
    return all_embeddings

# --- 儲存到 Chroma DB ---
def store_in_chroma(chunks, embeddings, db_path, collection_name):
    """
    將 chunks 和 embeddings 儲存到 Chroma DB。
    參數:
        chunks (list[str]): 文本 chunk 列表。
        embeddings (list[list[float]]): 對應的 embedding 列表。
        db_path (str): Chroma 持久化儲存路徑。
        collection_name (str): Chroma Collection 名稱。
    返回:
        chromadb.Collection | None: 創建或獲取的 Collection，若失敗則返回 None。
    """
    if not chunks or not embeddings or len(chunks) != len(embeddings):
        print("錯誤：chunks 或 embeddings 為空，或數量不匹配。")
        return None

    print(f"\n--- 開始儲存到 Chroma DB ---")
    print(f"資料庫路徑: {db_path}")
    print(f"Collection 名稱: {collection_name}")

    try:
        # 創建一個持久化的 Chroma Client
        persistent_client = chromadb.PersistentClient(path=db_path)

        # 獲取或創建 Collection
        # 注意：Chroma 預設使用自己的 embedding function (ef)，
        # 但我們已經自行生成了 embeddings，所以不需要它。
        # 我們需要確保創建 Collection 時不指定 embedding function，或使用虛擬的。
        # 最簡單的方式是直接添加數據時提供 embeddings。
        collection = persistent_client.get_or_create_collection(name=collection_name)
        print(f"成功獲取或創建 Collection: '{collection.name}'")


        # 為每個 chunk 生成唯一的 ID
        ids = [str(uuid.uuid4()) for _ in chunks]

        # 添加數據到 Collection
        # Chroma 的 add 方法可以批量添加
        # documents 對應文本 chunks
        # embeddings 對應向量
        # ids 對應唯一標識符
        # 注意：如果 Collection 已存在且包含相同 ID，add 會更新數據
        print(f"正在將 {len(chunks)} 個項目添加到 Chroma Collection...")
        collection.add(
            embeddings=embeddings,
            documents=chunks,
            ids=ids
        )

        count = collection.count()
        print(f"添加完成！Collection '{collection_name}' 現在包含 {count} 個項目。")
        return collection

    except Exception as e:
        print(f"儲存到 Chroma DB 時發生錯誤: {e}")
        import traceback
        traceback.print_exc() # 打印詳細錯誤
        return None

if __name__ == "__main__":
    # 1. 從檔案讀取之前生成的 chunks
    text_chunks = load_chunks_from_file(CHUNK_FILE)
    if not text_chunks:
        print("未能讀取 chunks，程式終止。")
        exit()

    # 2. 為所有 chunks 獲取 Embeddings
    print("\n--- 開始獲取 Embeddings ---")
    chunk_embeddings = get_embeddings_for_chunks(text_chunks, batch_size=EMBEDDING_BATCH_SIZE)
    if chunk_embeddings is None:
         print("獲取 embeddings 失敗，程式終止。")
         exit()

    # 3. 將數據儲存到 Chroma DB
    collection = store_in_chroma(text_chunks, chunk_embeddings, CHROMA_DB_PATH, COLLECTION_NAME)

    if collection:
        print("\n--- 處理完成 ---")
        print(f"路徑: {CHROMA_DB_PATH}")
        print(f"Collection: {COLLECTION_NAME}")

        # print("\n--- simple test (query '低碳水泥' top 3 related chunks) ---")
        # try:
        #     results = collection.query(
        #         query_texts=["低碳水泥"],
        #         n_results=3
        #     )
        #     print("Query Result:")
        #     if results and results.get('documents'):
        #         for i, doc in enumerate(results['documents'][0]):
        #             print(f"  - result {i+1} (ID: {results['ids'][0][i]}):")
        #             print(f"    {doc[:200]}...") # show top 200
        #             print(f"    (Distance: {results['distances'][0][i]:.4f})") # distance
        #     else:
        #         print("  - no related results found.")
        # except Exception as e:
        #     print(f"  - query error: {e}")

    else:
        print("\n--- 處理失敗 ---")
        print("未能將數據儲存到 Chroma DB。請檢查錯誤訊息。")
