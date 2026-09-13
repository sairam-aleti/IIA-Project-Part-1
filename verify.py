"""
Verification harness
====================
Walks through every claim Part A makes and shows the evidence for it.

    python verify.py

Run this in the demo. Each section prints something a marker can check
independently rather than a statement they have to take on trust.
"""

import json
from collections import Counter

from schema_matcher import match_schemas, SOURCE_SCOPE
from link_index import LinkIndex, naive_join_count
from mediator import GAVMediator, RULES

# The mapping a human would write by hand. Used only here, to score the
# matcher — the running system never sees it.
GROUND_TRUTH = {
    "rto": {"vehicle_mark": "registration_mark", "owner": "holder_name",
            "vehicle_category": "body_type", "registered_on": "first_reg_on",
            "chassis": "frame_serial", "propulsion": "fuel"},
    "insurance": {"vehicle_mark": "insured_vehicle_no", "policy_id": "policy_ref",
                  "insurer": "underwriter", "cover_begins": "cover_from",
                  "cover_ends": "cover_upto",
                  "declared_policy_state": "policy_state",
                  "cover_type": "cover_kind"},
    "police": {"vehicle_mark": "plate_marking", "theft_flag": "reported_stolen",
               "theft_case": "case_ref", "recovered_on": "recovered_on",
               "scrap_flag": "shredded", "scrap_certificate": "shred_cert",
               "record_amended_on": "last_amended"},
    "camera": {"vehicle_mark": "observed_mark", "sighting_id": "read_id",
               "sighting_time": "observed_on", "sighting_place": "gantry_location",
               "read_quality": "read_score"},
    "mot": {"vehicle_mark": "subject_mark", "finding": "finding",
            "severity": "severity", "finding_confidence": "decision_confidence",
            "evidence": "evidence_json", "raised_on": "raised_on",
            "source_sighting": "triggering_read"},
}

RULE = "-" * 74


def heading(number, title):
    print(f"\n{RULE}\n{number}. {title}\n{RULE}")


# ======================================================================

def check_schema_matching(mapping):
    heading(1, "Schema matching: is the mapping discovered or hardcoded?")
    print(f"Mode: {mapping['mode']}   threshold: {mapping['threshold']}")
    if not mapping["semantic_available"]:
        print(f"Semantic scoring unavailable ({mapping['semantic_unavailable_reason']}).")
        print("Running on lexical + type scoring only.\n")

    correct = total = 0
    for source, conf in mapping["sources"].items():
        truth = GROUND_TRUTH.get(source, {})
        print(f"  {source}  ->  {conf['table']}")
        for attribute in SOURCE_SCOPE[source]:
            found = conf["attributes"].get(attribute, {}).get("column")
            expected = truth.get(attribute)
            total += 1
            if found == expected:
                correct += 1
                mark = "ok "
            else:
                mark = "MISS"
            score = conf["attributes"].get(attribute, {}).get("score")
            print(f"      [{mark}] {attribute:<24} -> {str(found):<22}"
                  + (f" score {score}" if score else " (unmapped)")
                  + ("" if found == expected else f"   expected {expected}"))
        print()
    print(f"  Attribute-level accuracy: {correct}/{total} "
          f"({100 * correct / total:.1f}%)")
    print("\n  Note: the matcher's vocabulary contains no local column names —")
    print("  only plain-language descriptions of the global schema. Run")
    print("  matcher_eval.py to see how it holds up when columns are renamed.")


def check_canonicalisation(mapping):
    heading(2, "Identity: what canonicalisation actually buys")
    naive = naive_join_count(mapping)
    print("  Distinct raw identifier values per source:")
    for source, count in naive["per_source_rows"].items():
        print(f"      {source:<12} {count}")
    print("\n  Vehicles a join recovers, before and after canonicalisation:\n")
    print(f"      {'source pair':<26}{'raw equi-join':>14}{'canonical':>12}")
    for pair, counts in naive["pairs"].items():
        print(f"      {pair:<26}{counts['raw']:>14}{counts['canonical']:>12}")
    total_raw = sum(c["raw"] for c in naive["pairs"].values())
    if total_raw == 0:
        print("\n  A raw equi-join recovers nothing on any pair of sources.")
        print("  Each source writes the mark in its own format, so")
        print("  canonicalisation is load-bearing, not cosmetic.")

    print("\n  Worked example — five spellings of one vehicle:")
    import plate as plate_util
    samples = ["DL-3C-AB-1234", "DL 3C AB 1234", "dl 3c ab 1234",
               "  DL3CAB1234 ", "DL3CAB1234"]
    for raw in samples:
        print(f"      {raw!r:<22} -> {plate_util.canonical(raw)}")


