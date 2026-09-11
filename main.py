"""
FastAPI Application — MoT Vehicle Status API
=============================================
Exposes the GAV mediator as a REST API with full CRUD support.

Endpoints:
    GET    /api/v1/vehicle/{plate}     -> Full MoT_Report for a single vehicle
    GET    /api/v1/vehicles            -> All vehicles
    GET    /api/v1/vehicles/flagged    -> Flagged vehicles (uninsured/stolen/scrapped)
    POST   /api/v1/vehicle             -> Add a new vehicle across all 4 sources
    PUT    /api/v1/vehicle/{plate}     -> Update vehicle fields
    DELETE /api/v1/vehicle/{plate}     -> Delete vehicle from all sources
    GET    /api/v1/schema-mapping      -> Algorithmic schema mapping
    GET    /health                     -> Health check
"""

import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from schema_matcher import generate_mapping
from mediator import GAVMediator


# ==========================================
# Pydantic Request Models
# ==========================================

class VehicleCreate(BaseModel):
    """Request body for creating a new vehicle."""
    plate: str
    owner_name: str = "Unknown"
    vehicle_class: str = "Sedan"
    registration_date: Optional[str] = None
    chassis_no: Optional[str] = None
    policy_no: Optional[str] = None
    insurer_name: str = "AutoGuard Ltd"
    start_date: Optional[str] = None
    expiry_date: Optional[str] = None
    insurance_status: str = "Active"
    is_stolen: bool = False
    fir_number: Optional[str] = None
    is_scrapped: bool = False


class VehicleUpdate(BaseModel):
    """Request body for updating an existing vehicle."""
    owner_name: Optional[str] = None
    vehicle_class: Optional[str] = None
    chassis_no: Optional[str] = None
    policy_no: Optional[str] = None
    insurer_name: Optional[str] = None
    start_date: Optional[str] = None
    expiry_date: Optional[str] = None
    insurance_status: Optional[str] = None
    is_stolen: Optional[bool] = None
    fir_number: Optional[str] = None
    is_scrapped: Optional[bool] = None


# ==========================================
# Application State
# ==========================================

_schema_mapping: dict = {}
_mediator: GAVMediator | None = None


# ==========================================
# Lifespan (startup / shutdown)
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the schema matcher and mediator on startup."""
    global _schema_mapping, _mediator

    print("\n[*] Starting MoT Vehicle Status API...")

    db_dir = os.path.dirname(os.path.abspath(__file__))

    print("\n[*] Running Algorithmic Schema Matcher...")
    _schema_mapping = generate_mapping()
    print("[OK] Schema mapping generated.\n")

    _mediator = GAVMediator(_schema_mapping, db_dir=db_dir)
    print("[OK] GAV Mediator initialized.\n")

    print("=" * 50)
    print("  API is ready at http://127.0.0.1:8000")
    print("  API docs at   http://127.0.0.1:8000/docs")
    print("=" * 50)
    print()

    yield

    if _mediator:
        _mediator.close()
    print("\n[STOP] MoT API shut down.")


# ==========================================
# FastAPI App
# ==========================================

app = FastAPI(
    title="MoT Vehicle Status API",
    description=(
        "A Global-As-View (GAV) mediator system that integrates 4 heterogeneous "
        "vehicle databases (Camera, RTO, Insurance, Police) into a single unified "
        "API for the Ministry of Transportation."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware (allow React dev server and any origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files (React app)
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ==========================================
# READ Endpoints
# ==========================================

@app.get("/", include_in_schema=False)
async def root():
    """Serve the frontend UI."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "mediator_ready": _mediator is not None}


@app.get("/api/v1/vehicle/{plate}")
async def get_vehicle_report(plate: str):
    """Retrieve the unified MoT_Report for a vehicle via GAV query unfolding."""
    if _mediator is None:
        raise HTTPException(status_code=503, detail="Mediator not initialized")

    plate = plate.strip().upper()
    report = _mediator.query_vehicle(plate)

    if report is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"No records found for vehicle: {plate}",
                "vehicle_identifier": plate,
                "sources_queried": list(_mediator.wrappers.keys()),
            }
        )

    return report


