# Mini-project

This project is a full-stack web application that allows you to "chat" with your PDF documents.

What makes this project unique is its multimodal RAG (Retrieval-Augmented Generation) pipeline. It doesn't just read the text from your PDFs; it also uses a Vision-Language Model (VLM) to analyze any images, charts, or figures within the document. These image descriptions are embedded alongside the text, allowing you to ask questions about both the text and the visual content of your documents.

The application uses a FastAPI backend, a ChromaDB vector store, and a modern vanilla JS + Tailwind CSS frontend.   

## Setup and Installation

### Prerequisites

* Python 3.10+

* An Ollama API Key (since this project uses the Ollama Cloud models).

* FFmpeg (for audio processing). Install it via your system's package manager (e.g., `brew install ffmpeg`, `apt-get install ffmpeg`).

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
    3. Install the required Python packages. (A `requirements.txt` is not provided, but you can install the main dependencies manually):
        ```shell 
        pip install "fastapi[all]" uvicorn ollama langchain langchain-ollama langchain-community langchain-huggingface langchain-chroma chromadb sentence-transformers torch python-dotenv "marker-pdf[full]" speechrecognition pydub unstructured markdown sounddevice
        ```

        for Windows
        ```shell
        pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu128

        ```

        for Linux
        ```shell
        pip3 install torch torchvision
        ```
    4. Create a `.env` file in the `Backend-new/` directory:
        ```shell
        touch .env
        ```
    5. Add your Ollama API key to the `.env` file:
        ```shell
        OLLAMA_API_KEY="your_ollama_api_key_goes_here"
        ```
3. Run the Application
    1. From the `Backend-new/` directory, start the FastAPI server:
        ```shell 
        uvicorn main:app --reload
        ```
        The `--reload` flag is for development and automatically restarts the server when code changes.
    2. Open your browser and navigate to: `http://127.0.0.1:8000`

        You will see the PDF upload page. Upload a document, wait for it to be processed, and you will be redirected to the chat page, ready to ask questions.

## Project Structure

```bash
├── .gitignore              # add your env here
├── Backend/
│   ├── main.py             # FastAPI server: endpoints for upload, chat, STT
│   ├── rag_components.py   # Loads LLM/Embedding models, builds the RAG chain
│   ├── Base.py             # Pipeline Script 1: PDF -> Markdown + Images
│   ├── Image-Testo.py      # Pipeline Script 2: Analyzes images using Ollama VLM
│   ├── Emmbed.py           # Pipeline Script 3: Embeds final MD -> ChromaDB
│   │
│   ├── chroma_db/          # Default directory for the persistent vector store
│   ├── pdf/                # Default directory for uploaded PDFs
│   ├── .env                # (You must create this) Stores API keys
│
└── Frontend(basic)/
    ├── upload.html         # PDF upload page
    ├── index.html          # Main chat interface
    ├── style.css           # Custom styles (e.g., typing indicator)
    ├── script.js           # Chat page logic (sending messages, STT)
    └── upload.js           # Upload page logic (handling file upload, redirecting)


```

