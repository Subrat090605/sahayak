import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Load environment variables from .env
load_dotenv()

app = FastAPI(
    title="Sahayak API",
    description="Voice-first multi-agent scheme discovery for Indian citizens",
)


@app.get("/health")
def health():
    return {"status": "ok"}


# Serve the static directory at the root
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
