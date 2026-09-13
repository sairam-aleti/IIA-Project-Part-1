"""
GAV mediator
============
Unfolds one global query into local sub-queries across five autonomous
sources, merges the answers, and reaches a *defensible* conclusion.

Global schema (virtual — nothing is materialised):

    VehicleView(
        canonical_mark,
        identity          -- how the plate was resolved, and how confidently
        registration      -- from rto, or absent
        insurance_at      -- evaluated against a specific instant, not today
        enforcement       -- theft and scrap status
        sightings         -- roadside observations
        prior_findings    -- what has already been reported to the Ministry
        contradictions    -- facts from different sources that cannot both hold
        assessment        -- outcome, confidence, and the reasons for it
        provenance        -- every fact traced to source, table and column
    )

Four outcomes, not three:

    COMPLIANT              insured at the time observed, nothing adverse
    UNINSURED              no cover in force at the time observed
    SUSPICIOUS             stolen, scrapped, unregistered, or self-contradictory
    INSUFFICIENT_EVIDENCE  the system declines to conclude

The fourth is the point. A report to the Ministry is an accusation against a
citizen, so the mediator must be able to say "I cannot tell" — when the plate
does not resolve to a known vehicle, when the vehicle has never been observed
so there is no moment to assess, or when a source that would settle the
question is unreachable. Part A reaches that state through missing and
malformed data; Part B will reach it through probability.

Conflict rules are declared, not improvised, and every applied rule is recorded
in the assessment so a reviewer can see why the system believed what it did.
"""

import json
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import create_engine, text

import plate as plate_util
from link_index import LinkIndex
from wrappers import create_wrappers

# ======================================================================
# Declared conflict-resolution rules
# ======================================================================

RULES = {
    "date_over_label": (
        "When a policy's recorded status label disagrees with its cover dates, "
        "the dates govern. A row labelled Active whose cover period has ended "
        "does not provide cover."
    ),
    "absence_is_evidence": (
        "A reachable insurance source holding no policy for a vehicle is "
        "evidence the vehicle was never insured, not missing data."
    ),
    "unreachable_is_not_evidence": (
        "An unreachable source yields no evidence either way, and forces "
        "INSUFFICIENT_EVIDENCE rather than a default assumption."
    ),
    "assess_at_sighting": (
        "Insurance is evaluated at the moment the vehicle was observed on the "
        "road, not at the moment the query was run."
    ),
    "contradiction_needs_adjudication": (
        "Two sources asserting mutually impossible facts are both reported. "
        "The mediator does not silently pick a winner."
    ),
    "identity_before_assessment": (
        "No compliance conclusion is reached for a plate that does not resolve "
        "to a known vehicle."
    ),
}

OUTCOME_COMPLIANT = "COMPLIANT"
OUTCOME_UNINSURED = "UNINSURED"
OUTCOME_SUSPICIOUS = "SUSPICIOUS"
OUTCOME_ABSTAIN = "INSUFFICIENT_EVIDENCE"

SEVERITY = {
    OUTCOME_COMPLIANT: "NONE",
    OUTCOME_UNINSURED: "MEDIUM",
    OUTCOME_SUSPICIOUS: "HIGH",
    OUTCOME_ABSTAIN: "REVIEW",
}


def _as_date(value):
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text_value = str(value)
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(text_value[:26], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text_value.replace("Z", "")).date()
    except ValueError:
        return None


def _value(fact):
    return fact.get("value") if fact else None