@app.get("/api/v1/vehicles")
async def get_all_vehicles():
    """Retrieve all vehicles from the database."""
    if _mediator is None:
        raise HTTPException(status_code=503, detail="Mediator not initialized")

    vehicles = _mediator.query_all_vehicles()
    return {"total": len(vehicles), "vehicles": vehicles}


@app.get("/api/v1/vehicles/flagged")
async def get_flagged_vehicles():
    """Retrieve all vehicles with active flags (UNINSURED, STOLEN, SCRAPPED)."""
    if _mediator is None:
        raise HTTPException(status_code=503, detail="Mediator not initialized")

    flagged = _mediator.query_all_flagged()
    return {
        "total_flagged": len(flagged),
        "vehicles": flagged,
        "flag_summary": {
            "uninsured": sum(1 for v in flagged if "UNINSURED" in v["flags"]),
            "stolen": sum(1 for v in flagged if "STOLEN" in v["flags"]),
            "scrapped": sum(1 for v in flagged if "SCRAPPED" in v["flags"]),
        }
    }


@app.get("/api/v1/schema-mapping")
async def get_schema_mapping():
    """Expose the algorithmically generated schema mapping."""
    return {
        "global_key": "vehicle_identifier",
        "target_concept": "vehicle identifier registration license plate number",
        "mapping": _schema_mapping,
    }


# ==========================================
# WRITE Endpoints (CREATE, UPDATE, DELETE)
# ==========================================

@app.post("/api/v1/vehicle")
async def create_vehicle(body: VehicleCreate):
    """
    Register a new vehicle across all 4 source databases.
    This inserts records into RTO, Insurance, Police, and Camera DBs.
    """
    if _mediator is None:
        raise HTTPException(status_code=503, detail="Mediator not initialized")

    plate = body.plate.strip().upper()

    # Check if vehicle already exists
    existing = _mediator.query_vehicle(plate)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"message": f"Vehicle {plate} already exists.", "vehicle_identifier": plate}
        )

    data = body.model_dump()
    data["plate"] = plate

    results = _mediator.insert_vehicle(data)

    success = all(results.values())
    return {
        "message": f"Vehicle {plate} {'created successfully' if success else 'partially created'}.",
        "vehicle_identifier": plate,
        "source_results": results,
    }


@app.put("/api/v1/vehicle/{plate}")
async def update_vehicle(plate: str, body: VehicleUpdate):
    """
    Update vehicle fields across the relevant source databases.
    Only provided (non-null) fields will be updated.
    """
    if _mediator is None:
        raise HTTPException(status_code=503, detail="Mediator not initialized")

    plate = plate.strip().upper()

    # Check if vehicle exists
    existing = _mediator.query_vehicle(plate)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail={"message": f"Vehicle {plate} not found.", "vehicle_identifier": plate}
        )

    # Only send non-null fields
    data = {k: v for k, v in body.model_dump().items() if v is not None}

    if not data:
        return {"message": "No fields to update.", "vehicle_identifier": plate}

    results = _mediator.update_vehicle(plate, data)

    return {
        "message": f"Vehicle {plate} updated.",
        "vehicle_identifier": plate,
        "fields_updated": list(data.keys()),
        "source_results": results,
    }


@app.delete("/api/v1/vehicle/{plate}")
async def delete_vehicle(plate: str):
    """Delete a vehicle from all 4 source databases."""
    if _mediator is None:
        raise HTTPException(status_code=503, detail="Mediator not initialized")

    plate = plate.strip().upper()

    # Check if vehicle exists
    existing = _mediator.query_vehicle(plate)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail={"message": f"Vehicle {plate} not found.", "vehicle_identifier": plate}
        )

    results = _mediator.delete_vehicle(plate)

    return {
        "message": f"Vehicle {plate} deleted.",
        "vehicle_identifier": plate,
        "source_results": results,
    }
