"""
Source wrappers
===============
One wrapper per source. A wrapper is configured entirely by the attribute
mapping the schema matcher produced: it contains no local column names, so
renaming a column in any source changes nothing here.

Each wrapper returns *facts*, and every fact carries the same envelope:

    {"value": ..., "source": "insurance", "column": "cover_upto",
     "confidence": 1.0, "retrieved_at": "...", "derivation": None}

In Part A every confidence is 1.0, because a value read directly out of a
source is known with certainty — the uncertainty in Part A lives in identity
resolution and in missing records, not in the values themselves. Part B will
populate the same field with real probabilities, and nothing downstream needs
to change shape.

`record_count` distinguishes the two ways a source can fail to answer:
    absent  — the source was reachable and holds no record for this vehicle
    error   — the source could not be reached
The mediator treats these very differently. Absence of an insurance record is
strong evidence of non-insurance; an unreachable insurer is no evidence at all.
"""

import os
import requests
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from dotenv import load_dotenv

from sqlalchemy import create_engine, text

import plate as plate_util

load_dotenv()


def _now():
    return datetime.now(timezone.utc).isoformat()


class BaseWrapper(ABC):
    """Shared machinery: mapped reads, normalisation, provenance."""

    source_name = None
    cardinality = "one"          # "one" row per vehicle, or "many"

    def __init__(self, db_path, source_conf, link_index):
        self.db_path = db_path
        self.table = source_conf.get("table")
        self.attributes = source_conf.get("attributes", {})
        self.unmapped = source_conf.get("unmapped", [])
        self.link_index = link_index
        self.available = bool(self.table) and os.path.exists(db_path)
        self.engine = create_engine(f"sqlite:///{db_path}") if self.available else None

    # -- mapping helpers ----------------------------------------------
    def column_for(self, attribute):
        """Local column carrying a global attribute, or None if unmapped."""
        info = self.attributes.get(attribute)
        return info["column"] if info else None

    def _fact(self, attribute, row, derivation=None, confidence=1.0):
        """Lift one mapped attribute out of a row into a provenance-tagged fact."""
        column = self.column_for(attribute)
        if column is None:
            return None
        value = row.get(column)
        return {
            "value": self._normalise(value),
            "source": self.source_name,
            "table": self.table,
            "column": column,
            "confidence": confidence,
            "derivation": derivation,
            "retrieved_at": _now(),
        }

    @staticmethod
    def _normalise(value):
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return value

    # -- querying -----------------------------------------------------
    def _rows_for(self, mark):
        """
        Fetch every row this source holds for a canonical mark.

        The query uses the raw values the linkage index recorded for this
        source, which is how format divergence is bridged: the wrapper never
        needs to know that the insurers write marks with spaces.
        """
        if not self.available:
            return None
        raws = self.link_index.raw_values(mark, self.source_name)
        if not raws:
            return []
        column = self.column_for("vehicle_mark")
        if column is None:
            return []
        placeholders = ", ".join(f":v{i}" for i in range(len(raws)))
        params = {f"v{i}": raw for i, raw in enumerate(raws)}
        sql_str = f"SELECT * FROM {self.table} WHERE {column} IN ({placeholders})"
        
        node_url = os.environ.get(f"{self.source_name.upper()}_NODE_URL")
        if node_url:
            try:
                resp = requests.post(f"{node_url}/sql", json={"query": sql_str, "params": params}, timeout=10)
                data = resp.json()
                if data.get("success"):
                    return data.get("rows", [])
            except Exception as e:
                pass
            return []

        sql = text(sql_str)
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).mappings().all()]

    def query(self, mark):
        """
        Standard envelope for every source.

        Returns {"status": "present"|"absent"|"error"|"unavailable",
                 "record_count": int, "facts": {...}, "extra": {...}}
        """
        if not self.available:
            return {"status": "unavailable", "record_count": 0, "facts": {},
                    "source": self.source_name,
                    "note": "source not reachable or no mapped table"}
        try:
            rows = self._rows_for(mark)
        except Exception as exc:                       # noqa: BLE001
            return {"status": "error", "record_count": 0, "facts": {},
                    "source": self.source_name, "note": f"{type(exc).__name__}: {exc}"}

        if not rows:
            return {"status": "absent", "record_count": 0, "facts": {},
                    "source": self.source_name}

        return self._shape(rows)

    @abstractmethod
    def _shape(self, rows):
        """Turn raw rows into the fact envelope for this source."""

    # -- writing ------------------------------------------------------
    # A wrapper adapts to its source's conventions, and the plate format is
    # one of those conventions. `plate_format` is the only source-specific
    # knowledge left in these classes; everything else comes from the mapping.
    plate_format = "compact"

    def format_mark(self, mark):
        if self.plate_format == "hyphenated":
            return plate_util.as_hyphenated(mark)
        if self.plate_format == "spaced":
            return plate_util.as_spaced(mark)
        return mark

    def insert(self, mark, values):
        """
        Insert one row, translating global attribute names to local columns.

        `values` is keyed by global attribute. Unmapped attributes are dropped
        rather than guessed at. Returns the inserted row's key column value so
        the caller can compensate if a later source fails.
        """
        if not self.available:
            return {"ok": False, "reason": "source unavailable"}
        raw_mark = self.format_mark(mark)
        columns = {self.column_for("vehicle_mark"): raw_mark}
        for attribute, value in values.items():
            column = self.column_for(attribute)
            if column and value is not None:
                columns[column] = value
        columns = {c: v for c, v in columns.items() if c}
        if not columns:
            return {"ok": False, "reason": "no mapped columns for this source"}

        names = list(columns)
        binds = [f":b{i}" for i in range(len(names))]
        params = {f"b{i}": columns[n] for i, n in enumerate(names)}
        sql_str = f"INSERT INTO {self.table} ({', '.join(names)}) VALUES ({', '.join(binds)})"
        
        node_url = os.environ.get(f"{self.source_name.upper()}_NODE_URL")
        if node_url:
            try:
                resp = requests.post(f"{node_url}/sql", json={"query": sql_str, "params": params}, timeout=10)
                if not resp.json().get("success"):
                    return {"ok": False, "reason": resp.json().get("error")}
                return {"ok": True, "raw_mark": raw_mark, "columns": names}
            except Exception as exc:
                return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

        sql = text(sql_str)
        try:
            with self.engine.begin() as conn:
                conn.execute(sql, params)
        except Exception as exc:                       # noqa: BLE001
            return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
        return {"ok": True, "raw_mark": raw_mark, "columns": names}

    def update(self, mark, values):
        if not self.available:
            return {"ok": False, "reason": "source unavailable"}
        raws = self.link_index.raw_values(mark, self.source_name)
        if not raws:
            return {"ok": True, "changed": 0, "reason": "no row in this source"}
        assignments, params = [], {}
        for i, (attribute, value) in enumerate(values.items()):
            column = self.column_for(attribute)
            if column and value is not None:
                assignments.append(f"{column} = :s{i}")
                params[f"s{i}"] = value
        if not assignments:
            return {"ok": True, "changed": 0, "reason": "nothing mapped to update"}
        key = self.column_for("vehicle_mark")
        placeholders = ", ".join(f":k{i}" for i in range(len(raws)))
        params.update({f"k{i}": raw for i, raw in enumerate(raws)})
        sql_str = f"UPDATE {self.table} SET {', '.join(assignments)} WHERE {key} IN ({placeholders})"
        
        node_url = os.environ.get(f"{self.source_name.upper()}_NODE_URL")
        if node_url:
            try:
                resp = requests.post(f"{node_url}/sql", json={"query": sql_str, "params": params}, timeout=10)
                if not resp.json().get("success"):
                    return {"ok": False, "reason": resp.json().get("error")}
                return {"ok": True, "changed": resp.json().get("affected", 0)}
            except Exception as exc:
                return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

        sql = text(sql_str)
        try:
            with self.engine.begin() as conn:
                result = conn.execute(sql, params)
        except Exception as exc:                       # noqa: BLE001
            return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
        return {"ok": True, "changed": result.rowcount}

    def delete(self, mark):
        if not self.available:
            return {"ok": False, "reason": "source unavailable"}
        raws = self.link_index.raw_values(mark, self.source_name)
        if not raws:
            return {"ok": True, "changed": 0, "reason": "no row in this source"}
        key = self.column_for("vehicle_mark")
        placeholders = ", ".join(f":k{i}" for i in range(len(raws)))
        params = {f"k{i}": raw for i, raw in enumerate(raws)}
        sql_str = f"DELETE FROM {self.table} WHERE {key} IN ({placeholders})"
        
        node_url = os.environ.get(f"{self.source_name.upper()}_NODE_URL")
        if node_url:
            try:
                resp = requests.post(f"{node_url}/sql", json={"query": sql_str, "params": params}, timeout=10)
                if not resp.json().get("success"):
                    return {"ok": False, "reason": resp.json().get("error")}
                return {"ok": True, "changed": resp.json().get("affected", 0)}
            except Exception as exc:
                return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

        sql = text(sql_str)
        try:
            with self.engine.begin() as conn:
                result = conn.execute(sql, params)
        except Exception as exc:                       # noqa: BLE001
            return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
        return {"ok": True, "changed": result.rowcount}

    def close(self):
        if self.engine:
            self.engine.dispose()


