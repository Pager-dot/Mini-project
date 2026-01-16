import os
import shutil
from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles 
from pathlib import Path
import speech_recognition as sr
import io
from pydub import AudioSegment
import subprocess
import sys
from pydantic import BaseModel  
from contextlib import asynccontextmanager
import re
from langchain_core.messages import HumanMessage, AIMessage 
from typing import Dict 

# --- Auth Imports ---
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth

# --- RAG Components ---
from Backend.rag_components import (
    load_models,
    get_rag_chain_for_collection,
    check_and_ingest_json,
    delete_user_collections
)

# --- Global Status Tracker ---
processing_status: Dict[str, str] = {}

load_dotenv(find_dotenv())
# --- Configuration ---
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
SECRET_KEY = os.getenv("SECRET_KEY")

if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    raise ValueError("Missing Google Auth credentials in .env file")

# --- PATH CONFIGURATION ---
BASE_DIR = Path(__file__).parent
USERS_DATA_FOLDER = BASE_DIR / "users_data"
USERS_CHROMA_DB_PATH = USERS_DATA_FOLDER / "chromadb" 
ABSOLUTE_FRONTEND_PATH = BASE_DIR.parent / "Frontend(basic)"

# Verify Frontend Path Exists (Debug Check)
if not ABSOLUTE_FRONTEND_PATH.exists():
    print(f"WARNING: Frontend path not found at {ABSOLUTE_FRONTEND_PATH}")

USERS_DATA_FOLDER.mkdir(exist_ok=True)
USERS_CHROMA_DB_PATH.mkdir(exist_ok=True)

# --- Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application startup...")
    load_models()       
    check_and_ingest_json() 
    yield
    print("Application shutdown...")

app = FastAPI(lifespan=lifespan)

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, https_only=False, same_site="lax")

# --- Mount Static Files Correctly ---
app.mount("/static", StaticFiles(directory=ABSOLUTE_FRONTEND_PATH), name="static")

oauth = OAuth()
oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

class ChatRequest(BaseModel):
    message: str
    collection_name: str | None = None
    history: list[dict] = []

def sanitize_name(name: str) -> str:
    name = name.replace(' ', '_')
    name = re.sub(r'[^a-zA-Z0-9._-]', '', name)
    if len(name) < 3: name = f"doc_{name}"
    return name[:63]

def get_unique_collection_name(user_id: str, short_name: str) -> str:
    safe_uid = re.sub(r'[^a-zA-Z0-9]', '', user_id)
    return f"u_{safe_uid}_{short_name}"[:63]

def run_processing_pipeline(pdf_path: Path, unique_collection_name: str, short_name: str):
    global processing_status
    try:
        processing_status[short_name] = "processing"
        output_dir = pdf_path.parent 
        base_md_file = output_dir / f"{output_dir.name}.md"
        described_md_file = output_dir / f"{output_dir.name}_with_descriptions.md"
        python_executable = sys.executable
        
        print(f"\n--- [PIPELINE START] Collection: {unique_collection_name} ---")
        subprocess.run([python_executable, "Base.py", str(pdf_path), str(output_dir)], check=True, capture_output=True, text=True)
        subprocess.run([python_executable, "Image-Testo.py", str(base_md_file), str(output_dir), str(described_md_file)], check=True, capture_output=True, text=True)
        subprocess.run([python_executable, "Emmbed.py", str(described_md_file), unique_collection_name, str(USERS_CHROMA_DB_PATH)], check=True, capture_output=True, text=True)
        
        print(f"--- [PIPELINE SUCCCESS] ---")
        processing_status[short_name] = "completed"
    except Exception as e:
        print(f"!!!!!! [PIPELINE FAILED] {e} !!!!!!")
        processing_status[short_name] = "failed"
    finally:
        if output_dir.exists():
            try:
                shutil.rmtree(output_dir)
            except Exception as e:
                print(f"Error cleanup: {e}")

def transcribe_and_translate_audio(audio_content: bytes) -> dict:
    r = sr.Recognizer()
    try:
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_content))
        wav_buffer = io.BytesIO()
        audio_segment.export(wav_buffer, format="wav", parameters=["-ac", "1", "-ar", "22050"])
        wav_buffer.seek(0)
        with sr.AudioFile(wav_buffer) as source:
            audio = r.record(source)
        return {"text_english": r.recognize_google(audio, language="en-US")}
    except Exception:
        return {"text_english": "Could not understand audio."}

# --- HELPER: Cleanup Logic ---
async def perform_cleanup(request: Request):
    user = request.session.get('user')
    if user and user.get('sub') != 'guest':
        user_id = user.get('sub')
        print(f"--- [CLEANUP] Deleting data for user: {user_id} ---")
        delete_user_collections(str(USERS_CHROMA_DB_PATH), user_id)
    request.session.clear()

