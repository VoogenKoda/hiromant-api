import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Laeme juurkausta .env faili
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from routers import analyze, astrology, payments, tarot

app = FastAPI(title="Uhhuu SaaS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze.router, prefix="/api", tags=["analyze"])
app.include_router(astrology.router, prefix="/api/astrology", tags=["astrology"])
app.include_router(payments.router, prefix="/api/payments", tags=["payments"])
app.include_router(tarot.router, prefix="/api/tarot", tags=["tarot"])

@app.get("/")
def read_root():
    return {"message": "Uhhuu SaaS API is running."}
