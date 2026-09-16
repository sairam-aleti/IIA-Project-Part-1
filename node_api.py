import os
import logging
from sqlalchemy import text, create_engine
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(filename='system.log', level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")

app = FastAPI(title="Node API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

engine = create_engine(f'sqlite:///{os.path.join(HERE, "rto.db")}')

class SQLRequest(BaseModel):
    query: str

@app.post("/sql")
async def execute_sql(body: SQLRequest):
    logger.info(f"Executing tunneled SQL: {body.query}")
    try:
        with engine.connect() as conn:
            result = conn.execute(text(body.query))
            if body.query.strip().upper().startswith("SELECT"):
                rows = [dict(row._mapping) for row in result]
                return {"success": True, "rows": rows}
            else:
                conn.commit()
                return {"success": True, "affected": result.rowcount}
    except Exception as e:
        logger.error(f"SQL Error: {str(e)}")
        return {"success": False, "error": str(e)}

@app.get("/health")
async def health():
    return {"status": "ok", "node": "rto"}

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
@app.get("/{full_path:path}")
async def serve_ui():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