# --- ROUTES ---

@app.get("/login/google")
async def login_google(request: Request):
    redirect_uri = "http://localhost:8000/auth/google/callback" 
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth/google/callback")
async def auth_google_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
        user = token.get('userinfo')
        if user:
            request.session['user'] = dict(user)
            return RedirectResponse(url='/upload')
    except Exception as e:
        return HTMLResponse(content=f"<h1>Authentication Failed</h1><p>{e}</p>")
    return RedirectResponse(url='/')

@app.get("/login/guest")
async def login_guest(request: Request):
    request.session['user'] = {'sub': 'guest', 'name': 'Guest User', 'email': 'guest@local'}
    return RedirectResponse(url='/chat')

@app.post("/end_session")
async def end_session(request: Request):
    """Called via AJAX/Beacon when tab closes."""
    await perform_cleanup(request)
    return JSONResponse(content={"message": "Session ended"})

@app.get("/logout")
async def logout(request: Request):
    """Called when user clicks Logout button."""
    await perform_cleanup(request)
    # REDIRECT to home page (Login)
    return RedirectResponse(url='/', status_code=303)

@app.get("/", response_class=HTMLResponse)
async def serve_login_page(request: Request):
    if request.session.get('user'):
        return RedirectResponse(url='/chat')
    path = ABSOLUTE_FRONTEND_PATH / "index.html"
    return HTMLResponse(content=path.read_text(encoding='utf-8'))

@app.get("/upload", response_class=HTMLResponse)
async def serve_upload_page(request: Request):
    user = request.session.get('user')
    if not user: return RedirectResponse(url='/')
    if user.get('sub') == 'guest': return RedirectResponse(url='/chat')
    path = ABSOLUTE_FRONTEND_PATH / "upload.html"
    return HTMLResponse(content=path.read_text(encoding='utf-8'))

@app.get("/chat", response_class=HTMLResponse)
async def serve_chat_page(request: Request):
    if not request.session.get('user'): return RedirectResponse(url='/')
    path = ABSOLUTE_FRONTEND_PATH / "chat.html"
    return HTMLResponse(content=path.read_text(encoding='utf-8'))

@app.get("/status/{collection_name}")
async def get_processing_status(collection_name: str):
    return {"status": processing_status.get(collection_name, "unknown")}

@app.post("/upload-pdf/")
async def upload_pdf(request: Request, file: UploadFile = File(...), background_tasks: BackgroundTasks = BackgroundTasks()):
    user = request.session.get('user')
    if not user: raise HTTPException(status_code=401, detail="Not authenticated")
    if user.get('sub') == 'guest': raise HTTPException(status_code=403, detail="Guests cannot upload.")

    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    if file_size > 1 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size exceeds 1MB limit.")

    try:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files allowed.")
        
        user_id = user.get('sub')
        safe_filename = sanitize_name(Path(file.filename).stem)
        temp_dir = USERS_DATA_FOLDER / f"temp_{user_id}_{safe_filename}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        file_path = temp_dir / file.filename
        
        with open(file_path, "wb") as buffer:
            while content := await file.read(1024 * 1024):  
                buffer.write(content)
        
        unique_col_name = get_unique_collection_name(user_id, safe_filename)
        background_tasks.add_task(run_processing_pipeline, file_path, unique_col_name, safe_filename)
        
        return {"filename": file.filename, "message": "Processing...", "collection_name": safe_filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

@app.post("/transcribe-audio/")
async def transcribe_audio(audio_file: UploadFile = File(...)):
    content = await audio_file.read()
    return transcribe_and_translate_audio(content)

@app.post("/chat")
async def handle_chat_message(request: Request, chat_req: ChatRequest):
    user = request.session.get('user')
    if not user: return {"answer": "Session expired."}
    
    user_id = user.get('sub')
    target_collection = None
    if user_id != 'guest' and chat_req.collection_name:
        target_collection = get_unique_collection_name(user_id, chat_req.collection_name)

    try:
        rag_chain = get_rag_chain_for_collection(str(USERS_CHROMA_DB_PATH), target_collection)
        if rag_chain is None: return {"answer": "System initializing..."}
            
        chat_history = []
        for msg in chat_req.history:
            if msg['role'] == 'user': chat_history.append(HumanMessage(content=msg['content']))
            elif msg['role'] == 'assistant': chat_history.append(AIMessage(content=msg['content']))
            
        result = rag_chain.invoke({"input": chat_req.message, "chat_history": chat_history})
        return {"answer": result["answer"]}
    except Exception as e:
        print(f"Chat Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user_info")
async def get_user_info(request: Request):
    user = request.session.get('user')
    if user: return {"name": user.get('name'), "email": user.get('email'), "picture": user.get('picture')}
    return {"error": "Not logged in"}