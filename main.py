from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"Hello": "World", "version": "6.0.0"}

@app.get("/version")
def version():
    return {"version": "6.0.0", "status": "working"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)