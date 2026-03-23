"""
rag_components.py — RAG logic, retrieval, and LLM chain construction.

Handles model loading (LLM + embeddings), ChromaDB ingestion of static
professor data (data.json), hybrid retrieval (global JSON + per-user
uploaded PDFs), smart query interception for META and department queries,
and building the full history-aware RAG chain.
"""

import torch                     # Check GPU availability via torch.cuda.is_available()
import chromadb                  # ChromaDB vector database — PersistentClient for storing/querying embeddings
import os                        # os.access() for path permissions, os.getenv() for env vars
import json                      # Parse data.json (static professor profiles)
import uuid                      # Generate unique IDs for ChromaDB document entries
import re                        # Regex for META/department query patterns and user ID sanitization
from pathlib import Path         # Object-oriented filesystem path construction
from langchain_core.messages import HumanMessage, AIMessage  # Typed message objects for chat history handling
from langchain_classic.chains import (
    create_history_aware_retriever,   # Wraps a retriever to reformulate queries using chat history
    create_retrieval_chain,           # Ties retriever + QA chain into a single end-to-end chain
)
from langchain_classic.chains.combine_documents import (
    create_stuff_documents_chain,     # Feeds all retrieved docs into a single LLM prompt ("stuff" strategy)
)
from dotenv import load_dotenv   # Load .env file for OLLAMA_API_KEY

from langchain_ollama.chat_models import ChatOllama       # Ollama-hosted LLM client (gpt-oss:120b)
from langchain_huggingface import HuggingFaceEmbeddings    # HuggingFace sentence embeddings (BGE-large-en-v1.5)
from langchain_chroma import Chroma                        # LangChain wrapper around ChromaDB for retriever creation
from langchain_core.prompts import ChatPromptTemplate      # Build structured system/human prompt templates
from langchain_core.runnables import RunnableLambda        # Wrap a plain Python function as a LangChain Runnable,
                                                           # used to combine multiple retrievers into one callable
                                                           # that the retrieval chain can invoke like any other step

load_dotenv()

BASE_DIR = Path(__file__).parent

# --- Persistent storage for HF Spaces (falls back to local for dev) ---
HF_PERSISTENT_DIR = Path("/data")
if HF_PERSISTENT_DIR.exists() and os.access(HF_PERSISTENT_DIR, os.W_OK):
    GLOBAL_DB_PATH = HF_PERSISTENT_DIR / "chromadb"
else:
    GLOBAL_DB_PATH = BASE_DIR / "chromadb"

GLOBAL_DB_PATH.mkdir(parents=True, exist_ok=True)
print(f"[DB] Using global ChromaDB path: {GLOBAL_DB_PATH}")

JSON_COLLECTION_NAME = "static_json_knowledge"
JSON_DATA_PATH = BASE_DIR / "data.json"

# Cached copy of data.json for direct lookups (department queries bypass
# vector search). Populated by check_and_ingest_json() at startup.
_raw_json_data = []

EMBEDDING_MODEL_NAME = "BAAI/bge-large-en-v1.5"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
OLLAMA_BASE_URL = "https://ollama.com"
LLM_MODEL_ID = "gpt-oss:120b"

# k=4 is ideal: each professor is 1-2 chunks (~2KB). Pulling 4 chunks gives
# 2-4 relevant professors without flooding the context with unrelated profiles.
JSON_RETRIEVER_K = 4
USER_RETRIEVER_K = 4

# Patterns that are questions about the conversation itself, not about professors.
# These must be answered from chat history — never from ChromaDB.
META_QUESTION_PATTERNS = re.compile(
    r"\b(what (did|have) (we|you|i)|what (was|were) (we|you)|"
    r"what (have we|did we) (talk|discuss|chat|say|ask)|"
    r"(recall|remember|summarize|summarise) (our|the) (conversation|chat|discussion)|"
    r"previous (question|message|query)|last (question|message|query)|"
    r"what (was|is) my (last|previous|first) (question|message))\b",
    re.IGNORECASE
)