# ======================================================================

class RTOWrapper(BaseWrapper):
    source_name = "rto"
    plate_format = "hyphenated"

    def _shape(self, rows):
        row = rows[0]
        facts = {a: self._fact(a, row) for a in
                 ("owner", "vehicle_category", "registered_on", "chassis", "propulsion")}
        return {"status": "present", "record_count": len(rows),
                "source": self.source_name,
                "facts": {k: v for k, v in facts.items() if v}}


class InsuranceWrapper(BaseWrapper):
    """
    Returns the whole policy history, not a single flag.

    Whether a vehicle is insured depends on the moment asked about, so the
    wrapper's job is to surface every cover period it holds and let the
    mediator evaluate them against a timestamp.
    """
    source_name = "insurance"
    cardinality = "many"
    plate_format = "spaced"

    def _shape(self, rows):
        begins_col = self.column_for("cover_begins")
        ends_col = self.column_for("cover_ends")

        periods = []
        for row in rows:
            periods.append({
                "policy_id": self._fact("policy_id", row),
                "insurer": self._fact("insurer", row),
                "cover_begins": self._fact("cover_begins", row),
                "cover_ends": self._fact("cover_ends", row),
                "declared_policy_state": self._fact("declared_policy_state", row),
                "cover_type": self._fact("cover_type", row),
            })
        periods.sort(key=lambda p: (p["cover_begins"] or {}).get("value") or "")

        return {"status": "present", "record_count": len(rows),
                "source": self.source_name,
                "facts": {},
                "cover_periods": periods,
                "period_columns": {"begins": begins_col, "ends": ends_col}}


