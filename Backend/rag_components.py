import torch
import chromadb
import os
import json
import uuid
from pathlib import Path
from langchain_core.messages import HumanMessage, AIMessage # <--- NEW
from langchain_classic.chains import create_history_aware_retriever, create_retrieval_chain # <--- NEW
from langchain_classic.chains.combine_documents import create_stuff_documents_chain # <--- NEW
from dotenv import load_dotenv

# --- Imports for Ollama Cloud LLM ---
from langchain_ollama.chat_models import ChatOllama

# --- Imports for RAG ---
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_core.output_parsers import StrOutputParser

# --- 1. Configuration ---
load_dotenv()

DB_PATH = "chroma_db"
EMBEDDING_MODEL_NAME = "BAAI/bge-large-en-v1.5"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
JSON_COLLECTION_NAME = "static_json_knowledge" # Fixed name for your JSON data
JSON_DATA_PATH = "data.json" # Path to your json file

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
OLLAMA_BASE_URL = "https://ollama.com"
LLM_MODEL_ID = "gpt-oss:120b"

# --- 2. Global Variables ---
llm = None
embeddings = None
chroma_client = None

def load_models():
    """Loads models and connects to ChromaDB."""
    global llm, embeddings, chroma_client

    print("--- Loading RAG models ---")
    
    # 1. Load LLM
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

    # 2. Load Embeddings
    try:
        embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL_NAME,
            model_kwargs={'device': DEVICE},
            encode_kwargs={'normalize_embeddings': True}
        )
    except Exception as e:
        print(f"FATAL Error loading embedding model: {e}")
        exit()

    # 3. Connect to Chroma
    try:
        chroma_client = chromadb.PersistentClient(path=DB_PATH)
        print(f"Connected to ChromaDB at: {DB_PATH}")
    except Exception as e:
        print(f"FATAL Error connecting to ChromaDB: {e}")
        exit()

    print("--- Models Loaded ---")

def check_and_ingest_json():
    """
    Checks if JSON data is already in ChromaDB. 
    If not, it reads the JSON file and ingests it.
    """
    global chroma_client, embeddings
    
    print(f"Checking status of JSON collection: '{JSON_COLLECTION_NAME}'...")
    
    # Check if collection exists and has data
    try:
        collection = chroma_client.get_collection(name=JSON_COLLECTION_NAME)
        if collection.count() > 0:
            print(f"✅ Collection '{JSON_COLLECTION_NAME}' already exists with {collection.count()} items. Skipping ingestion.")
            return
    except Exception:
        print(f"Collection '{JSON_COLLECTION_NAME}' not found or empty. Starting ingestion...")

    # Load JSON File
    if not os.path.exists(JSON_DATA_PATH):
        print(f"⚠️ Warning: '{JSON_DATA_PATH}' not found. Skipping JSON ingestion.")
        return

    try:
        with open(JSON_DATA_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        print(f"Loaded {len(data)} records from JSON.")
        
        # Prepare for Chroma
        documents = []
        metadatas = []
        ids = []

        for item in data:
            # DIRECT MAPPING: We use the 'page_content' field directly.
            # No need to convert the whole object to text.
            if "page_content" in item:
                documents.append(item["page_content"])
                metadatas.append(item.get("metadata", {})) # Use existing metadata
                ids.append(str(uuid.uuid4()))
        
        if not documents:
            print("No valid 'page_content' fields found in JSON.")
            return

        # Embed and Store
        # We use the LangChain wrapper to simplify embedding generation
        vector_store = Chroma(
            client=chroma_client,
            collection_name=JSON_COLLECTION_NAME,
            embedding_function=embeddings,
        )
        
        vector_store.add_texts(texts=documents, metadatas=metadatas, ids=ids)
        print(f"✅ Successfully ingested {len(documents)} items into '{JSON_COLLECTION_NAME}'.")

    except Exception as e:
        print(f"❌ Error during JSON ingestion: {e}")

def get_hybrid_retriever(pdf_collection_name: str = None):
    """
    Returns a retriever that searches BOTH the static JSON collection
    AND the specific PDF collection (if provided).
    """
    global chroma_client, embeddings
    
    retrievers = []

    # 1. Always include the JSON retriever
    try:
        json_store = Chroma(
            client=chroma_client,
            collection_name=JSON_COLLECTION_NAME,
            embedding_function=embeddings,
        )
        # Search JSON data
        retrievers.append(json_store.as_retriever(search_kwargs={"k": 3}))
    except Exception as e:
        print(f"Error accessing JSON collection: {e}")

    # 2. Include PDF retriever if a valid collection name is provided
    if pdf_collection_name:
        try:
            # Check if collection actually exists in Chroma
            existing_collections = [c.name for c in chroma_client.list_collections()]
            if pdf_collection_name in existing_collections:
                pdf_store = Chroma(
                    client=chroma_client,
                    collection_name=pdf_collection_name,
                    embedding_function=embeddings,
                )
                # Search PDF data
                retrievers.append(pdf_store.as_retriever(search_kwargs={"k": 3}))
            else:
                print(f"Requested PDF collection '{pdf_collection_name}' not found.")
        except Exception as e:
            print(f"Error accessing PDF collection: {e}")

    # 3. Create a combined retriever function
    def combined_retrieval(query):
        combined_docs = []
        for retriever in retrievers:
            docs = retriever.invoke(query)
            combined_docs.extend(docs)
        return combined_docs

    return RunnableLambda(combined_retrieval)
def get_rag_chain_for_collection(collection_name: str = None):
    """
    Builds a History-Aware RAG chain.
    """
    global llm

    if not llm:
        print("Models not loaded.")
        return None

    # 1. Get the Hybrid Retriever (JSON + PDF)
    retriever = get_hybrid_retriever(collection_name)

    # 2. Define "Contextualize Question" Prompt
    # This prompt helps the AI rewrite the user's question to be standalone
    # e.g., "Give me her email" -> "Give me Laxman Soren's email"
    contextualize_q_system_prompt = """Given a chat history and the latest user question 
    which might reference context in the chat history, formulate a standalone question 
    which can be understood without the chat history. Do NOT answer the question, 
    just reformulate it if needed and otherwise return it as is."""

    contextualize_q_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", contextualize_q_system_prompt),
            ("placeholder", "{chat_history}"),
            ("human", "{input}"),
        ]
    )

    # 3. Create History-Aware Retriever
    # This chain will: Take Input + History -> Rewrite Question -> Fetch Docs
    history_aware_retriever = create_history_aware_retriever(
        llm, retriever, contextualize_q_prompt
    )

    # 4. Define "Answer Question" Prompt
    qa_system_prompt = """You are an assistant for question-answering tasks. 
    Use the following pieces of retrieved context to answer the question. 
    If you don't know the answer, just say that you don't know. 
    Keep the answer concise.

    CONTEXT:
    {context}"""

    qa_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", qa_system_prompt),
            ("placeholder", "{chat_history}"),
            ("human", "{input}"),
        ]
    )

    # 5. Create the Final RAG Chain
    question_answer_chain = create_stuff_documents_chain(llm, qa_prompt)
    rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)
    
    return rag_chain