# Detects questions asking about the count or full list of professors in a department.
DEPARTMENT_QUERY_PATTERNS = re.compile(
    r"\b(how many|list\s+all|list|count|number\s+of|total|all\s+(the\s+)?)"
    r".*?\b(professors?|faculty|teachers?|staff|lecturers?)\b"
    r"|\b(professors?|faculty)\b.*?\b(in|of|from|under)\b.*?\b(department|dept|school|branch)\b",
    re.IGNORECASE
)

# Maps user-friendly department names/abbreviations to the branch prefix
# used in data.json. Longest keywords are matched first to avoid partial hits.
_DEPT_KEYWORD_MAP = {
    'computer science and engineering': 'cse',
    'computer science': 'cse',
    'cse': 'cse',
    'biotechnology': 'biotech',
    'biotech': 'biotech',
    'electronics and communication': 'electronics',
    'electronics': 'electronics',
    'ece': 'electronics',
    'electrical and electronics': 'electrical',
    'electrical': 'electrical',
    'eee': 'electrical',
    'civil engineering': 'civil',
    'civil': 'civil',
    'mechanical engineering': 'mechanical',
    'mechanical': 'mechanical',
    'film': 'film',
    'fashion technology': 'ksoft',
    'fashion': 'ksoft',
    'law': 'ksol',
    'management': 'ksom',
    'public health': 'ksph',
    'humanities': 'ksoh',
    'architecture': 'ksap',
    'yoga': 'yoga',
    'rural management': 'ksrm',
    'computer applications': 'ksac',
    'mca': 'ksac',
}


def answer_department_query(question: str) -> str | None:
    """
    If the question asks how many / list all professors in a department,
    answer directly from the cached data.json — never from the vector retriever.
    Returns None if this is not a department count/list question.
    """
    if not DEPARTMENT_QUERY_PATTERNS.search(question):
        return None

    q_lower = question.lower()

    # Match longest keyword first to avoid 'cs' matching before 'computer science'
    matched_prefix = None
    for keyword, prefix in sorted(_DEPT_KEYWORD_MAP.items(), key=lambda x: -len(x[0])):
        if keyword in q_lower:
            matched_prefix = prefix
            break

    if not matched_prefix:
        return None

    professors = sorted({
        item['metadata']['name']
        for item in _raw_json_data
        if item.get('branch', '').lower().startswith(matched_prefix)
        and item.get('metadata', {}).get('type') == 'profile_summary'
        and item.get('metadata', {}).get('name')
    })

    if not professors:
        return f"No professors found for that department in the database."

    # Get the full branch display name from the first matching entry
    branch_display = matched_prefix.upper()
    for item in _raw_json_data:
        if item.get('branch', '').lower().startswith(matched_prefix):
            branch_display = item['branch']
            break

    count = len(professors)
    names_list = '\n'.join(f"- {name}" for name in professors)
    return f"There are **{count} professors** in the {branch_display} department:\n\n{names_list}"


llm = None
embeddings = None
global_chroma_client = None


