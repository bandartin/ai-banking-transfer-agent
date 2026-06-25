from fastapi import FastAPI

app = FastAPI(title="testapp", version="0.1.0")


@app.get("/")
async def root():
    return {"message": "testapp running"}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "testapp"}
