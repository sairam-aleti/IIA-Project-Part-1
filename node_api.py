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

engine = create_engine(f'sqlite:///{os.path.join(HERE, "police.db")}')

def init_db():
    with engine.connect() as conn:
        conn.execute(text("""
CREATE TABLE IF NOT EXISTS stolen_vehicles (
    vehicle_mark TEXT PRIMARY KEY,
    reported_stolen_on DATE,
    fir_number TEXT,
    status TEXT
)
"""))
        conn.commit()

init_db()

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
    return {"status": "ok", "node": "police"}

@app.get("/logs")
async def get_logs():
    try:
        with open("system.log", "r") as f:
            lines = f.readlines()
        return {"success": True, "logs": lines[-50:]}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/schema")
async def schema():
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = {}
    for table in inspector.get_table_names():
        tables[table] = [
            {"name": col["name"], "kind": str(col["type"])}
            for col in inspector.get_columns(table)
        ]
    return {"tables": tables}

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
@app.get("/{full_path:path}")
async def serve_ui(full_path: str = ""):
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
