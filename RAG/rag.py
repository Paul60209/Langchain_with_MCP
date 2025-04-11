import spacy
import openai
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import matplotlib.pyplot as plt
import os
import re
import tiktoken

# --- 全域變數 ---
INPUT_FILE = "RAG/data/TCC.txt"
OUTPUT_CHUNKS_FILE = "RAG/data/tcc_chunks_sections_overlap.txt"

OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"  # OpenAI Embedding 模型 -> 用來獲取文本的向量
TIKTOKEN_ENCODING = "cl100k_base" # text-embedding-3-small 使用的 encoding -> 用來計算 token 數
SPACY_MODEL = "zh_core_web_sm"    # spaCy 中文模型 -> 用來處理中文斷句

SIMILARITY_THRESHOLD = 0.7 
MIN_CHUNK_SENTENCES = 3 
MAX_CHUNK_SENTENCES = 15
OVERLAP_SENTENCES = 2 
SECTION_SEPARATOR = "________________" 

# --- 載入模型 ---
nlp = spacy.load(SPACY_MODEL)  # 載入 spaCy 的繁體中文模型
client = openai.OpenAI()  # 載入 OpenAI API
encoding = tiktoken.get_encoding(TIKTOKEN_ENCODING)  # 載入 tiktoken


# --- 文本處理 ---
def read_text_file(filepath):
    """
    讀取指定的文本檔案。
    參數:
        filepath (str): 檔案路徑。
    返回:
        str: 檔案內容，若讀取失敗則返回 None。
    """
    try:
        # 讀取文本檔案內容，使用 utf-8 編碼
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            print(f"成功讀取檔案: {filepath}")
            return content
    except FileNotFoundError:
        print(f"錯誤：找不到檔案 {filepath}")
        return None
    except Exception as e:
        print(f"讀取檔案時發生錯誤: {e}")
        return None

def clean_text_section(text):
    """
    清理單個文本段落，移除多餘的空白和特殊標記。
    注意：此函數假定分隔符已被移除。
    參數:
        text (str): 原始文本段落。
    返回:
        str: 清理後的文本段落。
    """
    text = re.sub(r'\n\s*\n', '\n', text).strip() # 移除多餘的空行和前後空白
    text = re.sub(r'^\s*[\*•-]\s+', '', text, flags=re.MULTILINE) # 移除單獨存在的列表標記符號 (例如 *)，但保留其後的文字
    text = re.sub(r'\s+', ' ', text).strip() # 將多個空格替換為單個空格
    text = text.replace(SECTION_SEPARATOR, '').strip() # 移除可能殘留的分隔符
    return text

def split_into_sentences(text):
    """
    使用 spaCy 將文本分割成句子列表。
    參數:
        text (str): 要分割的文本。
    返回:
        list[str]: 句子列表，過濾掉空句子。
    """
    doc = nlp(text) # 使用 spaCy 處理文本
    sentences = [sent.text.strip() for sent in doc.sents if sent.text.strip()] # 提取句子文本，並過濾掉只包含空白的句子
    return sentences

# --- 獲取 Embeddings ---
def get_embeddings(texts):
    """
    使用 OpenAI API 獲取文本列表的 embedding 向量。
    參數:
        texts (list[str]): 文本句子列表。
    返回:
        numpy.ndarray: embedding 向量的 numpy 陣列，若失敗則返回 None。
    """
    if not texts:
        return None
    try:
        response = client.embeddings.create(input=texts, model=OPENAI_EMBEDDING_MODEL) # 調用 OpenAI API 獲取 embeddings
        embeddings = [item.embedding for item in response.data] # 從回應中提取 embedding 向量
        return np.array(embeddings)
    except openai.APIError as e:
        print(f"  - OpenAI API 返回錯誤: {e}")
        return None
    except Exception as e:
        print(f"  - 獲取 embedding 時發生錯誤: {e}")
        return None

# --- 計算餘弦相似度 ---
def calculate_similarities(vectors):
    """
    計算相鄰向量之間的餘弦相似度。
    參數:
        vectors (numpy.ndarray): embedding 向量陣列。
    返回:
        list[float]: 相鄰向量間的餘弦相似度列表。
    """
    if vectors is None or len(vectors) < 2: # 當句子不足兩個時，無法計算相似度
        return []
    similarities = []
    for i in range(len(vectors) - 1): # 遍歷向量，計算相鄰向量的餘弦相似度
        sim = cosine_similarity([vectors[i]], [vectors[i+1]])[0][0]
        similarities.append(sim)
    return similarities

# --- 找出語義斷點 ---
def find_breakpoints(similarities, threshold):
    """
    根據相似度閾值找出語義斷點的索引。
    參數:
        similarities (list[float]): 相鄰句子相似度列表。
        threshold (float): 相似度閾值。
    返回:
        list[int]: 斷點的索引列表 (表示斷點發生在該索引的句子 *之後*)。
    """
    breakpoints = []
    for i, sim in enumerate(similarities): # 遍歷相似度列表，找出低於閾值的點
        if sim < threshold:
            breakpoints.append(i)
    return breakpoints

