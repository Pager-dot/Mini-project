import os
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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

# --- NEW: Auth Imports ---
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth

# --- Import RAG components ---
from rag_components import load_models, get_rag_chain_for_collection, check_and_ingest_json

# --- Global Status Tracker ---
processing_status: Dict[str, str] = {}
# --- Configuration (LOADED FROM ENV) ---
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
SECRET_KEY = os.getenv("SECRET_KEY")

# Optional: Raise an error if keys are missing (Good for debugging)
if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    raise ValueError("Missing Google Auth credentials in .env file")

# --- Lifespan event handler ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application startup...")
    load_models()       
    check_and_ingest_json() 
    yield
    print("Application shutdown...")

app = FastAPI(lifespan=lifespan)

# --- NEW: Add Session Middleware ---
# This allows the server to remember the logged-in user via a cookie
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, https_only=False, same_site="lax")
# --- NEW: Setup OAuth ---
oauth = OAuth()
oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)

class ChatRequest(BaseModel):
    message: str
    collection_name: str | None = None
    history: list[dict] = []

ABSOLUTE_FRONTEND_PATH = Path(__file__).parent.parent / "Frontend(basic)"
PDF_FOLDER = Path(__file__).parent / "pdf"
PDF_FOLDER.mkdir(exist_ok=True) 

try:
    app.mount("/static", StaticFiles(directory=ABSOLUTE_FRONTEND_PATH), name="static")
except RuntimeError as e:
    print(f"FATAL ERROR: StaticFiles could not find the directory at: {ABSOLUTE_FRONTEND_PATH}")
    raise e 

def sanitize_name(name: str) -> str:
    name = name.replace(' ', '_')
    name = re.sub(r'[^a-zA-Z0-9._-]', '', name)
    if len(name) < 3: name = f"doc_{name}"
    if not name[0].isalnum(): name = f"c_{name}"
    if not name[-1].isalnum(): name = f"{name}_c"
    return name[:63]

def run_processing_pipeline(pdf_path: Path, collection_name: str):
    global processing_status
    try:
        processing_status[collection_name] = "processing"
        
        file_stem = collection_name
        original_stem = pdf_path.stem
        output_dir = Path(__file__).parent / original_stem
        base_md_file = output_dir / f"{original_stem}.md"
        described_md_file = output_dir / f"{original_stem}_with_descriptions.md"
        python_executable = sys.executable
        
        print(f"\n--- [PIPELINE START] Processing: {pdf_path.name} ---")

        subprocess.run([python_executable, "Base.py", str(pdf_path)], check=True, capture_output=True, text=True)
        subprocess.run([python_executable, "Image-Testo.py", str(base_md_file), str(output_dir), str(described_md_file)], check=True, capture_output=True, text=True)
        subprocess.run([python_executable, "Emmbed.py", str(described_md_file), file_stem], check=True, capture_output=True, text=True)
        
        print(f"--- [PIPELINE SUCCESS] Finished processing ---")
        processing_status[collection_name] = "completed"

    except Exception as e:
        print(f"!!!!!! [PIPELINE FAILED] {e} !!!!!!")
        processing_status[collection_name] = "failed"

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

# --- AUTH ROUTES ---

@app.get("/login/google")
async def login_google(request: Request):
    # FORCE the redirect_uri to match exactly what is in your Google Console
    # Choose ONE consistency: localhost usually works best.
    redirect_uri = "http://localhost:8000/auth/google/callback" 
    
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth/google/callback")
async def auth_google_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
        user = token.get('userinfo')
        if user:
            # Store user info in the session (cookie)
            request.session['user'] = dict(user)
            # Redirect to the upload page
            return RedirectResponse(url='/upload')
    except Exception as e:
        print(f"Auth Error: {e}")
        return HTMLResponse(content=f"<h1>Authentication Failed</h1><p>{e}</p>")
    
    return RedirectResponse(url='/')

@app.get("/logout")
async def logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url='/')

# --- APP ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def serve_login_page(request: Request):
    # Check if user is already logged in
    user = request.session.get('user')
    if user:
        return RedirectResponse(url='/upload')

    login_file_path = ABSOLUTE_FRONTEND_PATH / "index.html"
    if not login_file_path.exists():
        return HTMLResponse(status_code=404, content="Login page not found.")
    with open(login_file_path, 'r', encoding='utf-8') as f:
        return HTMLResponse(content=f.read())

@app.get("/upload", response_class=HTMLResponse)
async def serve_upload_page(request: Request):
    # Optional: Protect this route
    # if not request.session.get('user'):
    #     return RedirectResponse(url='/')
        
    upload_file_path = ABSOLUTE_FRONTEND_PATH / "upload.html"
    with open(upload_file_path, 'r', encoding='utf-8') as f:
        return HTMLResponse(content=f.read())

@app.get("/chat", response_class=HTMLResponse)
async def serve_chat_page(request: Request):
    # Optional: Protect this route
    # if not request.session.get('user'):
    #     return RedirectResponse(url='/')

    chat_file_path = ABSOLUTE_FRONTEND_PATH / "chat.html"
    with open(chat_file_path, 'r', encoding='utf-8') as f:
        return HTMLResponse(content=f.read())

@app.get("/status/{collection_name}")
async def get_processing_status(collection_name: str):
    status = processing_status.get(collection_name, "unknown")
    return {"status": status}

@app.post("/upload-pdf/")
async def upload_pdf(file: UploadFile = File(...), background_tasks: BackgroundTasks = BackgroundTasks()):
    # ... (Keep existing implementation unchanged)
    try:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are allowed.")
        file_path = PDF_FOLDER / file.filename
        with open(file_path, "wb") as buffer:
            while content := await file.read(1024 * 1024):  
                buffer.write(content)
        collection_name = sanitize_name(Path(file.filename).stem)
        background_tasks.add_task(run_processing_pipeline, file_path, collection_name)
        return {"filename": file.filename, "message": "File upload successful. Processing started.", "path": str(file_path), "collection_name": collection_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not upload file: {e}")

@app.post("/transcribe-audio/")
async def transcribe_audio(audio_file: UploadFile = File(...)):
    content = await audio_file.read()
    return transcribe_and_translate_audio(content)

@app.post("/chat")
async def handle_chat_message(request: ChatRequest):
    try:
        rag_chain = get_rag_chain_for_collection(request.collection_name)
        if rag_chain is None:
            return {"answer": "Processing document... please wait."}
        chat_history = []
        for msg in request.history:
            if msg['role'] == 'user': chat_history.append(HumanMessage(content=msg['content']))
            elif msg['role'] == 'assistant': chat_history.append(AIMessage(content=msg['content']))
        result = rag_chain.invoke({"input": request.message, "chat_history": chat_history})
        return {"answer": result["answer"]}
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
# --- Add this to main.py ---

@app.get("/user_info")
async def get_user_info(request: Request):
    user = request.session.get('user')
    if user:
        return {"name": user.get('name'), "email": user.get('email'), "picture": user.get('picture')}
    return {"error": "Not logged in"}