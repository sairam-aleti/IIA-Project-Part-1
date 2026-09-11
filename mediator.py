"""
GAV Mediator Engine
===================
Implements the Global-As-View federated query engine.

Global Schema:
    MoT_Report(
        vehicle_identifier,   # Unified key
        owner,                # From RTO
        vehicle_class,        # From RTO
        is_insured,           # Derived from Insurance (expiry_date >= today)
        insurance_details,    # From Insurance
        is_stolen,            # From Police
        is_scrapped,          # From Police
        fir_number,           # From Police (if stolen)
        last_seen,            # Latest camera capture
        provenance            # Full trace of every field to its source
    )

Query Unfolding:
    1. Dispatch sub-queries to all 4 wrappers.
    2. Join results in-memory by vehicle_identifier.
    3. Resolve conflicts (e.g., insurance expiry check).
    4. Build provenance trace.
    5. Return unified MoT_Report.
"""

from datetime import datetime
from wrappers import create_wrappers


class GAVMediator:
    """
    The Global-As-View mediator that unfolds global queries into
    local sub-queries across all source wrappers and merges the results.
    """

    def __init__(self, schema_mapping: dict, db_dir: str = "."):
        """
        Args:
            schema_mapping: The SCHEMA_MAPPING from schema_matcher.
            db_dir:         Directory containing the .db files.
        """
        self.schema_mapping = schema_mapping
        self.wrappers = create_wrappers(schema_mapping, db_dir)

    def query_vehicle(self, plate: str) -> dict | None:
        """
        Execute a federated GAV query for a single vehicle.

        This is the core view-unfolding operation:
        1. Dispatch to all 4 wrappers.
        2. Merge results.
        3. Resolve conflicts.
        4. Build provenance.

        Args:
            plate: The vehicle identifier (license plate).

        Returns:
            A unified MoT_Report dict, or None if the vehicle is unknown.
        """
        # ── Step 1: Dispatch sub-queries to all wrappers ──
        results = {}
        for source_name, wrapper in self.wrappers.items():
            try:
                result = wrapper.query(plate)
                results[source_name] = result
            except Exception as e:
                results[source_name] = None
                print(f"[MEDIATOR WARNING] Query to {source_name} failed: {e}")

        # Check if we got data from at least one source
        if all(v is None for v in results.values()):
            return None

        # ── Step 2 & 3: Merge results + conflict resolution ──
        rto_data = results.get("rto_db")
        insurance_data = results.get("insurance_db")
        police_data = results.get("police_db")
        camera_data = results.get("camera_db")

        # Provenance accumulator
        provenance = {}

        # Owner (from RTO)
        owner = None
        vehicle_class = None
        registration_date = None
        chassis_no = None
        if rto_data:
            owner = rto_data.get("owner")
            vehicle_class = rto_data.get("vehicle_class")
            registration_date = rto_data.get("registration_date")
            chassis_no = rto_data.get("chassis_no")
            provenance.update({
                "owner": rto_data["provenance"]["owner"],
                "vehicle_class": rto_data["provenance"]["vehicle_class"],
                "registration_date": rto_data["provenance"]["registration_date"],
                "chassis_no": rto_data["provenance"]["chassis_no"],
            })

        # Insurance (with conflict resolution)
        is_insured = None
        insurance_details = None
        if insurance_data:
            is_insured = insurance_data.get("is_insured")
            insurance_details = {
                "policy_no": insurance_data.get("policy_no"),
                "insurer": insurance_data.get("insurer_name"),
                "start_date": insurance_data.get("policy_start"),
                "expiry_date": insurance_data.get("policy_expiry"),
                "raw_status": insurance_data.get("policy_status_raw"),
            }
            provenance["is_insured"] = insurance_data["provenance"]["is_insured"]
            provenance["insurance_details"] = {
                "policy_no": insurance_data["provenance"]["policy_no"],
                "insurer": insurance_data["provenance"]["insurer_name"],
                "start_date": insurance_data["provenance"]["policy_start"],
                "expiry_date": insurance_data["provenance"]["policy_expiry"],
            }

        # Police (stolen / scrapped)
        is_stolen = None
        is_scrapped = None
        fir_number = None
        police_status_updated = None
        if police_data:
            is_stolen = police_data.get("is_stolen")
            is_scrapped = police_data.get("is_scrapped")
            fir_number = police_data.get("fir_number")
            police_status_updated = police_data.get("status_updated_at")
            provenance.update({
                "is_stolen": police_data["provenance"]["is_stolen"],
                "is_scrapped": police_data["provenance"]["is_scrapped"],
                "fir_number": police_data["provenance"]["fir_number"],
            })

        # Camera (last seen)
        last_seen_at = None
        last_seen_location = None
        ocr_confidence = None
        if camera_data:
            last_seen_at = camera_data.get("last_seen_at")
            last_seen_location = camera_data.get("last_seen_location")
            ocr_confidence = camera_data.get("ocr_confidence")
            provenance.update({
                "last_seen_at": camera_data["provenance"]["last_seen_at"],
                "last_seen_location": camera_data["provenance"]["last_seen_location"],
            })

        # ── Step 4: Build the unified MoT_Report ──
        mot_report = {
            "vehicle_identifier": plate,
            "owner": owner,
            "vehicle_class": vehicle_class,
            "registration_date": registration_date,
            "chassis_no": chassis_no,
            "is_insured": is_insured,
            "insurance_details": insurance_details,
            "is_stolen": is_stolen,
            "is_scrapped": is_scrapped,
            "fir_number": fir_number,
            "last_seen": {
                "timestamp": last_seen_at,
                "location": last_seen_location,
                "ocr_confidence": ocr_confidence,
            } if camera_data else None,
            "flags": self._compute_flags(is_insured, is_stolen, is_scrapped),
            "provenance": provenance,
            "query_timestamp": datetime.utcnow().isoformat() + "Z",
        }

        return mot_report

    def _compute_flags(self, is_insured, is_stolen, is_scrapped) -> list:
        """Compute alert flags for quick filtering."""
        flags = []
        if is_insured is False:
            flags.append("UNINSURED")
        if is_stolen is True:
            flags.append("STOLEN")
        if is_scrapped is True:
            flags.append("SCRAPPED")
        return flags

    def query_all_vehicles(self) -> list:
        """
        Scan all vehicles and return a lightweight summary for each.
        Suitable for the 1000-record demo dataset.
        """
        from sqlalchemy import create_engine, text

        # Get all plates from RTO (the most complete registry)
        rto_wrapper = self.wrappers.get("rto_db")
        if not rto_wrapper:
            return []

        engine = create_engine(f"sqlite:///{rto_wrapper.db_path}")
        with engine.connect() as conn:
            key_col = rto_wrapper.local_key
            rows = conn.execute(
                text(f"SELECT {key_col} FROM {rto_wrapper.table}")
            ).fetchall()
        engine.dispose()

        vehicles = []
        for row in rows:
            plate = row[0]
            report = self.query_vehicle(plate)
            if report:
                vehicles.append({
                    "vehicle_identifier": plate,
                    "owner": report.get("owner"),
                    "flags": report["flags"],
                    "is_insured": report.get("is_insured"),
                    "is_stolen": report.get("is_stolen"),
                    "is_scrapped": report.get("is_scrapped"),
                })

        return vehicles

    def query_all_flagged(self) -> list:
        """
        Scan all vehicles and return those with any flags
        (uninsured, stolen, or scrapped).
        """
        all_vehicles = self.query_all_vehicles()
        return [v for v in all_vehicles if v.get("flags")]

    def insert_vehicle(self, data: dict) -> dict:
        """
        Insert a new vehicle across all 4 source databases.

        Args:
            data: Dict containing all vehicle fields.

        Returns:
            Dict with per-source success status.
        """
        results = {}
        for source_name, wrapper in self.wrappers.items():
            try:
                results[source_name] = wrapper.insert(data)
            except Exception as e:
                results[source_name] = False
                print(f"[MEDIATOR ERROR] Insert to {source_name} failed: {e}")
        return results

    def update_vehicle(self, plate: str, data: dict) -> dict:
        """
        Update vehicle fields across the relevant source databases.

        Args:
            plate: The vehicle identifier.
            data:  Dict of fields to update.

        Returns:
            Dict with per-source success status.
        """
        results = {}
        for source_name, wrapper in self.wrappers.items():
            try:
                results[source_name] = wrapper.update(plate, data)
            except Exception as e:
                results[source_name] = False
                print(f"[MEDIATOR ERROR] Update to {source_name} failed: {e}")
        return results

    def delete_vehicle(self, plate: str) -> dict:
        """
        Delete a vehicle from all 4 source databases.

        Args:
            plate: The vehicle identifier to delete.

        Returns:
            Dict with per-source success status.
        """
        results = {}
        for source_name, wrapper in self.wrappers.items():
            try:
                results[source_name] = wrapper.delete(plate)
            except Exception as e:
                results[source_name] = False
                print(f"[MEDIATOR ERROR] Delete from {source_name} failed: {e}")
        return results

    def close(self):
        """Clean up all wrapper connections."""
        for wrapper in self.wrappers.values():
            wrapper.close()
