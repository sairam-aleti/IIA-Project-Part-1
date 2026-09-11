"""
Source Wrappers
===============
One wrapper per data source. Each wrapper:
  - Accepts the SCHEMA_MAPPING configuration (no hardcoded column names).
  - Executes local SQL queries using SQLAlchemy.
  - Normalizes output (timestamps → ISO-8601, booleans, etc.).
  - Tags every returned record with provenance metadata.
"""

import os
from datetime import date, datetime
from abc import ABC, abstractmethod

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


# ==========================================
# Base Wrapper
# ==========================================

class BaseWrapper(ABC):
    """Abstract base for all source wrappers."""

    def __init__(self, db_path: str, source_name: str, schema_mapping: dict):
        """
        Args:
            db_path:        Path to the SQLite database file.
            source_name:    Logical name of this source (e.g. "camera_db").
            schema_mapping: The full SCHEMA_MAPPING dict from schema_matcher.
        """
        self.db_path = db_path
        self.source_name = source_name
        self.mapping = schema_mapping.get(source_name, {})
        self.local_key = self.mapping.get("local_key")
        self.table = self.mapping.get("table")
        self.engine = create_engine(f"sqlite:///{db_path}")
        self.Session = sessionmaker(bind=self.engine)

    @abstractmethod
    def query(self, vehicle_identifier: str) -> dict | None:
        """Query the local source for a given vehicle identifier."""
        pass

    @abstractmethod
    def insert(self, data: dict) -> bool:
        """Insert a new record into this source. Returns True on success."""
        pass

    @abstractmethod
    def update(self, vehicle_identifier: str, data: dict) -> bool:
        """Update an existing record. Returns True on success."""
        pass

    def delete(self, vehicle_identifier: str) -> bool:
        """Delete a record by vehicle identifier. Shared implementation."""
        session = self.Session()
        try:
            key_col = self.local_key
            sql = text(f"DELETE FROM {self.table} WHERE {key_col} = :vid")
            result = session.execute(sql, {"vid": vehicle_identifier})
            session.commit()
            return result.rowcount > 0
        except Exception as e:
            session.rollback()
            print(f"[WRAPPER ERROR] Delete from {self.source_name} failed: {e}")
            return False
        finally:
            session.close()

    def _iso(self, value) -> str | None:
        """Normalize a date/datetime to ISO-8601 string."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, str):
            # Already a string — try to parse and re-format for consistency
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
                try:
                    return datetime.strptime(value, fmt).isoformat()
                except ValueError:
                    continue
            return value  # Return as-is if no format matches
        return str(value)

    def _provenance(self, field: str, local_column: str) -> dict:
        """Build a provenance trace for a single field."""
        return {
            "source": self.source_name,
            "table": self.table,
            "local_column": local_column,
            "retrieved_at": datetime.utcnow().isoformat() + "Z",
        }

    def close(self):
        """Dispose the engine."""
        self.engine.dispose()


# ==========================================
# Camera Wrapper
# ==========================================

class CameraWrapper(BaseWrapper):
    """
    Wraps camera.db / Capture table.
    Returns the most recent sighting (latest captured_at) for a plate.
    """

    def query(self, vehicle_identifier: str) -> dict | None:
        session = self.Session()
        try:
            # Dynamic column name from schema mapping
            key_col = self.local_key  # e.g. "plate_id"
            sql = text(
                f"SELECT * FROM {self.table} "
                f"WHERE {key_col} = :vid "
                f"ORDER BY captured_at DESC LIMIT 1"
            )
            result = session.execute(sql, {"vid": vehicle_identifier}).mappings().first()
            if result is None:
                return None

            row = dict(result)
            return {
                "vehicle_identifier": row[key_col],
                "last_seen_at": self._iso(row.get("captured_at")),
                "last_seen_location": row.get("camera_loc"),
                "ocr_confidence": row.get("ocr_confidence"),
                "provenance": {
                    "last_seen_at": self._provenance("last_seen_at", "captured_at"),
                    "last_seen_location": self._provenance("last_seen_location", "camera_loc"),
                    "ocr_confidence": self._provenance("ocr_confidence", "ocr_confidence"),
                },
            }
        finally:
            session.close()

    def insert(self, data: dict) -> bool:
        session = self.Session()
        try:
            sql = text(
                f"INSERT INTO {self.table} ({self.local_key}, camera_loc, captured_at, ocr_confidence) "
                f"VALUES (:vid, :loc, :ts, :conf)"
            )
            session.execute(sql, {
                "vid": data["plate"],
                "loc": data.get("camera_location", "Unknown"),
                "ts": datetime.utcnow().isoformat(),
                "conf": data.get("ocr_confidence", 0.95),
            })
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            print(f"[WRAPPER ERROR] Insert into {self.source_name} failed: {e}")
            return False
        finally:
            session.close()

    def update(self, vehicle_identifier: str, data: dict) -> bool:
        # Camera captures are append-only; update is a no-op
        return True


# ==========================================
# RTO Wrapper
# ==========================================

class RTOWrapper(BaseWrapper):
    """
    Wraps rto.db / Vehicle table.
    Returns owner and vehicle registration details.
    """

    def query(self, vehicle_identifier: str) -> dict | None:
        session = self.Session()
        try:
            key_col = self.local_key  # e.g. "reg_num"
            sql = text(
                f"SELECT * FROM {self.table} WHERE {key_col} = :vid"
            )
            result = session.execute(sql, {"vid": vehicle_identifier}).mappings().first()
            if result is None:
                return None

            row = dict(result)
            return {
                "vehicle_identifier": row[key_col],
                "owner": row.get("owner_name"),
                "vehicle_class": row.get("vehicle_class"),
                "registration_date": self._iso(row.get("registration_date")),
                "chassis_no": row.get("chassis_no"),
                "provenance": {
                    "owner": self._provenance("owner", "owner_name"),
                    "vehicle_class": self._provenance("vehicle_class", "vehicle_class"),
                    "registration_date": self._provenance("registration_date", "registration_date"),
                    "chassis_no": self._provenance("chassis_no", "chassis_no"),
                },
            }
        finally:
            session.close()

    def insert(self, data: dict) -> bool:
        session = self.Session()
        try:
            sql = text(
                f"INSERT INTO {self.table} ({self.local_key}, owner_name, vehicle_class, registration_date, chassis_no) "
                f"VALUES (:vid, :owner, :vclass, :regdate, :chassis)"
            )
            session.execute(sql, {
                "vid": data["plate"],
                "owner": data.get("owner_name", "Unknown"),
                "vclass": data.get("vehicle_class", "Sedan"),
                "regdate": data.get("registration_date", date.today().isoformat()),
                "chassis": data.get("chassis_no", f"CH{data['plate']}AUTO"),
            })
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            print(f"[WRAPPER ERROR] Insert into {self.source_name} failed: {e}")
            return False
        finally:
            session.close()

    def update(self, vehicle_identifier: str, data: dict) -> bool:
        session = self.Session()
        try:
            updates = []
            params = {"vid": vehicle_identifier}
            if "owner_name" in data:
                updates.append("owner_name = :owner")
                params["owner"] = data["owner_name"]
            if "vehicle_class" in data:
                updates.append("vehicle_class = :vclass")
                params["vclass"] = data["vehicle_class"]
            if "chassis_no" in data:
                updates.append("chassis_no = :chassis")
                params["chassis"] = data["chassis_no"]
            if not updates:
                return True
            sql = text(f"UPDATE {self.table} SET {', '.join(updates)} WHERE {self.local_key} = :vid")
            result = session.execute(sql, params)
            session.commit()
            return result.rowcount > 0
        except Exception as e:
            session.rollback()
            print(f"[WRAPPER ERROR] Update {self.source_name} failed: {e}")
            return False
        finally:
            session.close()


# ==========================================
# Insurance Wrapper
# ==========================================

class InsuranceWrapper(BaseWrapper):
    """
    Wraps insurance.db / Policy table.
    Returns insurance status with conflict resolution:
    even if status == 'Active', is_insured is False when expiry_date < today.
    """

    def query(self, vehicle_identifier: str) -> dict | None:
        session = self.Session()
        try:
            key_col = self.local_key  # e.g. "vehicle_reg_no"
            sql = text(
                f"SELECT * FROM {self.table} WHERE {key_col} = :vid"
            )
            result = session.execute(sql, {"vid": vehicle_identifier}).mappings().first()
            if result is None:
                return None

            row = dict(result)

            # Conflict resolution: derive is_insured from expiry_date
            expiry_raw = row.get("expiry_date")
            if expiry_raw:
                if isinstance(expiry_raw, str):
                    expiry = datetime.strptime(expiry_raw, "%Y-%m-%d").date()
                elif isinstance(expiry_raw, datetime):
                    expiry = expiry_raw.date()
                else:
                    expiry = expiry_raw
                is_insured = expiry >= date.today()
            else:
                is_insured = False

            return {
                "vehicle_identifier": row[key_col],
                "is_insured": is_insured,
                "policy_no": row.get("policy_no"),
                "insurer_name": row.get("insurer_name"),
                "policy_start": self._iso(row.get("start_date")),
                "policy_expiry": self._iso(row.get("expiry_date")),
                "policy_status_raw": row.get("status"),
                "provenance": {
                    "is_insured": {
                        **self._provenance("is_insured", "expiry_date"),
                        "derivation": "expiry_date >= today()",
                    },
                    "policy_no": self._provenance("policy_no", "policy_no"),
                    "insurer_name": self._provenance("insurer_name", "insurer_name"),
                    "policy_start": self._provenance("policy_start", "start_date"),
                    "policy_expiry": self._provenance("policy_expiry", "expiry_date"),
                },
            }
        finally:
            session.close()

    def insert(self, data: dict) -> bool:
        session = self.Session()
        try:
            sql = text(
                f"INSERT INTO {self.table} ({self.local_key}, policy_no, insurer_name, start_date, expiry_date, status) "
                f"VALUES (:vid, :pno, :ins, :sd, :ed, :st)"
            )
            session.execute(sql, {
                "vid": data["plate"],
                "pno": data.get("policy_no", f"POL-{data['plate']}"),
                "ins": data.get("insurer_name", "AutoGuard Ltd"),
                "sd": data.get("start_date", date.today().isoformat()),
                "ed": data.get("expiry_date", (date.today().replace(year=date.today().year + 1)).isoformat()),
                "st": data.get("insurance_status", "Active"),
            })
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            print(f"[WRAPPER ERROR] Insert into {self.source_name} failed: {e}")
            return False
        finally:
            session.close()

    def update(self, vehicle_identifier: str, data: dict) -> bool:
        session = self.Session()
        try:
            updates = []
            params = {"vid": vehicle_identifier}
            if "policy_no" in data:
                updates.append("policy_no = :pno")
                params["pno"] = data["policy_no"]
            if "insurer_name" in data:
                updates.append("insurer_name = :ins")
                params["ins"] = data["insurer_name"]
            if "start_date" in data:
                updates.append("start_date = :sd")
                params["sd"] = data["start_date"]
            if "expiry_date" in data:
                updates.append("expiry_date = :ed")
                params["ed"] = data["expiry_date"]
            if "insurance_status" in data:
                updates.append("status = :st")
                params["st"] = data["insurance_status"]
            if not updates:
                return True
            sql = text(f"UPDATE {self.table} SET {', '.join(updates)} WHERE {self.local_key} = :vid")
            result = session.execute(sql, params)
            session.commit()
            return result.rowcount > 0
        except Exception as e:
            session.rollback()
            print(f"[WRAPPER ERROR] Update {self.source_name} failed: {e}")
            return False
        finally:
            session.close()

# ==========================================
# Police Wrapper
# ==========================================

class PoliceWrapper(BaseWrapper):
    """
    Wraps police.db / StolenRecord table.
    Returns stolen/scrapped status.
    """

    def query(self, vehicle_identifier: str) -> dict | None:
        session = self.Session()
        try:
            key_col = self.local_key  # e.g. "license_tag"
            sql = text(
                f"SELECT * FROM {self.table} WHERE {key_col} = :vid"
            )
            result = session.execute(sql, {"vid": vehicle_identifier}).mappings().first()
            if result is None:
                return None

            row = dict(result)

            # Normalize booleans (SQLite stores as 0/1)
            is_stolen = bool(row.get("is_stolen"))
            is_scrapped = bool(row.get("is_scrapped"))

            return {
                "vehicle_identifier": row[key_col],
                "is_stolen": is_stolen,
                "fir_number": row.get("fir_number"),
                "is_scrapped": is_scrapped,
                "status_updated_at": self._iso(row.get("status_updated_at")),
                "provenance": {
                    "is_stolen": self._provenance("is_stolen", "is_stolen"),
                    "fir_number": self._provenance("fir_number", "fir_number"),
                    "is_scrapped": self._provenance("is_scrapped", "is_scrapped"),
                    "status_updated_at": self._provenance("status_updated_at", "status_updated_at"),
                },
            }
        finally:
            session.close()

    def insert(self, data: dict) -> bool:
        session = self.Session()
        try:
            sql = text(
                f"INSERT INTO {self.table} ({self.local_key}, is_stolen, fir_number, is_scrapped, status_updated_at) "
                f"VALUES (:vid, :stolen, :fir, :scrapped, :updated)"
            )
            session.execute(sql, {
                "vid": data["plate"],
                "stolen": 1 if data.get("is_stolen", False) else 0,
                "fir": data.get("fir_number"),
                "scrapped": 1 if data.get("is_scrapped", False) else 0,
                "updated": datetime.utcnow().isoformat(),
            })
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            print(f"[WRAPPER ERROR] Insert into {self.source_name} failed: {e}")
            return False
        finally:
            session.close()

    def update(self, vehicle_identifier: str, data: dict) -> bool:
        session = self.Session()
        try:
            updates = ["status_updated_at = :updated"]
            params = {"vid": vehicle_identifier, "updated": datetime.utcnow().isoformat()}
            if "is_stolen" in data:
                updates.append("is_stolen = :stolen")
                params["stolen"] = 1 if data["is_stolen"] else 0
            if "fir_number" in data:
                updates.append("fir_number = :fir")
                params["fir"] = data["fir_number"]
            if "is_scrapped" in data:
                updates.append("is_scrapped = :scrapped")
                params["scrapped"] = 1 if data["is_scrapped"] else 0
            sql = text(f"UPDATE {self.table} SET {', '.join(updates)} WHERE {self.local_key} = :vid")
            result = session.execute(sql, params)
            session.commit()
            return result.rowcount > 0
        except Exception as e:
            session.rollback()
            print(f"[WRAPPER ERROR] Update {self.source_name} failed: {e}")
            return False
        finally:
            session.close()

# ==========================================
# Wrapper Factory
# ==========================================

def create_wrappers(schema_mapping: dict, db_dir: str = ".") -> dict:
    """
    Instantiate all four wrappers from a schema mapping config.

    Args:
        schema_mapping: The SCHEMA_MAPPING dict from schema_matcher.
        db_dir:         Directory containing the .db files.

    Returns:
        Dict of {source_name: wrapper_instance}
    """
    db_paths = {
        "camera_db":    os.path.join(db_dir, "camera.db"),
        "rto_db":       os.path.join(db_dir, "rto.db"),
        "insurance_db": os.path.join(db_dir, "insurance.db"),
        "police_db":    os.path.join(db_dir, "police.db"),
    }

    wrapper_classes = {
        "camera_db":    CameraWrapper,
        "rto_db":       RTOWrapper,
        "insurance_db": InsuranceWrapper,
        "police_db":    PoliceWrapper,
    }

    wrappers = {}
    for source_name, WrapperCls in wrapper_classes.items():
        path = db_paths[source_name]
        wrappers[source_name] = WrapperCls(
            db_path=path,
            source_name=source_name,
            schema_mapping=schema_mapping,
        )

    return wrappers


if __name__ == "__main__":
    # Quick test: generate mapping, create wrappers, query a plate
    from schema_matcher import generate_mapping
    import json

    mapping = generate_mapping()
    wrappers = create_wrappers(mapping)

    # Read one plate from rto.db for testing
    from sqlalchemy import create_engine, text as sql_text
    engine = create_engine("sqlite:///rto.db")
    with engine.connect() as conn:
        row = conn.execute(sql_text("SELECT reg_num FROM Vehicle LIMIT 1")).first()
        if row:
            test_plate = row[0]
            print(f"\nTesting wrappers with plate: {test_plate}\n")
            for name, wrapper in wrappers.items():
                result = wrapper.query(test_plate)
                print(f"--- {name} ---")
                print(json.dumps(result, indent=2, default=str))
                print()
    engine.dispose()