class PoliceWrapper(BaseWrapper):
    source_name = "police"

    def _shape(self, rows):
        row = rows[0]
        facts = {}
        for attr in ("theft_flag", "scrap_flag"):
            fact = self._fact(attr, row)
            if fact:
                fact["value"] = bool(fact["value"])
                facts[attr] = fact
        for attr in ("theft_case", "recovered_on", "scrap_certificate",
                     "record_amended_on"):
            fact = self._fact(attr, row)
            if fact:
                facts[attr] = fact
        return {"status": "present", "record_count": len(rows),
                "source": self.source_name, "facts": facts}


class CameraWrapper(BaseWrapper):
    """Returns every sighting, most recent first."""
    source_name = "camera"
    cardinality = "many"

    def _shape(self, rows):
        time_col = self.column_for("sighting_time")
        sightings = []
        for row in rows:
            sightings.append({
                "sighting_id": self._fact("sighting_id", row),
                "sighting_time": self._fact("sighting_time", row),
                "sighting_place": self._fact("sighting_place", row),
                "read_quality": self._fact("read_quality", row),
            })
        if time_col:
            sightings.sort(key=lambda s: (s["sighting_time"] or {}).get("value") or "",
                           reverse=True)
        return {"status": "present", "record_count": len(rows),
                "source": self.source_name, "facts": {},
                "sightings": sightings}


