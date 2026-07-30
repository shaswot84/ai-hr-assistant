from fastapi import FastAPI

app = FastAPI(title="AI HR Assistant")


@app.get("/health")
async def health():
    return {"status": "ok"}