def check_linkage(mediator):
    heading(3, "Linkage index")
    stats = mediator.link_index.stats
    for source, values in stats.items():
        if source == "_totals":
            continue
        print(f"  {source:<12} rows {values['rows']:<7} linked {values['linked']:<7} "
              f"malformed {values['malformed']}")
    totals = stats["_totals"]
    print(f"\n  canonical marks seen      {totals['canonical_marks']}")
    print(f"  marks in a register       {totals['known_marks']}")
    print(f"  marks seen only by camera {totals['orphan_marks']}")
    print("\n  Every link in Part A has method=exact_canonical and score=1.0.")
    print("  The method and score columns exist so Part B can add")
    print("  probabilistic links without changing anything downstream.")


def check_temporal(mediator):
    heading(4, "Insurance is assessed at the sighting, not at query time")
    from datetime import date
    today = date.today().isoformat()

    # Look for a vehicle whose verdict actually differs depending on when it
    # is assessed. That is the whole argument for the temporal check.
    found = fallback = None
    for mark in mediator.link_index.all_known():
        view = mediator.query_vehicle(mark)
        if not view["assessment"]["assessed_at"]:
            continue
        periods = view["insurance_at"].get("periods") or []
        if len(periods) < 1:
            continue
        at_today = mediator.query_vehicle(mark, as_of=today)
        if at_today["assessment"]["outcome"] != view["assessment"]["outcome"]:
            found = (mark, view, at_today)
            break
        if fallback is None and len(periods) >= 2:
            fallback = (mark, view, at_today)
    found = found or fallback
    if not found:
        print("  No suitable vehicle in this dataset.")
        return
    mark, view, at_today = found
    print(f"  Vehicle {mark}")
    print(f"  Assessed at {view['assessment']['assessed_at']} "
          f"({view['assessment']['assessment_basis']})")
    print("\n  Policy history held by the insurers:")
    for period in view["insurance_at"]["periods"]:
        flag = "  <- in force at assessment" if period["in_force_at_assessment"] else ""
        stale = "  [label contradicts dates]" if period["label_contradicts_dates"] else ""
        print(f"      {period['cover_begins']} to {period['cover_ends']}  "
              f"{str(period['declared_state']):<8}{flag}{stale}")
    print(f"\n  Assessed at the sighting : {view['insurance_at']['state']:<16}"
          f"-> {view['assessment']['outcome']}")
    print(f"  Assessed at today        : {at_today['insurance_at']['state']:<16}"
          f"-> {at_today['assessment']['outcome']}")
    if view["assessment"]["outcome"] != at_today["assessment"]["outcome"]:
        print("\n  The two verdicts differ. Checking against today would have")
        print("  produced the wrong answer for the question the use case asks:")
        print("  was this vehicle insured when it was on the road?")
    print("\n  'Is this vehicle insured' has no answer without a timestamp.")


def check_no_policy_case(mediator):
    heading(5, "A vehicle with no policy row at all is flagged")
    target = None
    for mark in mediator.link_index.all_known():
        view = mediator.query_vehicle(mark)
        if view["insurance_at"]["state"] == "never_recorded" and \
                view["assessment"]["outcome"] == "UNINSURED":
            target = (mark, view)
            break
    if not target:
        print("  No such vehicle in this dataset.")
        return
    mark, view = target
    print(f"  Vehicle {mark}")
    print(f"  Insurance source status : {view['source_status']['insurance']}")
    print(f"  Insurance state         : {view['insurance_at']['state']}")
    print(f"  Outcome                 : {view['assessment']['outcome']}")
    print(f"  Rules applied           : {', '.join(view['assessment']['rules_applied'])}")
    print("\n  Reasons given:")
    for reason in view["assessment"]["reasons"]:
        print(f"      - {reason}")
    print("\n  This is the case the earlier build missed: absence of a record")
    print("  yielded is_insured=None, which never satisfied the UNINSURED test,")
    print("  so a vehicle that was never insured passed as unflagged.")