# --- 初步組合成 Chunks ---
def group_into_chunks(sentences, breakpoints, min_sentences, max_sentences):
    """
    根據斷點和最大句子數限制將句子組合成初步的 chunk 列表 (句子列表的列表)。
    參數:
        sentences (list[str]): 原始句子列表。
        breakpoints (list[int]): 語義斷點索引列表。
        min_sentences (int): 每個 chunk 的最小句子數 (合併時使用)。
        max_sentences (int): 每個 chunk 的最大句子數。
    返回:
        list[list[str]]: 初步的 chunk 列表 (尚未合併過小 chunk)。
    """
    if not sentences: return []
    chunks_of_sentences = []
    current_chunk_start_index = 0
    semantic_breakpoints_set = set(breakpoints)
    for i in range(len(sentences)):
        current_chunk_len = i + 1 - current_chunk_start_index
        is_semantic_break = i in semantic_breakpoints_set
        is_max_len_reached = current_chunk_len >= max_sentences
        is_last_sentence = i == len(sentences) - 1
        if is_last_sentence or is_max_len_reached or is_semantic_break:
            split_index = i + 1
            chunk = sentences[current_chunk_start_index:split_index]
            if chunk: chunks_of_sentences.append(chunk)
            current_chunk_start_index = split_index

    # 合併過小的 chunks
    merged_chunks = []
    if not chunks_of_sentences: return []

    current_merged_chunk = [] # 用一個列表來累積當前正在合併的 chunk

    for chunk in chunks_of_sentences:
        if not chunk: continue
                
        potential_len = len(current_merged_chunk) + len(chunk) # 預計合併後的長度

        # 條件 1: 如果 current_merged_chunk 為空，直接開始新的
        if not current_merged_chunk:
            current_merged_chunk = list(chunk)
        # 條件 2: 如果當前 chunk 小於 min_sentences 且 合併後不超過 max_sentences
        elif len(chunk) < min_sentences and potential_len <= max_sentences:
            current_merged_chunk.extend(chunk)
        # 條件 3: 如果 current_merged_chunk 小於 min_sentences 且 合併後不超過 max_sentences
        # (這種情況也允許合併，即使當前 chunk 不小)
        elif len(current_merged_chunk) < min_sentences and potential_len <= max_sentences:
             current_merged_chunk.extend(chunk)
        # 當不滿足合併條件，則結束當前的 merged chunk，開始新的
        else:
            merged_chunks.append(current_merged_chunk)
            current_merged_chunk = list(chunk)

    # 添加最後一個累積的 chunk
    if current_merged_chunk:
        merged_chunks.append(current_merged_chunk)

    print(f"  - 初步分組並合併後得到 {len(merged_chunks)} 個 chunks (最小句子數: {min_sentences}, 最大句子數: {max_sentences})。")
    return merged_chunks

# --- 添加句子重疊 ---
def add_sentence_overlap(chunks_of_sentences, overlap_sentences):
    """
    為相鄰的 chunk (句子列表) 添加重疊。
    參數:
        chunks_of_sentences (list[list[str]]): 句子列表的列表。
        overlap_sentences (int): 重疊的句子數量。
    返回:
        list[list[str]]: 帶有重疊的 chunk 列表。
    """
    if overlap_sentences <= 0 or len(chunks_of_sentences) < 2:
        return chunks_of_sentences # 無需添加重疊

    overlapped_chunks = [chunks_of_sentences[0]] # 第一個 chunk 不變

    for i in range(1, len(chunks_of_sentences)):
        prev_chunk = chunks_of_sentences[i-1]
        current_chunk = chunks_of_sentences[i]

        # 從前一個 chunk 中獲取重疊部分
        overlap = prev_chunk[-overlap_sentences:] # 取最後 overlap_sentences 個句子

        # 將重疊部分加到當前 chunk 的開頭 (注意：確保不重複添加已有的句子)
        # 創建一個新的列表來存儲帶重疊的當前 chunk
        new_current_chunk = overlap + [sent for sent in current_chunk if sent not in overlap]

        overlapped_chunks.append(new_current_chunk)

    print(f"  - 添加了 {overlap_sentences} 句的重疊。")
    return overlapped_chunks

# --- 繪製相似度圖，確認陡坡圖 ---
def plot_similarities(similarities, threshold, section_index):
    """
    繪製單個段落的相鄰句子相似度變化圖。
    參數:
        similarities (list[float]): 相鄰句子相似度列表。
        threshold (float): 相似度閾值。
        section_index (int): 段落的索引 (用於標題)。
    """
    if not similarities:
        print(f"段落 {section_index + 1} 沒有足夠的句子來計算相似度，跳過繪圖。")
        return
    plt.figure(figsize=(12, 6))
    plt.plot(similarities, marker='.', linestyle='-', label=f'Section {section_index + 1} Adjacent Sentence Similarity')

    plt.axhline(threshold, color='red', linestyle='--', label=f'Threshold ({threshold})')

    plt.title(f'Section {section_index + 1}: Cosine Similarity between Adjacent Sentences')
    plt.xlabel('Sentence Index (Transition Point within section)')
    plt.ylabel('Cosine Similarity')
    plt.legend()
    plt.grid(True)

    print(f"正在顯示段落 {section_index + 1} 的相似度變化圖...")
    plt.show() 

