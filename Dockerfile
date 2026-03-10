FROM python:3.10-slim

# Set initial working directory
WORKDIR /app

# Install system dependencies (ffmpeg + libraries for opencv/torch)
RUN apt-get update && \
    apt-get install -y ffmpeg libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# Copy backend requirements
COPY Backend/requirements.txt .

# Install Python dependencies
RUN pip install \
    --no-cache-dir \
    --default-timeout=300 \
    --retries=10 \
    -r requirements.txt

# Copy entire project
COPY . .

# --- FIX 1: Set Workdir to Backend ---
# This ensures subprocess calls like "python Base.py" find the file
WORKDIR /app/Backend

# --- FIX 2: Add /app to PYTHONPATH ---
# This allows "from Backend.rag_components" to work even though we are inside Backend
ENV PYTHONPATH=/app

# Expose FastAPI port
EXPOSE 8000

# Run FastAPI app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]