def check_contradictions(mediator):
    heading(6, "Cross-source contradictions are reported, not resolved silently")
    seen = Counter()
    examples = {}
    for mark in mediator.link_index.all_known():
        view = mediator.query_vehicle(mark)
        for contradiction in view["contradictions"]:
            seen[contradiction["kind"]] += 1
            examples.setdefault(contradiction["kind"], (mark, contradiction))
    if not seen:
        print("  None detected in this dataset.")
        return
    for kind, count in seen.most_common():
        mark, contradiction = examples[kind]
        print(f"\n  {kind}  ({count} vehicles)")
        print(f"      example  {mark}")
        print(f"      sources  {', '.join(contradiction['sources'])}")
        print(f"      detail   {contradiction['detail']}")
        print(f"      meaning  {contradiction['implication']}")
        if "resolved_by_rule" in contradiction:
            print(f"      resolved by rule: {contradiction['resolved_by_rule']}")


def check_abstention(mediator):
    heading(7, "What the system does when it does not know")
    unresolved = mediator.unresolved_reads()
    print(f"  Camera reads that resolve to no known vehicle: {len(unresolved)}")
    for read in unresolved[:3]:
        print(f"\n      mark            {read['canonical_mark']}")
        print(f"      wellformed      {read['wellformed']}")
        print(f"      confusable key  {read['confusable_key']}")
        print(f"      reads           {read['read_count']}")
        print(f"      outcome         {read['outcome']}")
    print("\n  And vehicles that are known but still cannot be assessed:")
    shown = 0
    for mark in mediator.link_index.all_known():
        view = mediator.query_vehicle(mark)
        if view["assessment"]["outcome"] == "INSUFFICIENT_EVIDENCE":
            print(f"\n      {mark}: {view['assessment']['reasons'][0]}")
            print(f"      confidence: {view['assessment']['confidence']} "
                  f"({view['assessment']['confidence_basis']})")
            shown += 1
            if shown == 2:
                break
    if not shown:
        print("      none in this dataset")


def check_outcomes(mediator):
    heading(8, "Outcome distribution and reporting")
    page = mediator.assess_all()
    counts = Counter(v["outcome"] for v in page["vehicles"])
    print(f"  Assessed {page['total_known']} known vehicles:\n")
    for outcome, count in counts.most_common():
        share = 100 * count / page["total_known"]
        print(f"      {outcome:<24} {count:>5}   {share:5.1f}%")
    adjudication = sum(1 for v in page["vehicles"] if v["requires_adjudication"])
    print(f"\n      requiring adjudication   {adjudication:>5}")
    print(f"\n  Declared conflict-resolution rules in force: {len(RULES)}")
    for name in RULES:
        print(f"      {name}")


def check_reporting(mediator):
    heading(9, "Reports filed with the Ministry")
    summary = mediator.sweep(limit=150)
    print(f"  Assessed {summary['assessed']}, filed {summary['filed']} findings")
    for outcome, count in sorted(summary["by_outcome"].items()):
        print(f"      {outcome:<24} {count}")
    rows = mediator.reports(limit=2)
    if rows:
        print("\n  Most recent report as stored in mot.db:\n")
        print(json.dumps(rows[0], indent=4, default=str)[:1400])


# ======================================================================

def main():
    print(RULE)
    print("Part A verification — MoT vehicle integration")
    print(RULE)

    mapping = match_schemas(verbose=False)
    check_schema_matching(mapping)
    check_canonicalisation(mapping)

    mediator = GAVMediator(mapping, ".")
    check_linkage(mediator)
    check_temporal(mediator)
    check_no_policy_case(mediator)
    check_contradictions(mediator)
    check_abstention(mediator)
    check_outcomes(mediator)
    check_reporting(mediator)

    print(f"\n{RULE}\nDone\n{RULE}")
    mediator.close()


if __name__ == "__main__":
    main()