# --- 儲存 Chunks ---
def save_chunks(final_chunks_text, filepath):
    """
    將最終的文本 chunk 儲存到檔案，每個 chunk 之間用分隔符隔開，並包含 token 數。
    參數:
        final_chunks_text (list[str]): 最終的文本 chunks 列表。
        filepath (str): 儲存路徑。
    """
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            total_tokens = 0
            for i, chunk in enumerate(final_chunks_text):
                chunk_text = chunk.strip() # 確保前後無多餘空白
                token_count = len(encoding.encode(chunk_text)) # <--- 計算 token
                total_tokens += token_count
                f.write(f"--- Chunk {i+1} (Tokens: {token_count}) ---\n") # <--- 加入 token 數
                f.write(chunk_text)
                f.write("\n\n") # 兩個換行符作為分隔
        avg_tokens = total_tokens / len(final_chunks_text) if final_chunks_text else 0
        print(f"成功將 {len(final_chunks_text)} 個 chunks 儲存到: {filepath}")
        print(f"總 Token 數: {total_tokens}, 平均每個 Chunk Token 數: {avg_tokens:.2f}")
    except IOError as e:
        print(f"儲存 chunks 失敗: {e}")

if __name__ == "__main__":
    # 1. 讀取整個檔案
    raw_text = read_text_file(INPUT_FILE)
    if not raw_text:
        exit()

    # 2. 根據分隔符分割成主要段落
    major_sections = raw_text.split(SECTION_SEPARATOR)
    print(f"文本被分割成 {len(major_sections)} 個主要段落。")

    all_final_chunks_text = [] # 用於收集所有段落產生的最終文本 chunks

    # 3. 遍歷每個主要段落進行處理
    for index, section_text in enumerate(major_sections):
        print(f"\n--- 處理段落 {index + 1}/{len(major_sections)} ---")

        # 3.1 清理當前段落文本
        cleaned_section = clean_text_section(section_text)
        if not cleaned_section:
             print("  - 清理後段落為空，跳過。")
             continue

        # 3.2 分割句子
        sentences = split_into_sentences(cleaned_section)
        print(f"  - 段落被分割成 {len(sentences)} 個句子。")
        if len(sentences) < 2: # 需要至少兩個句子才能計算相似度
            print("  - 句子數量不足以進行語義 chunking，將整個段落視為一個 chunk。")
            if cleaned_section: # 確保不是空的
                all_final_chunks_text.append(cleaned_section)
            continue # 處理下一個段落

        # 3.3 獲取 Embeddings
        embeddings = get_embeddings(sentences)
        if embeddings is None:
            print("  - 獲取 embeddings 失敗，跳過此段落。")
            continue
        print(f"  - 成功獲取 {len(embeddings)} 個句子的 embedding。")

        # 3.4 計算相似度
        similarities = calculate_similarities(embeddings)
        print(f"  - 計算了 {len(similarities)} 個相鄰句子的相似度。")
        if not similarities:
             print("  - 計算相似度失敗，跳過此段落。")
             continue

        # 3.5 餘弦陡坡圖
        # plot_similarities(similarities, SIMILARITY_THRESHOLD, index)

        # 3.6 找出斷點
        breakpoints = find_breakpoints(similarities, SIMILARITY_THRESHOLD)
        print(f"  - 根據閾值 {SIMILARITY_THRESHOLD} 找到 {len(breakpoints)} 個潛在斷點。")

        # 3.7 初步組合成 Chunks (句子列表的列表)，考慮 min/max 限制
        initial_chunks_of_sentences = group_into_chunks(sentences, breakpoints, MIN_CHUNK_SENTENCES, MAX_CHUNK_SENTENCES)

        # 3.8 添加句子重疊
        overlapped_chunks_of_sentences = add_sentence_overlap(initial_chunks_of_sentences, OVERLAP_SENTENCES)

        # 3.9 將帶重疊的句子列表合併成文本 chunks
        section_final_chunks_text = [" ".join(chunk_sentences).strip() for chunk_sentences in overlapped_chunks_of_sentences]
        print(f"  - 添加重疊後最終生成 {len(section_final_chunks_text)} 個文本 chunks。")

        # 3.10 將當前段落的最終文本 chunks 添加到總列表中
        all_final_chunks_text.extend(section_final_chunks_text)

    # 4. 儲存所有 Chunks 到檔案
    if all_final_chunks_text:
        save_chunks(all_final_chunks_text, OUTPUT_CHUNKS_FILE)
    else:
        print("\n未生成任何 chunk。")

    # print(f"\n--- Chunk 總數: {len(all_final_chunks)} ---")
    # print("--- Chunk 預覽 (前 5 個) ---")
    # for i, chunk in enumerate(all_final_chunks[:5]):
    #     print(f"Chunk {i+1}:\n{chunk}\n--------------------")