class MoTWrapper(BaseWrapper):
    """
    The reporting sink. Readable like any other source, and writable — this is
    the only source the mediator writes to as part of normal operation.
    """
    source_name = "mot"
    cardinality = "many"

    def _shape(self, rows):
        raised_col = self.column_for("raised_on")
        findings = []
        for row in rows:
            findings.append({
                "finding": self._fact("finding", row),
                "severity": self._fact("severity", row),
                "finding_confidence": self._fact("finding_confidence", row),
                "evidence": self._fact("evidence", row),
                "raised_on": self._fact("raised_on", row),
                "source_sighting": self._fact("source_sighting", row),
            })
        if raised_col:
            findings.sort(key=lambda f: (f["raised_on"] or {}).get("value") or "",
                          reverse=True)
        return {"status": "present", "record_count": len(rows),
                "source": self.source_name, "facts": {},
                "prior_findings": findings}

    # -- write path ---------------------------------------------------
    def file_report(self, report_ref, mark, finding, severity, confidence,
                    evidence_json, triggering_read=None):
        """Persist one compliance finding. Returns True on commit."""
        if not self.available:
            return False
        cols = {
            "vehicle_mark": self.column_for("vehicle_mark"),
            "finding": self.column_for("finding"),
            "severity": self.column_for("severity"),
            "finding_confidence": self.column_for("finding_confidence"),
            "evidence": self.column_for("evidence"),
            "raised_on": self.column_for("raised_on"),
            "source_sighting": self.column_for("source_sighting"),
        }
        if any(c is None for k, c in cols.items() if k != "source_sighting"):
            return False
        # the primary key column is whatever the matcher did not claim as an
        # attribute; look it up from the table definition rather than assuming
        pk = self._primary_key()
        names = [pk, cols["vehicle_mark"], cols["finding"], cols["severity"],
                 cols["finding_confidence"], cols["evidence"], cols["raised_on"]]
        values = {"pk": report_ref, "mark": mark, "finding": finding,
                  "severity": severity, "conf": confidence,
                  "evidence": evidence_json, "raised": datetime.now(timezone.utc)}
        binds = [":pk", ":mark", ":finding", ":severity", ":conf", ":evidence", ":raised"]
        if cols["source_sighting"]:
            names.append(cols["source_sighting"])
            binds.append(":read")
            values["read"] = triggering_read
        sql = text(f"INSERT INTO {self.table} ({', '.join(names)}) "
                   f"VALUES ({', '.join(binds)})")
        with self.engine.begin() as conn:
            conn.execute(sql, values)
        return True

    def _primary_key(self):
        from sqlalchemy import inspect
        pk = inspect(self.engine).get_pk_constraint(self.table)
        cols = pk.get("constrained_columns") or []
        return cols[0] if cols else "report_ref"


# ======================================================================

WRAPPER_CLASSES = {
    "rto": RTOWrapper,
    "insurance": InsuranceWrapper,
    "police": PoliceWrapper,
    "camera": CameraWrapper,
    "mot": MoTWrapper,
}


def create_wrappers(mapping, link_index, db_dir="."):
    from data_generator import DB_FILES

    filenames = {label: name for name, (_, label) in DB_FILES.items()}
    wrappers = {}
    for source, conf in mapping["sources"].items():
        cls = WRAPPER_CLASSES.get(source)
        if cls is None:
            continue
        path = os.path.join(db_dir, filenames.get(source, f"{source}.db"))
        wrappers[source] = cls(path, conf, link_index)
    return wrappers