def load_models():
    """Initialize the three core components at app startup:
    1. Ollama LLM (gpt-oss:120b) for chat generation
    2. HuggingFace embeddings (BGE-large-en-v1.5) for vector search
    3. Global ChromaDB persistent client for the static professor collection"""
    global llm, embeddings, global_chroma_client

    print("--- Loading RAG models ---")
    try:
        llm = ChatOllama(
            base_url=OLLAMA_BASE_URL,
            model=LLM_MODEL_ID,
            headers={'Authorization': f'Bearer {OLLAMA_API_KEY}'},
            temperature=0.3,  # Lower temperature = more focused, less verbose
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
        print(f"Connecting to Global DB at: {GLOBAL_DB_PATH}")
        global_chroma_client = chromadb.PersistentClient(path=str(GLOBAL_DB_PATH))
    except Exception as e:
        print(f"FATAL Error connecting to Global ChromaDB: {e}")
        exit()

    print("--- Models Loaded ---")


def check_and_ingest_json():
    """
    Ingests data.json into ChromaDB.
    Re-ingests automatically if the item count in data.json changes,
    so updating data.json + redeploying is all you need.
    """
    global global_chroma_client, embeddings, _raw_json_data

    if not global_chroma_client:
        return

    if not JSON_DATA_PATH.exists():
        print(f"Warning: '{JSON_DATA_PATH}' not found.")
        return

    try:
        with open(JSON_DATA_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _raw_json_data = data  # cache for direct lookups
        source_count = sum(1 for item in data if "page_content" in item)
    except Exception as e:
        print(f"Could not read data.json: {e}")
        return

    try:
        collection = global_chroma_client.get_collection(name=JSON_COLLECTION_NAME)
        stored_count = collection.count()
        if stored_count == source_count and stored_count > 0:
            print(f"Global Collection ready with {stored_count} items.")
            return
        print(f"Count mismatch (stored={stored_count}, source={source_count}). Re-ingesting...")
        global_chroma_client.delete_collection(name=JSON_COLLECTION_NAME)
    except Exception:
        print(f"Global Collection not found. Ingesting {source_count} items...")

    try:
        documents, metadatas, ids = [], [], []
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
            for i in range(0, len(documents), 100):
                vector_store.add_texts(
                    texts=documents[i:i+100],
                    metadatas=metadatas[i:i+100],
                    ids=ids[i:i+100]
                )
            print(f"Ingested {len(documents)} items into Global DB.")
    except Exception as e:
        print(f"Error during JSON ingestion: {e}")


def get_hybrid_retriever(shared_users_db_path: str, unique_collection_name: str = None):
    """Build a combined retriever that searches both the global JSON collection
    (static professor data) and the user's uploaded-PDF collection (if any).
    Results are deduplicated by content prefix to avoid showing the same chunk twice."""
    global global_chroma_client, embeddings

    retrievers = []

    try:
        json_store = Chroma(
            client=global_chroma_client,
            collection_name=JSON_COLLECTION_NAME,
            embedding_function=embeddings,
        )
        retrievers.append(json_store.as_retriever(search_kwargs={"k": JSON_RETRIEVER_K}))
    except Exception as e:
        print(f"Error accessing Global JSON: {e}")

    if shared_users_db_path and unique_collection_name:
        try:
            shared_client = chromadb.PersistentClient(path=str(shared_users_db_path))
            existing = [c.name for c in shared_client.list_collections()]
            if unique_collection_name in existing:
                user_store = Chroma(
                    client=shared_client,
                    collection_name=unique_collection_name,
                    embedding_function=embeddings,
                )
                retrievers.append(user_store.as_retriever(search_kwargs={"k": USER_RETRIEVER_K}))
            else:
                print(f"Note: User collection '{unique_collection_name}' not found yet.")
        except Exception as e:
            print(f"Error accessing Shared DB: {e}")

    if not retrievers:
        return None

    def combined_retrieval(query):
        combined_docs = []
        seen = set()
        for r in retrievers:
            try:
                for doc in r.invoke(query):
                    key = doc.page_content[:150]
                    if key not in seen:
                        seen.add(key)
                        combined_docs.append(doc)
            except Exception as e:
                print(f"Retriever error: {e}")
        return combined_docs

    return RunnableLambda(combined_retrieval)


def delete_user_collections(shared_db_path: str, user_id: str):
    """Delete all ChromaDB collections belonging to a user (matched by the
    u_{userId}_ prefix). Called on explicit logout to clean up user data."""
    try:
        client = chromadb.PersistentClient(path=shared_db_path)
        safe_uid = re.sub(r'[^a-zA-Z0-9]', '', user_id)
        prefix = f"u_{safe_uid}_"
        count = 0
        for col in client.list_collections():
            if col.name.startswith(prefix):
                client.delete_collection(col.name)
                count += 1
        print(f"Deleted {count} collections for user {user_id}.")
    except Exception as e:
        print(f"Error cleaning up user collections: {e}")


def answer_from_history_only(question: str, chat_history: list) -> str:
    """
    Answers meta-questions about the conversation (e.g. 'what did we talk about?')
    directly from the in-memory chat history, completely bypassing ChromaDB.
    Called from main.py before the RAG chain is invoked.
    """
    if not chat_history:
        return "We haven't discussed anything yet — this is the start of our conversation!"

    history_text = ""
    for msg in chat_history:
        if isinstance(msg, HumanMessage):
            history_text += f"User: {msg.content}\n"
        elif isinstance(msg, AIMessage):
            first_sentence = msg.content.split('.')[0].strip()
            history_text += f"Assistant: {first_sentence}.\n"

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a helpful assistant. The user is asking about what was discussed "
         "in this conversation. Answer in 2-3 sentences using only the chat history "
         "below. Do not reference any external database.\n\nChat History:\n{history}"),
        ("human", "{question}")
    ])
    result = (prompt | llm).invoke({"history": history_text, "question": question})
    return result.content


