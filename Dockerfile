FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy backend requirements first (better caching)
COPY Backend/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy entire project
COPY . .

# Expose FastAPI port
EXPOSE 8000

# Run FastAPI app
CMD ["uvicorn", "Backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
