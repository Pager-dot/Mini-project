"""
Emmbed.py — Document chunking & embedding storage (Stage 3 / final stage of the pipeline).

Chunks a processed markdown file into 512-character segments with 50-char overlap,
generates vector embeddings using BGE-large-en-v1.5, and stores them in a
ChromaDB collection for later retrieval by the RAG chain.

Usage: python Emmbed.py <path_to_markdown_file> <collection_name> <chroma_db_path>
"""

import chromadb                          # ChromaDB vector database — PersistentClient for storing embeddings
from sentence_transformers import SentenceTransformer  # Load BGE-large model to generate vector embeddings
from langchain_community.document_loaders import UnstructuredMarkdownLoader  # Parse markdown files into LangChain Documents
from langchain_text_splitters import RecursiveCharacterTextSplitter          # Split documents into fixed-size overlapping chunks
import uuid                              # Generate unique IDs for each chunk stored in ChromaDB
import time                              # Measure embedding generation duration
import sys                               # CLI argument parsing (sys.argv) and exit on error (sys.exit)
import torch                             # Check GPU availability via torch.cuda.is_available()

# --- 1. Configuration: parse CLI arguments ---

if len(sys.argv) < 4:
    print("Error: Missing arguments.")
    print("Usage: python Emmbed.py <path_to_markdown_file> <collection_name> <chroma_db_path>")
    sys.exit(1)

# Data Configuration
MARKDOWN_FILE = sys.argv[1]
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50

# Collection and DB Configuration
COLLECTION_NAME = sys.argv[2]
CHROMA_PATH = sys.argv[3]  # <--- NEW: Dynamic DB Path

# Embedding Model Configuration
MODEL_NAME = "BAAI/bge-large-en-v1.5"

# --- 2. Load Embedding Model ---
# Load BGE-large-en-v1.5 sentence transformer on GPU if available, else CPU.
print(f"Loading embedding model: {MODEL_NAME}...")
model = SentenceTransformer(MODEL_NAME, device="cuda" if torch.cuda.is_available() else "cpu")
print("Model loaded.")

# --- 3. Load, Chunk, and Prepare Document ---
# Use LangChain's UnstructuredMarkdownLoader + RecursiveCharacterTextSplitter
# to split the markdown into 512-char chunks with 50-char overlap.
print(f"Loading and splitting document: {MARKDOWN_FILE}...")
loader = UnstructuredMarkdownLoader(MARKDOWN_FILE)
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP
)

docs = loader.load_and_split(text_splitter=text_splitter)
print(f"Document split into {len(docs)} chunks.")

texts = [doc.page_content for doc in docs]
metadatas = [doc.metadata for doc in docs]
ids = [str(uuid.uuid4()) for _ in texts]

# --- 4. Generate Embeddings ---
# Encode all chunks with normalized embeddings using the sentence transformer.
print("Generating embeddings for all chunks...")
start_time = time.time()
embeddings = model.encode(
    texts,
    normalize_embeddings=True,
    show_progress_bar=True
)
end_time = time.time()
print(f"Embeddings generated in {end_time - start_time:.2f} seconds.")

# --- 5. Initialize ChromaDB and Store Data ---
# Create/get the collection and insert all chunks with embeddings, metadata, and UUIDs.
print(f"Initializing ChromaDB at: {CHROMA_PATH}")
client = chromadb.PersistentClient(path=CHROMA_PATH)

collection = client.get_or_create_collection(name=COLLECTION_NAME)

print(f"Adding {len(texts)} chunks to the '{COLLECTION_NAME}' collection...")
collection.add(
    embeddings=embeddings,
    documents=texts,
    metadatas=metadatas,
    ids=ids
)

print("Data insertion complete.")
print(f"Done processing for collection: {COLLECTION_NAME}.")