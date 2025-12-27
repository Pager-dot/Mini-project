import torch
import chromadb
import os
import json
import uuid
import re
from pathlib import Path  # <--- NEW IMPORT
from langchain_core.messages import HumanMessage, AIMessage
from langchain_classic.chains import create_history_aware_retriever, create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from dotenv import load_dotenv

# --- Imports for Ollama Cloud LLM ---
from langchain_ollama.chat_models import ChatOllama

# --- Imports for RAG ---
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableLambda

# --- 1. Configuration ---
load_dotenv()

# --- FIX: Use Absolute Path for Global DB ---
# This ensures we find 'Backend/chromadb' regardless of where you run main.py from
BASE_DIR = Path(__file__).parent
GLOBAL_DB_PATH = BASE_DIR / "chromadb" 
JSON_COLLECTION_NAME = "static_json_knowledge"
JSON_DATA_PATH = BASE_DIR / "data.json"

EMBEDDING_MODEL_NAME = "BAAI/bge-large-en-v1.5"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
OLLAMA_BASE_URL = "https://ollama.com"
LLM_MODEL_ID = "gpt-oss:120b"

# --- 2. Global Variables ---
llm = None
embeddings = None
global_chroma_client = None

def load_models():
    """Loads models and connects to the GLOBAL ChromaDB."""
    global llm, embeddings, global_chroma_client

    print("--- Loading RAG models ---")
    
    try:
        llm = ChatOllama(
            base_url=OLLAMA_BASE_URL,
            model=LLM_MODEL_ID,
            headers={'Authorization': f'Bearer {OLLAMA_API_KEY}'},
            temperature=0.7,
        )
    except Exception as e:
        print(f"FATAL Error connecting to LLM: {e}")
        exit()

    try:
        embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL_NAME,
            model_kwargs={'device': DEVICE},
            encode_kwargs={'normalize_embeddings': True}
        )
    except Exception as e:
        print(f"FATAL Error loading embedding model: {e}")
        exit()

    try:
        # Convert path to string for Chroma
        print(f"Connecting to Global DB at: {GLOBAL_DB_PATH}")
        global_chroma_client = chromadb.PersistentClient(path=str(GLOBAL_DB_PATH))
    except Exception as e:
        print(f"FATAL Error connecting to Global ChromaDB: {e}")
        exit()

    print("--- Models Loaded ---")

def check_and_ingest_json():
    """Checks if JSON data is in the Global ChromaDB."""
    global global_chroma_client, embeddings
    
    if not global_chroma_client: return 

    try:
        # Check if collection exists and has data
        collection = global_chroma_client.get_collection(name=JSON_COLLECTION_NAME)
        if collection.count() > 0:
            print(f"✅ Global Collection '{JSON_COLLECTION_NAME}' ready with {collection.count()} items.")
            return
    except Exception:
        print(f"Global Collection '{JSON_COLLECTION_NAME}' not found. Ingesting...")

    if not JSON_DATA_PATH.exists():
        print(f"⚠️ Warning: '{JSON_DATA_PATH}' not found.")
        return

    try:
        with open(JSON_DATA_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        documents = []
        metadatas = []
        ids = []

        for item in data:
            if "page_content" in item:
                documents.append(item["page_content"])
                metadatas.append(item.get("metadata", {}))
                ids.append(str(uuid.uuid4()))
        
        if documents:
            vector_store = Chroma(
                client=global_chroma_client,
                collection_name=JSON_COLLECTION_NAME,
                embedding_function=embeddings,
            )
            # Add in batches to avoid limits
            batch_size = 100
            for i in range(0, len(documents), batch_size):
                vector_store.add_texts(
                    texts=documents[i:i+batch_size], 
                    metadatas=metadatas[i:i+batch_size], 
                    ids=ids[i:i+batch_size]
                )
            print(f"✅ Ingested {len(documents)} items into Global DB.")

    except Exception as e:
        print(f"❌ Error during JSON ingestion: {e}")

def get_hybrid_retriever(shared_users_db_path: str, unique_collection_name: str = None):
    """
    Returns a retriever that searches:
    1. The Global JSON collection (Static Knowledge).
    2. The User's Specific Collection within the Shared DB (if provided).
    """
    global global_chroma_client, embeddings
    
    retrievers = []

    # 1. Global JSON Retriever
    try:
        json_store = Chroma(
            client=global_chroma_client,
            collection_name=JSON_COLLECTION_NAME,
            embedding_function=embeddings,
        )
        retrievers.append(json_store.as_retriever(search_kwargs={"k": 3}))
    except Exception as e:
        print(f"Error accessing Global JSON: {e}")

    # 2. User Specific Collection in Shared DB (Skip if Guest/None)
    if shared_users_db_path and unique_collection_name:
        try:
            shared_client = chromadb.PersistentClient(path=str(shared_users_db_path))
            existing_collections = [c.name for c in shared_client.list_collections()]
            
            if unique_collection_name in existing_collections:
                user_store = Chroma(
                    client=shared_client,
                    collection_name=unique_collection_name,
                    embedding_function=embeddings,
                )
                retrievers.append(user_store.as_retriever(search_kwargs={"k": 3}))
            else:
                # This is normal for a fresh upload or first query
                print(f"Note: User collection '{unique_collection_name}' not found yet.")
        except Exception as e:
            print(f"Error accessing Shared DB: {e}")

    # 3. Combine
    if not retrievers:
        # Fallback if everything fails
        return None

    def combined_retrieval(query):
        combined_docs = []
        for r in retrievers:
            try:
                docs = r.invoke(query)
                combined_docs.extend(docs)
            except Exception as e:
                print(f"Retriever error: {e}")
        return combined_docs

    return RunnableLambda(combined_retrieval)

def delete_user_collections(shared_db_path: str, user_id: str):
    try:
        client = chromadb.PersistentClient(path=shared_db_path)
        collections = client.list_collections()
        safe_uid = re.sub(r'[^a-zA-Z0-9]', '', user_id)
        prefix = f"u_{safe_uid}_"
        count = 0
        for col in collections:
            if col.name.startswith(prefix):
                client.delete_collection(col.name)
                count += 1
        print(f"Deleted {count} collections for user {user_id}.")
    except Exception as e:
        print(f"Error cleaning up user collections: {e}")

def get_rag_chain_for_collection(shared_users_db_path: str, unique_collection_name: str = None):
    global llm

    if not llm:
        print("Models not loaded.")
        return None

    retriever = get_hybrid_retriever(shared_users_db_path, unique_collection_name)
    
    if not retriever:
        # Fallback if no data sources are available
        return None

    contextualize_q_system_prompt = """Given a chat history and the latest user question 
    which might reference context in the chat history, formulate a standalone question 
    which can be understood without the chat history. Do NOT answer the question."""

    contextualize_q_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", contextualize_q_system_prompt),
            ("placeholder", "{chat_history}"),
            ("human", "{input}"),
        ]
    )

    history_aware_retriever = create_history_aware_retriever(
        llm, retriever, contextualize_q_prompt
    )

    qa_system_prompt = """You are an AI assistant. Use the retrieved context to answer the question. 
    
    Context:
    {context}
    
    If the context doesn't contain the answer, say "I don't have that information in my documents."
    """

    qa_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", qa_system_prompt),
            ("placeholder", "{chat_history}"),
            ("human", "{input}"),
        ]
    )

    question_answer_chain = create_stuff_documents_chain(llm, qa_prompt)
    rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)
    
    return rag_chain