class GAVMediator:

    def __init__(self, mapping, db_dir="."):
        self.mapping = mapping
        self.db_dir = db_dir
        self.link_index = LinkIndex(mapping, db_dir)
        self.wrappers = create_wrappers(mapping, self.link_index, db_dir)

    # ==================================================================
    # Identity
    # ==================================================================

    def resolve_identity(self, query_plate):
        resolution = self.link_index.resolve(query_plate)
        resolution["links"] = self.link_index.link_records(resolution["canonical_mark"])
        resolution["rule"] = "identity_before_assessment"
        return resolution

    # ==================================================================
    # Insurance, evaluated at an instant
    # ==================================================================

    def evaluate_insurance(self, insurance_result, at):
        """
        Decide whether cover was in force at `at`.

        Returns state in {covered, lapsed, never_recorded, unknown} together
        with the policy that provided cover (if any) and the rules applied.
        """
        applied = ["assess_at_sighting"]
        status = insurance_result.get("status")

        if status in ("error", "unavailable"):
            return {"state": "unknown", "assessed_at": at.isoformat() if at else None,
                    "covering_policy": None, "periods": [],
                    "rules_applied": applied + ["unreachable_is_not_evidence"],
                    "note": insurance_result.get("note")}

        if status == "absent":
            return {"state": "never_recorded",
                    "assessed_at": at.isoformat() if at else None,
                    "covering_policy": None, "periods": [],
                    "rules_applied": applied + ["absence_is_evidence"]}

        periods = insurance_result.get("cover_periods", [])
        summary, covering = [], None
        label_conflicts = 0

        for period in periods:
            begins = _as_date(_value(period.get("cover_begins")))
            ends = _as_date(_value(period.get("cover_ends")))
            label = _value(period.get("declared_policy_state"))
            in_force = bool(at and begins and ends and begins <= at <= ends)
            label_says_active = str(label).strip().lower() == "active"
            conflict = label_says_active and ends is not None and ends < at if at else False
            if conflict:
                label_conflicts += 1
            entry = {
                "policy_id": _value(period.get("policy_id")),
                "insurer": _value(period.get("insurer")),
                "cover_begins": begins.isoformat() if begins else None,
                "cover_ends": ends.isoformat() if ends else None,
                "declared_state": label,
                "cover_type": _value(period.get("cover_type")),
                "in_force_at_assessment": in_force,
                "label_contradicts_dates": conflict,
            }
            summary.append(entry)
            if in_force and covering is None:
                covering = entry

        if label_conflicts:
            applied.append("date_over_label")

        return {
            "state": "covered" if covering else "lapsed",
            "assessed_at": at.isoformat() if at else None,
            "covering_policy": covering,
            "periods": summary,
            "policy_count": len(summary),
            "stale_labels": label_conflicts,
            "rules_applied": applied,
        }

    # ==================================================================
    # Contradictions
    # ==================================================================

    def detect_contradictions(self, registration, police, sightings, insurance_eval):
        """
        Facts that cannot all be true. Each is reported with the sources whose
        claims collide, so a reviewer can adjudicate rather than trust a guess.
        """
        found = []
        latest = None
        if sightings:
            latest = _as_date(_value(sightings[0].get("sighting_time")))

        scrapped = _value(police.get("facts", {}).get("scrap_flag"))
        stolen = _value(police.get("facts", {}).get("theft_flag"))
        recovered = _as_date(_value(police.get("facts", {}).get("recovered_on")))
        amended = _as_date(_value(police.get("facts", {}).get("record_amended_on")))

        if scrapped and latest:
            found.append({
                "kind": "scrapped_but_observed",
                "sources": ["police", "camera"],
                "detail": f"Police hold a certificate of destruction, yet the "
                          f"vehicle was observed on {latest.isoformat()}.",
                "implication": "Either the scrap record is wrong or the plate is cloned.",
            })

        if stolen and recovered:
            found.append({
                "kind": "stolen_flag_not_cleared",
                "sources": ["police"],
                "detail": f"The theft flag is still set although the vehicle was "
                          f"recovered on {recovered.isoformat()}.",
                "implication": "The police record is internally stale.",
            })

        if stolen and not recovered and latest and amended and latest > amended:
            found.append({
                "kind": "stolen_and_still_driving",
                "sources": ["police", "camera"],
                "detail": f"Reported stolen, and observed on "
                          f"{latest.isoformat()} after the record was last amended.",
                "implication": "Active theft, or a cloned plate.",
            })

        if insurance_eval.get("stale_labels"):
            found.append({
                "kind": "policy_label_contradicts_dates",
                "sources": ["insurance"],
                "detail": f"{insurance_eval['stale_labels']} policy row(s) are "
                          f"labelled Active with a cover period that has ended.",
                "implication": "Resolved by rule date_over_label.",
                "resolved_by_rule": "date_over_label",
            })

        registered_on = _as_date(_value(registration.get("facts", {}).get("registered_on")))
        if registered_on and latest and latest < registered_on:
            found.append({
                "kind": "observed_before_registration",
                "sources": ["rto", "camera"],
                "detail": f"Observed on {latest.isoformat()}, before the "
                          f"registration date of {registered_on.isoformat()}.",
                "implication": "Plate reuse, a backdated register entry, or a bad read.",
            })

        if registration.get("status") == "absent" and \
                insurance_eval.get("state") in ("covered", "lapsed"):
            found.append({
                "kind": "insured_but_unregistered",
                "sources": ["rto", "insurance"],
                "detail": "An insurer holds a policy for a plate the RTO has no "
                          "record of.",
                "implication": "Unregistered vehicle, or divergent plate records.",
            })

        return found

    # ==================================================================
    # The global query
    # ==================================================================

    def query_vehicle(self, query_plate, as_of=None):
        """
        Unfold a global query for one plate.

        Args:
            query_plate: plate as typed, in any format
            as_of:       ISO date to assess against. Defaults to the most
                         recent sighting, which is the question the use case
                         actually asks.
        """
        identity = self.resolve_identity(query_plate)
        mark = identity["canonical_mark"]

        if mark is None:
            return self._abstain_envelope(
                query_plate, identity,
                ["The supplied value contains no plate characters."])

        results = {}
        for source, wrapper in self.wrappers.items():
            results[source] = wrapper.query(mark)

        registration = results.get("rto", {"status": "unavailable", "facts": {}})
        insurance = results.get("insurance", {"status": "unavailable"})
        police = results.get("police", {"status": "absent", "facts": {}})
        camera = results.get("camera", {"status": "absent"})
        mot = results.get("mot", {"status": "absent"})

        sightings = camera.get("sightings", []) or []

        # ---- which instant are we assessing? ----
        if as_of:
            assess_at = _as_date(as_of)
            basis = "caller supplied as_of"
        elif sightings:
            assess_at = _as_date(_value(sightings[0].get("sighting_time")))
            basis = "most recent roadside sighting"
        else:
            assess_at = None
            basis = "no sighting on record"

        insurance_eval = self.evaluate_insurance(insurance, assess_at)
        contradictions = self.detect_contradictions(
            registration, police, sightings, insurance_eval)

        assessment = self._assess(identity, registration, insurance_eval,
                                  police, sightings, contradictions,
                                  assess_at, basis)

        return self._envelope(query_plate, identity, registration, insurance,
                              insurance_eval, police, camera, mot, sightings,
                              contradictions, assessment, results)

    # ------------------------------------------------------------------
    def _assess(self, identity, registration, insurance_eval, police,
                sightings, contradictions, assess_at, basis):
        """
        Reach an outcome, or decline to. Reasons are recorded either way.
        """
        reasons, abstain_reasons, rules = [], [], ["identity_before_assessment"]

        # -- identity gate --
        if not identity["known"]:
            if identity["sources_holding"]:
                abstain_reasons.append(
                    "This plate was read by the cameras but appears in no "
                    "register, so it cannot be tied to a known vehicle. It is "
                    "either an unregistered vehicle or a misread plate, and "
                    "Part A cannot distinguish the two.")
            else:
                abstain_reasons.append(
                    "No source holds any record of this plate.")
            if not identity["wellformed"]:
                abstain_reasons.append(
                    "The mark does not match the national plate grammar, which "
                    "is consistent with a character-level misread.")
            return self._abstain(abstain_reasons, rules, assess_at, basis)

        # -- an unreachable insurer means we cannot conclude --
        if insurance_eval["state"] == "unknown":
            rules.append("unreachable_is_not_evidence")
            abstain_reasons.append(
                "The insurance source could not be consulted, so insured "
                "status is unknown. No default is assumed.")
            return self._abstain(abstain_reasons, rules, assess_at, basis)

        # -- no sighting means no moment to assess --
        if assess_at is None:
            abstain_reasons.append(
                "The vehicle has never been observed on the road, so there is "
                "no moment at which to assess compliance.")
            return self._abstain(abstain_reasons, rules, assess_at, basis)

        findings = []
        rules.extend(insurance_eval.get("rules_applied", []))

        # -- insurance --
        if insurance_eval["state"] == "never_recorded":
            findings.append("UNINSURED")
            reasons.append(
                "No insurer holds any policy for this vehicle. It appears never "
                "to have been insured.")
        elif insurance_eval["state"] == "lapsed":
            findings.append("UNINSURED")
            latest_end = max((p["cover_ends"] or "" for p in insurance_eval["periods"]),
                             default="")
            reasons.append(
                f"{insurance_eval['policy_count']} policy period(s) on record, "
                f"none covering {assess_at.isoformat()}"
                + (f"; the most recent cover ended {latest_end}." if latest_end else "."))
        else:
            policy = insurance_eval["covering_policy"]
            reasons.append(
                f"Cover was in force at {assess_at.isoformat()} under policy "
                f"{policy['policy_id']} ({policy['insurer']}), valid "
                f"{policy['cover_begins']} to {policy['cover_ends']}.")

        # -- enforcement --
        facts = police.get("facts", {})
        if _value(facts.get("theft_flag")):
            findings.append("STOLEN")
            case = _value(facts.get("theft_case"))
            reasons.append(f"Reported stolen under case {case}." if case
                           else "Reported stolen.")
        if _value(facts.get("scrap_flag")):
            findings.append("SCRAPPED")
            cert = _value(facts.get("scrap_certificate"))
            reasons.append(f"A certificate of destruction was issued ({cert})."
                           if cert else "Recorded as scrapped.")

        # -- registration --
        if registration.get("status") == "absent":
            findings.append("UNREGISTERED")
            reasons.append("The RTO register holds no entry for this plate.")

        # -- contradictions --
        unresolved = [c for c in contradictions if "resolved_by_rule" not in c]
        if unresolved:
            rules.append("contradiction_needs_adjudication")
            for contradiction in unresolved:
                reasons.append(contradiction["detail"])

        # -- outcome --
        if {"STOLEN", "SCRAPPED", "UNREGISTERED"} & set(findings) or unresolved:
            outcome = OUTCOME_SUSPICIOUS
        elif "UNINSURED" in findings:
            outcome = OUTCOME_UNINSURED
        else:
            outcome = OUTCOME_COMPLIANT

        # Part A is deterministic: an outcome reached from present, consistent
        # records is reached with certainty. Confidence is a field, not a
        # flourish — Part B replaces the constant with a computed value.
        return {
            "outcome": outcome,
            "severity": SEVERITY[outcome],
            "confidence": 1.0,
            "confidence_basis": "deterministic: exact canonical linkage over "
                                "complete records",
            "findings": findings,
            "reasons": reasons,
            "requires_adjudication": bool(unresolved),
            "assessed_at": assess_at.isoformat() if assess_at else None,
            "assessment_basis": basis,
            "rules_applied": sorted(set(rules)),
            "reportable": outcome in (OUTCOME_UNINSURED, OUTCOME_SUSPICIOUS),
        }

    @staticmethod
    def _abstain(reasons, rules, assess_at, basis):
        return {
            "outcome": OUTCOME_ABSTAIN,
            "severity": SEVERITY[OUTCOME_ABSTAIN],
            "confidence": None,
            "confidence_basis": "the system declines to assign a confidence to "
                                "a conclusion it cannot reach",
            "findings": [],
            "reasons": reasons,
            "requires_adjudication": True,
            "assessed_at": assess_at.isoformat() if assess_at else None,
            "assessment_basis": basis,
            "rules_applied": sorted(set(rules)),
            "reportable": True,
        }

    # ------------------------------------------------------------------
    def _abstain_envelope(self, query_plate, identity, reasons):
        return {
            "query": query_plate,
            "canonical_mark": None,
            "identity": identity,
            "registration": {"status": "not_queried"},
            "insurance_at": {"state": "unknown"},
            "enforcement": {"status": "not_queried"},
            "sightings": [],
            "prior_findings": [],
            "contradictions": [],
            "assessment": self._abstain(reasons, ["identity_before_assessment"],
                                        None, "identity unresolved"),
            "provenance": {},
            "source_status": {},
            "queried_at": datetime.now(timezone.utc).isoformat(),
            # backward-compatible view
            "vehicle_identifier": query_plate,
            "flags": ["INSUFFICIENT_EVIDENCE"],
            "is_insured": None, "is_stolen": None, "is_scrapped": None,
            "owner": None, "vehicle_class": None, "registration_date": None,
            "chassis_no": None, "insurance_details": None, "last_seen": None,
        }

    def _envelope(self, query_plate, identity, registration, insurance,
                  insurance_eval, police, camera, mot, sightings,
                  contradictions, assessment, results):
        """Assemble the global view and flatten provenance for audit."""
        provenance = {}
        for source, result in results.items():
            for attribute, fact in (result.get("facts") or {}).items():
                provenance[attribute] = fact
        provenance["identity"] = {
            "source": "mediator",
            "derivation": "canonical(plate) matched against the linkage index",
            "method": identity["method"],
            "confidence": identity["score"],
            "links": identity["links"],
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
        if insurance_eval.get("periods"):
            provenance["insurance_at"] = {
                "source": "insurance",
                "table": insurance.get("source"),
                "derivation": "cover_begins <= assessed_at <= cover_ends over "
                              "the full policy history",
                "confidence": 1.0,
                "assessed_at": insurance_eval.get("assessed_at"),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            }

        police_facts = police.get("facts", {})
        latest = sightings[0] if sightings else None
        covering = insurance_eval.get("covering_policy")

        return {
            "query": query_plate,
            "canonical_mark": identity["canonical_mark"],
            "identity": identity,
            "registration": {
                "status": registration.get("status"),
                "owner": _value(registration.get("facts", {}).get("owner")),
                "vehicle_category": _value(registration.get("facts", {}).get("vehicle_category")),
                "registered_on": _value(registration.get("facts", {}).get("registered_on")),
                "chassis": _value(registration.get("facts", {}).get("chassis")),
                "propulsion": _value(registration.get("facts", {}).get("propulsion")),
            },
            "insurance_at": insurance_eval,
            "enforcement": {
                "status": police.get("status"),
                "reported_stolen": _value(police_facts.get("theft_flag")),
                "theft_case": _value(police_facts.get("theft_case")),
                "recovered_on": _value(police_facts.get("recovered_on")),
                "scrapped": _value(police_facts.get("scrap_flag")),
                "scrap_certificate": _value(police_facts.get("scrap_certificate")),
                "record_amended_on": _value(police_facts.get("record_amended_on")),
            },
            "sightings": [
                {
                    "sighting_id": _value(s.get("sighting_id")),
                    "at": _value(s.get("sighting_time")),
                    "place": _value(s.get("sighting_place")),
                    "read_quality": _value(s.get("read_quality")),
                }
                for s in sightings
            ],
            "prior_findings": [
                {
                    "finding": _value(f.get("finding")),
                    "severity": _value(f.get("severity")),
                    "confidence": _value(f.get("finding_confidence")),
                    "raised_on": _value(f.get("raised_on")),
                }
                for f in (mot.get("prior_findings") or [])
            ],
            "contradictions": contradictions,
            "assessment": assessment,
            "provenance": provenance,
            "source_status": {s: r.get("status") for s, r in results.items()},
            "queried_at": datetime.now(timezone.utc).isoformat(),

            # ---- backward-compatible projection for the existing UI ----
            "vehicle_identifier": identity["canonical_mark"],
            "owner": _value(registration.get("facts", {}).get("owner")),
            "vehicle_class": _value(registration.get("facts", {}).get("vehicle_category")),
            "registration_date": _value(registration.get("facts", {}).get("registered_on")),
            "chassis_no": _value(registration.get("facts", {}).get("chassis")),
            "is_insured": (None if insurance_eval["state"] == "unknown"
                           else insurance_eval["state"] == "covered"),
            "is_stolen": _value(police_facts.get("theft_flag")),
            "is_scrapped": _value(police_facts.get("scrap_flag")),
            "fir_number": _value(police_facts.get("theft_case")),
            "insurance_details": {
                "policy_no": covering["policy_id"] if covering else None,
                "insurer": covering["insurer"] if covering else None,
                "start_date": covering["cover_begins"] if covering else None,
                "expiry_date": covering["cover_ends"] if covering else None,
                "raw_status": covering["declared_state"] if covering else None,
                "policy_count": insurance_eval.get("policy_count", 0),
            } if insurance_eval.get("periods") else None,
            "last_seen": {
                "timestamp": _value(latest.get("sighting_time")),
                "location": _value(latest.get("sighting_place")),
                "ocr_confidence": _value(latest.get("read_quality")),
            } if latest else None,
            "flags": assessment["findings"] or ([assessment["outcome"]]
                                                if assessment["outcome"] != OUTCOME_COMPLIANT
                                                else []),
        }

    # ==================================================================
    # Batch assessment
    # ==================================================================

    def assess_all(self, limit=None, offset=0, outcome=None):
        """
        Assess every known vehicle. Returns compact rows for listing.

        Pagination is applied before the federated calls, so asking for one
        page costs one page of work rather than a full scan.
        """
        marks = self.link_index.all_known()
        total = len(marks)
        window = marks[offset: offset + limit] if limit else marks[offset:]

        rows = []
        for mark in window:
            view = self.query_vehicle(mark)
            assessment = view["assessment"]
            rows.append({
                "canonical_mark": mark,
                "owner": view["registration"]["owner"],
                "outcome": assessment["outcome"],
                "severity": assessment["severity"],
                "confidence": assessment["confidence"],
                "findings": assessment["findings"],
                "requires_adjudication": assessment["requires_adjudication"],
                "assessed_at": assessment["assessed_at"],
                "contradiction_count": len(view["contradictions"]),
                # legacy fields
                "vehicle_identifier": mark,
                "flags": view["flags"],
                "is_insured": view["is_insured"],
                "is_stolen": view["is_stolen"],
                "is_scrapped": view["is_scrapped"],
            })

        if outcome:
            rows = [r for r in rows if r["outcome"] == outcome]
        return {"total_known": total, "returned": len(rows), "offset": offset,
                "vehicles": rows}

    def unresolved_reads(self):
        """
        Camera reads that resolve to no known vehicle.

        These are the clearest instance of the system's own limit: a vehicle
        was definitely on the road, and the mediator cannot say which one.
        """
        out = []
        for mark in self.link_index.orphans():
            reads = self.link_index.links[mark].get("camera", [])
            camera = self.wrappers.get("camera")
            detail = camera.query(mark) if camera else {}
            sightings = detail.get("sightings", []) or []
            out.append({
                "canonical_mark": mark,
                "wellformed": plate_util.is_wellformed(mark),
                "confusable_key": plate_util.confusable_key(mark),
                "read_count": len(reads),
                "outcome": OUTCOME_ABSTAIN,
                "reason": ("Read by a camera but present in no register. Either "
                           "an unregistered vehicle or a misread plate; Part A "
                           "cannot distinguish these."),
                "sightings": [
                    {"at": _value(s.get("sighting_time")),
                     "place": _value(s.get("sighting_place")),
                     "read_quality": _value(s.get("read_quality"))}
                    for s in sightings[:3]
                ],
            })
        out.sort(key=lambda r: -r["read_count"])
        return out

    # ==================================================================
    # Reporting to the Ministry
    # ==================================================================

    def _next_report_ref(self):
        wrapper = self.wrappers.get("mot")
        if not wrapper or not wrapper.available:
            return f"MOT-{date.today().year}-{uuid.uuid4().hex[:8]}"
        pk = wrapper._primary_key()
        engine = create_engine(f"sqlite:///{wrapper.db_path}")
        with engine.connect() as conn:
            row = conn.execute(
                text(f"SELECT COUNT(*) FROM {wrapper.table}")).first()
        engine.dispose()
        return f"MOT-{date.today().year}-{(row[0] if row else 0) + 1:05d}"

    def file_report(self, view):
        """
        Persist one finding to mot.db.

        Both adverse outcomes and abstentions are filed. An abstention is a
        record that the system looked and could not tell, which is exactly what
        a reviewing officer needs to see.
        """
        wrapper = self.wrappers.get("mot")
        assessment = view["assessment"]
        if not wrapper or not wrapper.available:
            return {"filed": False, "reason": "reporting source unavailable"}
        if not assessment.get("reportable"):
            return {"filed": False, "reason": "outcome is compliant"}

        latest = view["sightings"][0] if view["sightings"] else None
        evidence = {
            "outcome": assessment["outcome"],
            "findings": assessment["findings"],
            "reasons": assessment["reasons"],
            "rules_applied": assessment["rules_applied"],
            "assessed_at": assessment["assessed_at"],
            "assessment_basis": assessment["assessment_basis"],
            "requires_adjudication": assessment["requires_adjudication"],
            "contradictions": [c["kind"] for c in view["contradictions"]],
            "identity": {
                "canonical_mark": view["canonical_mark"],
                "method": view["identity"]["method"],
                "score": view["identity"]["score"],
                "raw_values": [l["raw_value"] for l in view["identity"]["links"]],
            },
            "source_status": view["source_status"],
        }
        ref = self._next_report_ref()
        ok = wrapper.file_report(
            report_ref=ref,
            mark=view["canonical_mark"] or view["query"],
            finding=assessment["outcome"],
            severity=assessment["severity"],
            confidence=assessment["confidence"],
            evidence_json=json.dumps(evidence, default=str),
            triggering_read=(latest or {}).get("sighting_id"),
        )
        return {"filed": ok, "report_ref": ref if ok else None,
                "finding": assessment["outcome"],
                "severity": assessment["severity"]}

    def sweep(self, limit=None):
        """
        Assess known vehicles and file a report for every non-compliant one.

        This is the Ministry-facing operation the brief asks for: report the
        vehicle if it is not insured, or if anything about it is suspect.
        """
        summary = {"assessed": 0, "filed": 0, "by_outcome": {}, "reports": []}
        for mark in self.link_index.all_known()[:limit] if limit \
                else self.link_index.all_known():
            view = self.query_vehicle(mark)
            outcome = view["assessment"]["outcome"]
            summary["assessed"] += 1
            summary["by_outcome"][outcome] = summary["by_outcome"].get(outcome, 0) + 1
            if view["assessment"]["reportable"]:
                filed = self.file_report(view)
                if filed.get("filed"):
                    summary["filed"] += 1
                    summary["reports"].append({
                        "report_ref": filed["report_ref"],
                        "mark": mark,
                        "finding": outcome,
                    })
        return summary

    def reports(self, limit=100):
        """Read back the Ministry's report log."""
        wrapper = self.wrappers.get("mot")
        if not wrapper or not wrapper.available:
            return []
        cols = {
            "ref": wrapper._primary_key(),
            "mark": wrapper.column_for("vehicle_mark"),
            "finding": wrapper.column_for("finding"),
            "severity": wrapper.column_for("severity"),
            "confidence": wrapper.column_for("finding_confidence"),
            "evidence": wrapper.column_for("evidence"),
            "raised": wrapper.column_for("raised_on"),
        }
        engine = create_engine(f"sqlite:///{wrapper.db_path}")
        with engine.connect() as conn:
            rows = conn.execute(text(
                f"SELECT * FROM {wrapper.table} "
                f"ORDER BY {cols['raised']} DESC LIMIT :n"), {"n": limit}
            ).mappings().all()
        engine.dispose()

        out = []
        for row in rows:
            row = dict(row)
            try:
                evidence = json.loads(row.get(cols["evidence"]) or "{}")
            except (TypeError, ValueError):
                evidence = {}
            out.append({
                "report_ref": row.get(cols["ref"]),
                "mark": row.get(cols["mark"]),
                "finding": row.get(cols["finding"]),
                "severity": row.get(cols["severity"]),
                "confidence": row.get(cols["confidence"]),
                "raised_on": str(row.get(cols["raised"])),
                "evidence": evidence,
            })
        return out

    # ==================================================================
    def close(self):
        for wrapper in self.wrappers.values():
            wrapper.close()
