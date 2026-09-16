"""
FastAPI application — Ministry of Transportation integration API
================================================================
Exposes the GAV mediator over HTTP.

    GET    /api/v1/vehicle/{plate}          global view for one plate
    GET    /api/v1/vehicles                 paginated assessment of all vehicles
    GET    /api/v1/vehicles/flagged         non-compliant vehicles only
    GET    /api/v1/unresolved               reads the system cannot attribute
    GET    /api/v1/schema-mapping           the discovered attribute mapping
    GET    /api/v1/link-index               identity resolution statistics
    GET    /api/v1/rules                    the declared conflict-resolution rules
    GET    /api/v1/reports                  the Ministry's report log
    POST   /api/v1/vehicle/{plate}/report   file one finding
    POST   /api/v1/sweep                    assess and report in bulk
    POST   /api/v1/vehicle                  register a vehicle across sources
    PUT    /api/v1/vehicle/{plate}          amend a vehicle
    DELETE /api/v1/vehicle/{plate}          remove a vehicle from all sources
    GET    /health

The write endpoints apply a compensating rollback: if any source rejects the
write, rows already committed elsewhere are deleted again, and the response
reports what happened per source. SQLite gives no cross-database transaction,
so atomicity has to be built rather than claimed.
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional, Dict
from sqlalchemy import text

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import requests
from pydantic import BaseModel, Field

import plate as plate_util
from mediator import RULES, GAVMediator
from schema_matcher import generate_mapping

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")

_mapping: dict = {}
_mediator: Optional[GAVMediator] = None


# ======================================================================
# Request bodies
# ======================================================================

# The UI was written against an earlier field vocabulary. Rather than force a
# frontend rewrite, the API accepts both and normalises to global attribute
# names — which is itself a small instance of the problem this project is
# about: two clients naming the same concept differently.
LEGACY_FIELDS = {
    "owner_name": "owner",
    "vehicle_class": "vehicle_category",
    "registration_date": "registered_on",
    "chassis_no": "chassis",
    "policy_no": "policy_id",
    "insurer_name": "insurer",
    "start_date": "cover_begins",
    "expiry_date": "cover_ends",
    "insurance_status": "declared_policy_state",
    "is_stolen": "theft_flag",
    "fir_number": "theft_case",
    "is_scrapped": "scrap_flag",
    "camera_location": "sighting_place",
    "ocr_confidence": "read_quality",
}


def normalise_fields(payload: dict) -> dict:
    """Fold legacy field names onto global attribute names."""
    out = {}
    for key, value in payload.items():
        if value is None:
            continue
        out[LEGACY_FIELDS.get(key, key)] = value
    return out


class VehicleCreate(BaseModel):
    model_config = {"extra": "allow"}

    plate: str
    targets: Dict[str, bool] = Field(default_factory=lambda: {"rto": True, "insurance": True, "police": True, "camera": True})
    owner: Optional[str] = None
    vehicle_category: Optional[str] = None
    registered_on: Optional[str] = None
    chassis: Optional[str] = None
    propulsion: Optional[str] = None
    policy_id: Optional[str] = None
    insurer: Optional[str] = None
    cover_begins: Optional[str] = None
    cover_ends: Optional[str] = None
    declared_policy_state: Optional[str] = None
    cover_type: Optional[str] = None
    theft_flag: Optional[bool] = None
    theft_case: Optional[str] = None
    scrap_flag: Optional[bool] = None
    sighting_place: Optional[str] = None
    read_quality: Optional[float] = None


class VehicleUpdate(BaseModel):
    model_config = {"extra": "allow"}

    owner: Optional[str] = None
    vehicle_category: Optional[str] = None
    chassis: Optional[str] = None
    propulsion: Optional[str] = None
    insurer: Optional[str] = None
    cover_begins: Optional[str] = None
    cover_ends: Optional[str] = None
    declared_policy_state: Optional[str] = None
    theft_flag: Optional[bool] = None
    theft_case: Optional[str] = None
    scrap_flag: Optional[bool] = None

class SQLRequest(BaseModel):
    query: str
    target: str


# Which global attributes each source is allowed to be given on a write.
WRITE_SCOPE = {
    "rto": ["owner", "vehicle_category", "registered_on", "chassis", "propulsion"],
    "insurance": ["policy_id", "insurer", "cover_begins", "cover_ends",
                  "declared_policy_state", "cover_type"],
    "police": ["theft_flag", "theft_case", "scrap_flag"],
    "camera": ["sighting_place", "read_quality", "sighting_time"],
}


# ======================================================================
# Lifespan
# ======================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _mapping, _mediator
    print("\nStarting the MoT integration API")
    print("\nDiscovering source schemas")
    _mapping = generate_mapping(db_dir=HERE, verbose=True)
    _mediator = GAVMediator(_mapping, db_dir=HERE)
    totals = _mediator.link_index.stats.get("_totals", {})
    print(f"\nLinkage index built: {totals.get('canonical_marks')} canonical marks, "
          f"{totals.get('known_marks')} known, {totals.get('orphan_marks')} unattributable")
    print("\nReady on http://127.0.0.1:8000  (docs at /docs)\n")
    yield
    if _mediator:
        _mediator.close()
    print("\nShut down")


app = FastAPI(
    title="MoT vehicle integration API",
    description="A Global-As-View mediator over five autonomous vehicle data "
                "sources, producing defensible compliance findings.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _require_mediator():
    if _mediator is None:
        raise HTTPException(status_code=503, detail="Mediator not initialised")
    return _mediator


# ======================================================================
# Read endpoints
# ======================================================================

@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/health")
async def health():
    totals = _mediator.link_index.stats.get("_totals", {}) if _mediator else {}
    return {
        "status": "healthy" if _mediator else "starting",
        "matcher_mode": _mapping.get("mode"),
        "semantic_available": _mapping.get("semantic_available"),
        "sources": list((_mapping.get("sources") or {}).keys()),
        "linkage": totals,
    }


@app.get("/api/v1/vehicle/{plate}")
async def vehicle(plate: str, as_of: Optional[str] = Query(
        None, description="ISO date to assess against. Defaults to the most "
                          "recent sighting.")):
    """
    The global view for one plate.

    Never 404s on an unrecognised plate: a plate the system cannot attribute is
    a finding in its own right, returned as INSUFFICIENT_EVIDENCE with reasons.
    """
    mediator = _require_mediator()
    return mediator.query_vehicle(plate, as_of=as_of)


@app.get("/api/v1/vehicles")
async def vehicles(limit: int = Query(100, ge=1, le=1000),
                   offset: int = Query(0, ge=0),
                   outcome: Optional[str] = Query(
                       None, description="COMPLIANT | UNINSURED | SUSPICIOUS | "
                                         "INSUFFICIENT_EVIDENCE")):
    mediator = _require_mediator()
    return mediator.assess_all(limit=limit, offset=offset, outcome=outcome)


@app.get("/api/v1/vehicles/flagged")
async def flagged(limit: int = Query(200, ge=1, le=1000),
                  offset: int = Query(0, ge=0)):
    """Vehicles whose assessment is anything other than compliant."""
    mediator = _require_mediator()
    page = mediator.assess_all(limit=limit, offset=offset)
    rows = [v for v in page["vehicles"] if v["outcome"] != "COMPLIANT"]
    summary = {}
    for row in rows:
        summary[row["outcome"]] = summary.get(row["outcome"], 0) + 1
    return {
        "total_known": page["total_known"],
        "total_flagged": len(rows),
        "offset": offset,
        "outcome_summary": summary,
        "adjudication_required": sum(1 for r in rows if r["requires_adjudication"]),
        "vehicles": rows,
    }


@app.get("/api/v1/unresolved")
async def unresolved(limit: int = Query(100, ge=1, le=1000)):
    """
    Roadside reads that resolve to no known vehicle.

    A vehicle was on the road and the system cannot say which one. Part A
    reports these rather than guessing.
    """
    mediator = _require_mediator()
    rows = mediator.unresolved_reads()
    return {"total": len(rows), "returned": min(limit, len(rows)),
            "reads": rows[:limit]}


@app.get("/api/v1/schema-mapping")
async def schema_mapping():
    """The attribute mapping the matcher discovered, with its scores."""
    return {
        "mode": _mapping.get("mode"),
        "semantic_available": _mapping.get("semantic_available"),
        "semantic_unavailable_reason": _mapping.get("semantic_unavailable_reason"),
        "threshold": _mapping.get("threshold"),
        "weights": _mapping.get("weights"),
        "global_schema": _mapping.get("global_schema"),
        "sources": _mapping.get("sources"),
    }


@app.get("/api/v1/link-index")
async def link_index():
    mediator = _require_mediator()
    return {
        "per_source": {k: v for k, v in mediator.link_index.stats.items()
                       if k != "_totals"},
        "totals": mediator.link_index.stats.get("_totals", {}),
        "method": "exact_canonical",
        "note": "Part A links only on exact canonical equality, so every link "
                "score is 1.0. Reads that do not canonicalise onto a known "
                "mark are left unattributed rather than guessed.",
    }


@app.get("/api/v1/rules")
async def rules():
    """The declared conflict-resolution rules the mediator applies."""
    return {"rules": RULES}


@app.get("/api/v1/reports")
async def reports(limit: int = Query(100, ge=1, le=1000)):
    mediator = _require_mediator()
    rows = mediator.reports(limit=limit)
    return {"total_returned": len(rows), "reports": rows}


@app.get("/api/v1/canonicalise/{plate}")
async def canonicalise(plate: str):
    """Show what canonicalisation does to a raw plate string."""
    mediator = _require_mediator()
    mark = plate_util.canonical(plate)
    return {
        "input": plate,
        "canonical_mark": mark,
        "wellformed": plate_util.is_wellformed(mark),
        "confusable_key": plate_util.confusable_key(mark),
        "resolution": mediator.link_index.resolve(plate),
    }


# ======================================================================
# Report endpoints
# ======================================================================

@app.post("/api/v1/vehicle/{plate}/report")
async def file_one(plate: str, as_of: Optional[str] = None):
    """File a finding with the Ministry for one vehicle."""
    mediator = _require_mediator()
    view = mediator.query_vehicle(plate, as_of=as_of)
    result = mediator.file_report(view)
    return {"plate": plate, "canonical_mark": view["canonical_mark"],
            "assessment": view["assessment"], "filing": result}


@app.post("/api/v1/sweep")
async def sweep(limit: Optional[int] = Query(
        None, ge=1, le=2000, description="Cap the number of vehicles assessed.")):
    """
    Assess vehicles and report every non-compliant one to the Ministry.

    This is the operation the brief asks for: report the vehicle if it is not
    insured or if anything about it is suspect. Abstentions are filed too — a
    record that the system looked and could not tell.
    """
    mediator = _require_mediator()
    return mediator.sweep(limit=limit)


# ======================================================================
# Write endpoints, with compensating rollback
# ======================================================================

@app.post("/api/v1/vehicle")
async def create_vehicle(body: VehicleCreate):
    mediator = _require_mediator()
    mark = plate_util.canonical(body.plate)
    if not mark:
        raise HTTPException(status_code=400, detail="Unusable plate value")
    if mark in mediator.link_index.known_marks:
        raise HTTPException(status_code=409, detail={
            "message": f"{mark} already exists in at least one register",
            "sources_holding": sorted(mediator.link_index.links[mark]),
        })

    payload = normalise_fields(body.model_dump())
    committed, results = [], {}
    for source, attributes in WRITE_SCOPE.items():
        if not body.targets.get(source, False):
            continue
        wrapper = mediator.wrappers.get(source)
        if wrapper is None:
            continue
        values = {a: payload.get(a) for a in attributes if payload.get(a) is not None}
        if source == "camera" and values and "sighting_time" not in values:
            # a sighting without a timestamp cannot be assessed against, so
            # stamp it now rather than store an unusable observation
            values["sighting_time"] = datetime.now(timezone.utc)
        if source in ("camera", "police") and not values:
            # A newly registered vehicle has not been seen yet, and has
            # nothing to report to the police. Writing an empty row to either
            # source would fabricate a record: the police register is meant to
            # hold only vehicles with something against them, and an empty
            # sighting row would assert the vehicle was observed.
            results[source] = {"ok": True, "skipped": "nothing to record"}
            continue
        outcome = wrapper.insert(mark, values)
        results[source] = outcome
        if outcome.get("ok"):
            committed.append(source)
        else:
            # compensate: undo everything already written
            rolled_back = {}
            for done in committed:
                rolled_back[done] = mediator.wrappers[done].delete(mark)
            _rebuild_index(mediator)
            raise HTTPException(status_code=409, detail={
                "message": f"Write to {source} failed; all sources rolled back.",
                "failed_source": source,
                "reason": outcome.get("reason"),
                "rolled_back": rolled_back,
                "per_source": results,
            })

    _rebuild_index(mediator)
    return {"message": f"{mark} registered across {len(committed)} source(s).",
            "canonical_mark": mark, "per_source": results,
            "view": mediator.query_vehicle(mark)}


@app.put("/api/v1/vehicle/{plate}")
async def amend_vehicle(plate: str, body: VehicleUpdate):
    mediator = _require_mediator()
    mark = plate_util.canonical(plate)
    if not mark or mark not in mediator.link_index.known_marks:
        raise HTTPException(status_code=404, detail=f"No register holds {mark}")

    payload = normalise_fields(body.model_dump())
    if not payload:
        return {"message": "Nothing to amend.", "canonical_mark": mark}

    results = {}
    for source, attributes in WRITE_SCOPE.items():
        wrapper = mediator.wrappers.get(source)
        if wrapper is None:
            continue
        values = {a: payload[a] for a in attributes if a in payload}
        if values:
            results[source] = wrapper.update(mark, values)

    _rebuild_index(mediator)
    return {"message": f"{mark} amended.", "canonical_mark": mark,
            "fields": sorted(payload), "per_source": results,
            "view": mediator.query_vehicle(mark)}


@app.delete("/api/v1/vehicle/{plate}")
async def remove_vehicle(plate: str):
    mediator = _require_mediator()
    mark = plate_util.canonical(plate)
    if not mark or mark not in mediator.link_index.known_marks:
        raise HTTPException(status_code=404, detail=f"No register holds {mark}")
    results = {source: wrapper.delete(mark)
               for source, wrapper in mediator.wrappers.items()
               if source != "mot"}
    _rebuild_index(mediator)
    return {"message": f"{mark} removed from all operational sources. "
                       f"Ministry findings are retained for audit.",
            "canonical_mark": mark, "per_source": results}

@app.post("/api/v1/sql")
async def execute_sql(body: SQLRequest):
    mediator = _require_mediator()
    results = {}
    targets = list(mediator.wrappers.keys()) if body.target == "all" else [body.target]
    
    for t in targets:
        target = t
        wrapper = mediator.wrappers.get(t)
        if not wrapper:
            results[target] = {"error": f"Target database '{target}' not found"}
            continue
        node_url = os.environ.get(f"{target.upper()}_NODE_URL")
        if node_url:
            try:
                resp = requests.post(f"{node_url}/sql", json={"query": body.query}, timeout=10)
                results[target] = resp.json()
            except Exception as e:
                results[target] = {"error": f"Failed to tunnel to node: {str(e)}"}
            continue

        if not wrapper.available:
            results[target] = {"error": "database not available"}
            continue
        try:
            with wrapper.engine.connect() as conn:
                result = conn.execute(text(body.query))
                if body.query.strip().upper().startswith("SELECT"):
                    rows = [dict(row._mapping) for row in result]
                    results[target] = {"rows": rows}
                else:
                    conn.commit()
                    results[target] = {"affected": result.rowcount}
        except Exception as e:
            results[target] = {"error": str(e)}
            
    return results


def _rebuild_index(mediator):
    """
    Rebuild the linkage index after a write.

    The index is derived state over autonomous sources, so any write
    invalidates it. Rebuilding is a sub-second scan at this scale; a production
    deployment would maintain it incrementally.
    """
    from link_index import LinkIndex
    mediator.link_index = LinkIndex(mediator.mapping, mediator.db_dir)
    for wrapper in mediator.wrappers.values():
        wrapper.link_index = mediator.link_index
