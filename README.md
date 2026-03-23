# KIIT-RAG — KIIT Professor Finder (Mini Project)

A full-stack RAG (Retrieval-Augmented Generation) web application that lets users query information about KIIT University professors through a conversational AI interface.

The app combines a **static professor database** (`data.json`) with **user-uploaded PDF documents** to answer questions via a multimodal pipeline. It doesn't just read text — it uses a Vision-Language Model (VLM) to analyze images, charts, and figures within uploaded PDFs, converting them to searchable text descriptions.

### Key Features

- **Google OAuth + Guest login** — authenticated users can upload PDFs; guests can chat with the static professor database only.
- **3-stage PDF processing pipeline** — PDF → Markdown extraction → Vision model image captioning → Vector embedding & ChromaDB storage.
- **Hybrid retrieval** — every query searches both the global professor database and the user's uploaded documents.
- **Smart query interception** — META questions (about the conversation) are answered from chat history; department count/list queries hit the cached `data.json` directly to avoid vector K-limit bias.
- **History-aware follow-ups** — follow-up questions like "tell me more" are reformulated with context from chat history so the retriever fetches the right professor.
- **Voice input** — record audio in the browser, transcribed via Google Speech Recognition, and sent as a chat message.
- **Per-user data isolation** — each user's uploaded documents are stored in separate ChromaDB collections, cleaned up on logout.
- **Chat history persistence** — localStorage (authenticated) / sessionStorage (guests) with daily auto-expiry.

### Tech Stack

**Backend:** FastAPI, LangChain, ChromaDB, Ollama (gpt-oss:120b), HuggingFace Embeddings (BGE-large-en-v1.5), Marker PDF, SpeechRecognition, Authlib (Google OAuth)

**Frontend:** Vanilla HTML/CSS/JS, Marked.js (markdown rendering), MediaRecorder API (voice input),  Custom Material Design 3 UI with Tailwind CSS 

## Setup and Installation

### Prerequisites

* Python 3.10 to 3.12 (as for the time being some pytorch dependency only support this version)

* An Ollama API Key (since this project uses the Ollama Cloud models).

* FFmpeg (for audio processing). Install it via your system's package manager (e.g., `brew install ffmpeg`(For Mac), `apt-get install ffmpeg` (For Ubuntu/Debian based),`winget install Gyan.FFmpeg
`(For Windows)).

1. Clone the Repository

    ```shell
    git clone https://github.com/Pager-dot/Mini-project/

    cd Mini-project
    ```
2. Set Up the Backend
    1. Navigate to the backend directory:
        ```shell
        cd Backend
        ```
    2. (Recommended) Create and activate a virtual environment:
        ```shell
        python -m venv venv
        source venv/bin/activate  # On Windows: venv\Scripts\activate
        ```
    3. Install the required Python packages. Using the `requirements.txt`. Note: run this when you are inside the virtual environment :
        ```shell 
        pip install -r requirements.txt
        ```

        * for Windows (if there is an error in torch install for some reason)
            ```shell
            pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu128

            ```

        * for Linux (if there is an error in torch install for some reason)
            ```shell
            pip3 install torch torchvision
            ```
    4. Create a `.env` file in the `Backend` directory:
        ```shell
        touch .env # On Windows(powershell): ni .env 
        ```
    5. Add your Ollama API and keys for Google auth facility key to the `.env` file:
        ```shell
        OLLAMA_API_KEY="your_ollama_api_key_goes_here"
        ```
        ``` shell
        GOOGLE_CLIENT_ID='add your key here (provided by your gcp console)'
        GOOGLE_CLIENT_SECRET='add your key here (provided by your gcp console)' 
        GOOGLE_CLIENT_SECRET='add your key here (this can be anything)'
        ```
        
3. Run the Application
    1. From the `Backend` directory, start the FastAPI server:
        ```shell 
        uvicorn main:app --reload
        ```
        The `--reload` flag is for development and automatically restarts the server when code changes.
    2. Open your browser and navigate to: `http://localhost:8000/` (as this needs to be set by the gcp console)

        You will see the PDF upload page. Upload a document, wait for it to be processed, and you will be redirected to the chat page, ready to ask questions.

## Project Structure

```bash
Mini-project/
├── .env                        # Environment secrets (OAuth keys, Ollama API key, session secret)
├── .gitignore                  # Git exclusions (.env, venv, chromadb, etc.)
├── Dockerfile                  # Docker containerization (Python 3.10, port 7860 for HF Spaces)
├── README.md                   # This file — full project documentation
│
├── Backend/
│   ├── __init__.py             # Makes Backend a Python package (required for imports)
│   ├── main.py                 # FastAPI server: auth (Google OAuth + guest), routes, PDF upload,
│   │                           #   audio transcription, chat endpoint with query interception
│   ├── rag_components.py       # RAG logic: model loading, ChromaDB ingestion, hybrid retrieval,
│   │                           #   history-aware chain, META/department query interception
│   ├── Base.py                 # Pipeline Stage 1: PDF → Markdown + extracted images (Marker)
│   ├── Image-Testo.py          # Pipeline Stage 2: Replace image links with AI descriptions
│   │                           #   (Ollama Qwen3 vision model, auto-pulls model on startup)
│   ├── Emmbed.py               # Pipeline Stage 3: Chunk markdown → generate embeddings → store
│   │                           #   in ChromaDB (BGE-large-en-v1.5, 512-char chunks)
│   ├── data.json               # Static professor database (KIIT faculty profiles, publications,
│   │                           #   contact info) — cached at startup for direct department lookups
│   ├── requirements.txt        # Python dependencies with pinned versions
│   ├── chromadb/               # Global ChromaDB storage (static professor data, auto-created)
│   └── users_data/
│       └── chromadb/           # Per-user ChromaDB storage (uploaded PDF embeddings, auto-created)
│
└── frontend/
    ├── index.html              # Login page (Google OAuth sign-in + guest mode)
    ├── chat.html               # Main chat interface (message display, voice input, history)
    ├── upload.html             # PDF upload page (file selection, processing status polling)
    ├── script.js               # Chat logic: message send/receive, voice recording, markdown
    │                           #   rendering, conversation history persistence (localStorage/session)
    ├── upload.js               # Upload logic: file validation, upload to server, poll processing
    │                           #   status, redirect to chat on completion
    ├── style.css               # code for the theme, animations, responsive ui elements
    ├── tailwind-config.js      # Shared Tailwind configuration — included in all pages before tailwind CDN
    └── kiit-logo.png           # KIIT University brand logo
```

