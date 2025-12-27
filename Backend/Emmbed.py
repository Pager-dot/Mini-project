import chromadb
from sentence_transformers import SentenceTransformer
from langchain_community.document_loaders import UnstructuredMarkdownLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import uuid
import time
import sys
import torch

# --- 1. Configuration ---

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
print(f"Loading embedding model: {MODEL_NAME}...")
model = SentenceTransformer(MODEL_NAME, device="cuda" if torch.cuda.is_available() else "cpu")
print("Model loaded.")

# --- 3. Load, Chunk, and Prepare Document ---
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
print(f"Initializing ChromaDB at: {CHROMA_PATH}")
# Use the dynamic path passed from command line
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