def get_rag_chain_for_collection(shared_users_db_path: str, unique_collection_name: str = None):
    """Build the full RAG chain for a given user collection:
    1. History-aware retriever — reformulates follow-up questions into standalone queries
    2. Stuff documents chain — feeds retrieved profiles + history into the QA prompt
    3. Retrieval chain — ties retriever and QA chain together
    Returns a runnable that accepts {"input": str, "chat_history": list}."""
    global llm

    if not llm:
        print("Models not loaded.")
        return None

    retriever = get_hybrid_retriever(shared_users_db_path, unique_collection_name)
    if not retriever:
        return None

    # Reformulates follow-up questions into standalone DB search queries.
    # Critical rule: if the user says "more" or "tell me more", it must include
    # the professor name from history so ChromaDB fetches the RIGHT person.
    contextualize_q_system_prompt = (
        "You are a query reformulator for a university professor directory.\n"
        "Given the chat history and the latest user message, rewrite it as a "
        "clear, standalone search query for a professor database.\n\n"
        "Rules:\n"
        "- If the user refers to 'them', 'that professor', 'him', 'her', 'more', "
        "or 'tell me more' without naming someone, extract the professor's name "
        "from the chat history and include it in the query.\n"
        "- For 'more details' follow-ups produce: "
        "'Full profile of [Name]: research interests, publications, courses, email, education'\n"
        "- If the question is already specific and clear, return it unchanged.\n"
        "- Return ONLY the reformulated query. No explanation, no preamble."
    )

    contextualize_q_prompt = ChatPromptTemplate.from_messages([
        ("system", contextualize_q_system_prompt),
        ("placeholder", "{chat_history}"),
        ("human", "{input}"),
    ])

    history_aware_retriever = create_history_aware_retriever(
        llm, retriever, contextualize_q_prompt
    )

    # Concise, persona-driven QA prompt.
    # The key rules: don't dump everything, match the response length to what was asked.
    qa_system_prompt = """You are a helpful assistant for the KIIT University professor directory.
Answer using ONLY the professor profiles retrieved below.

How to respond:
- Single professor, general question → 3-5 lines: name, role, department, a key highlight, email if available.
- Single professor, "tell me more" / "full details" → list every available field for that professor only.
- "Who teaches X?" or "best professor for Y?" → name 2-3 professors, one line each explaining why.
- "List all professors in [dept]" → compact format: Name | Role | Email.
- Missing field → say "not listed" inline, do not make it a separate bullet.
- Never add a "Summary" section or usage tips at the end.
- Never invent or infer information not present in the profiles.

Retrieved Profiles:
{context}"""

    qa_prompt = ChatPromptTemplate.from_messages([
        ("system", qa_system_prompt),
        ("placeholder", "{chat_history}"),
        ("human", "{input}"),
    ])

    question_answer_chain = create_stuff_documents_chain(llm, qa_prompt)
    rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)
    return rag_chain