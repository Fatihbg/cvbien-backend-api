from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os

app = FastAPI(title="CV Bien API", version="5.0.0")

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173", 
        "https://cvbien4.vercel.app",
        "https://cvbien.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "CV Bien API v5.0.0 - Simple Version", "status": "online"}

@app.get("/version")
async def version():
    return {
        "version": "5.0.0",
        "status": "Simple Version Active",
        "timestamp": "2025-01-06-01:00"
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "message": "API is running"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print(f"🚀 Démarrage du serveur simple sur le port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
