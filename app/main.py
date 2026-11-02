import os, sqlite3, uuid, shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import httpx
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv("DATA_DIR", "/data"))
UPLOADS = DATA / "uploads"
DATA.mkdir(parents=True, exist_ok=True)
UPLOADS.mkdir(parents=True, exist_ok=True)
DB = DATA / "faults.db"
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "").strip()

app = FastAPI(title="Factory Fault Tracker")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS)), name="uploads")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS faults (
          id TEXT PRIMARY KEY, created_at TEXT NOT NULL, reporter TEXT NOT NULL,
          department TEXT NOT NULL, asset_code TEXT NOT NULL, fault_type TEXT NOT NULL,
          severity TEXT NOT NULL, description TEXT NOT NULL, photo_path TEXT,
          status TEXT NOT NULL DEFAULT 'New', assignee TEXT NOT NULL DEFAULT '',
          resolution TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
        )
        """)
init_db()

class UpdateFault(BaseModel):
    status: Optional[str] = None
    assignee: Optional[str] = None
    resolution: Optional[str] = None

@app.get("/", response_class=HTMLResponse)
def home():
    return (ROOT / "static" / "index.html").read_text(encoding="utf-8")

@app.get("/api/health")
def health():
    return {"ok": True, "app": "Factory Fault Tracker"}

@app.get("/api/faults")
def list_faults():
    with connect() as con:
        rows = con.execute("SELECT * FROM faults ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]

@app.post("/api/faults")
async def create_fault(
    reporter: str = Form(...), department: str = Form(...),
    asset_code: str = Form(...), fault_type: str = Form(...),
    severity: str = Form(...), description: str = Form(...),
    photo: UploadFile | None = File(default=None)
):
    reporter, department, asset_code = reporter.strip(), department.strip(), asset_code.strip()
    if not all([reporter, department, asset_code, fault_type, severity, description.strip()]):
        raise HTTPException(400, "Συμπλήρωσε όλα τα υποχρεωτικά πεδία.")
    fault_id = "FLT-" + datetime.now().strftime("%Y") + "-" + uuid.uuid4().hex[:8].upper()
    now = datetime.now(timezone.utc).isoformat()
    photo_path = None
    if photo and photo.filename:
        ext = Path(photo.filename).suffix.lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            raise HTTPException(400, "Η φωτογραφία πρέπει να είναι JPG, PNG ή WEBP.")
        saved = f"{fault_id}{ext}"
        target = UPLOADS / saved
        with target.open("wb") as out:
            shutil.copyfileobj(photo.file, out)
        photo_path = f"/uploads/{saved}"
    with connect() as con:
        con.execute("""INSERT INTO faults
        (id,created_at,reporter,department,asset_code,fault_type,severity,description,photo_path,status,assignee,resolution,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,'New','','',?)""",
        (fault_id, now, reporter, department, asset_code, fault_type, severity, description.strip(), photo_path, now))
    fault = {"id": fault_id, "created_at": now, "reporter": reporter, "department": department,
             "asset_code": asset_code, "fault_type": fault_type, "severity": severity,
             "description": description.strip(), "photo_path": photo_path, "status": "New", "assignee": ""}
    if TEAMS_WEBHOOK_URL:
        text = (f"ΝΕΑ ΒΛΑΒΗ: {fault_id}\nSeverity: {severity}\nΤμήμα: {department}\n"
                f"Εξοπλισμός: {asset_code}\nΤύπος: {fault_type}\nΑναφέρων: {reporter}\n"
                f"Περιγραφή: {description.strip()}\nΚατάσταση: New")
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.post(TEAMS_WEBHOOK_URL, json={"text": text})
                resp.raise_for_status()
        except Exception:
            # The report is saved even if Teams notification fails.
            pass
    return {"ok": True, "fault": fault}

@app.patch("/api/faults/{fault_id}")
def update_fault(fault_id: str, payload: UpdateFault):
    allowed = {"New", "Assigned", "In Progress", "Resolved"}
    with connect() as con:
        row = con.execute("SELECT * FROM faults WHERE id=?", (fault_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Δεν βρέθηκε η βλάβη.")
        status = payload.status if payload.status is not None else row["status"]
        if status not in allowed:
            raise HTTPException(400, "Μη έγκυρη κατάσταση.")
        assignee = payload.assignee.strip() if payload.assignee is not None else row["assignee"]
        resolution = payload.resolution.strip() if payload.resolution is not None else row["resolution"]
        now = datetime.now(timezone.utc).isoformat()
        con.execute("UPDATE faults SET status=?, assignee=?, resolution=?, updated_at=? WHERE id=?",
                    (status, assignee, resolution, now, fault_id))
        updated = con.execute("SELECT * FROM faults WHERE id=?", (fault_id,)).fetchone()
    return dict(updated)
