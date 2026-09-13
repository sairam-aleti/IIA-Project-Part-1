"""
Source database generator
=========================
Builds five autonomous SQLite databases that stand in for five agencies which
have never coordinated on a schema.

Design commitments, each of which the integration layer has to earn back:

1. No two sources name the registration mark the same way, and none of them
   uses a name the schema matcher has been told about in advance.
       rto        vehicle_register.registration_mark
       insurance  motor_policy.insured_vehicle_no
       police     theft_and_scrap_register.plate_marking
       camera     anpr_read.observed_mark
       mot        compliance_report.subject_mark

2. Each source stores the mark in its own format (hyphenated, spaced, compact,
   mixed case, stray whitespace). A naive equi-join across the raw columns
   returns almost nothing — see verify.py.

3. Coverage is ragged. A vehicle present in one source is not guaranteed to be
   present in another:
       - vehicles with no policy row at all  -> genuinely never insured
       - vehicles absent from the RTO register -> unregistered or cloned plate
       - the police register only holds vehicles with something to report
       - some camera reads are OCR-corrupted and match no known vehicle

4. Insurance is a history, not a flag. A vehicle can hold several consecutive
   policies with gaps between them, so "was this vehicle insured?" is only
   answerable with respect to a point in time.

5. mot.db is the reporting sink required by the brief. It is seeded with a few
   historical findings and then written to by the mediator at run time.
"""

import json
import os
import random
import string
from datetime import date, timedelta

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, Integer, String,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from faker import Faker

import plate as plate_util

fake = Faker("en_IN")
Faker.seed(20250916)
random.seed(20250916)

RTOBase = declarative_base()
InsuranceBase = declarative_base()
PoliceBase = declarative_base()
CameraBase = declarative_base()
MoTBase = declarative_base()


# ======================================================================
# Schemas — deliberately divergent vocabulary across the five agencies
# ======================================================================

class VehicleRegister(RTOBase):
    """Regional Transport Office register of registered vehicles."""
    __tablename__ = "vehicle_register"
    registration_mark = Column(String, primary_key=True)   # DL-3C-AB-1234
    holder_name = Column(String)
    body_type = Column(String)
    first_reg_on = Column(Date)
    frame_serial = Column(String, unique=True)
    fuel = Column(String)


class MotorPolicy(InsuranceBase):
    """Insurer consortium policy ledger. One row per policy, not per vehicle."""
    __tablename__ = "motor_policy"
    policy_ref = Column(String, primary_key=True)
    insured_vehicle_no = Column(String, index=True)         # DL 3C AB 1234
    underwriter = Column(String)
    cover_from = Column(Date)
    cover_upto = Column(Date)
    policy_state = Column(String)
    cover_kind = Column(String)


class TheftAndScrapRegister(PoliceBase):
    """Police register. Only vehicles with something to report appear here."""
    __tablename__ = "theft_and_scrap_register"
    plate_marking = Column(String, primary_key=True)        # DL3CAB1234
    reported_stolen = Column(Boolean)
    case_ref = Column(String, nullable=True)
    recovered_on = Column(Date, nullable=True)
    shredded = Column(Boolean)
    shred_cert = Column(String, nullable=True)
    last_amended = Column(DateTime)


class AnprRead(CameraBase):
    """Roadside automatic number plate recognition reads."""
    __tablename__ = "anpr_read"
    read_id = Column(Integer, primary_key=True, autoincrement=True)
    observed_mark = Column(String, index=True)              # DL3CAB1234
    gantry_location = Column(String)
    observed_on = Column(DateTime)
    read_score = Column(Float)


class ComplianceReport(MoTBase):
    """Ministry of Transportation sink. Findings raised against vehicles."""
    __tablename__ = "compliance_report"
    report_ref = Column(String, primary_key=True)
    subject_mark = Column(String, index=True)               # DL3CAB1234
    finding = Column(String)
    severity = Column(String)
    decision_confidence = Column(Float)
    evidence_json = Column(String)
    raised_on = Column(DateTime)
    triggering_read = Column(Integer, nullable=True)


DB_FILES = {
    "rto.db": (RTOBase, "rto"),
    "insurance.db": (InsuranceBase, "insurance"),
    "police.db": (PoliceBase, "police"),
    "camera.db": (CameraBase, "camera"),
    "mot.db": (MoTBase, "mot"),
}


def _fresh_sessions(db_dir="."):
    sessions = {}
    for filename, (base, label) in DB_FILES.items():
        path = os.path.join(db_dir, filename)
        if os.path.exists(path):
            os.remove(path)
        engine = create_engine(f"sqlite:///{path}")
        base.metadata.create_all(engine)
        sessions[label] = sessionmaker(bind=engine)()
    return sessions


# ======================================================================
# Plate minting
# ======================================================================

STATE_CODES = ["DL", "HR", "UP", "MH", "KA", "TN", "WB", "GJ", "RJ", "PB"]


def _mint_plate(used):
    while True:
        mark = "{}{:02d}{}{:04d}".format(
            random.choice(STATE_CODES),
            random.randint(1, 99),
            "".join(random.choices(string.ascii_uppercase, k=random.choice([1, 2, 2, 3]))),
            random.randint(1, 9999),
        )
        if mark not in used:
            used.add(mark)
            return mark


def _corrupt(mark):
    """Flip one glyph to its OCR lookalike, simulating a bad read."""
    swaps = {"O": "0", "0": "O", "I": "1", "1": "I", "S": "5", "5": "S",
             "B": "8", "8": "B", "Z": "2", "2": "Z", "G": "6", "6": "G"}
    positions = [i for i, ch in enumerate(mark) if ch in swaps]
    if not positions:
        return mark
    i = random.choice(positions)
    return mark[:i] + swaps[mark[i]] + mark[i + 1:]


# ======================================================================
# Generation
# ======================================================================

BODY_TYPES = ["Sedan", "Hatchback", "SUV", "Motorcycle", "Goods carrier", "Bus"]
FUELS = ["Petrol", "Diesel", "CNG", "Electric", "Hybrid"]
UNDERWRITERS = ["SecureDrive General", "AutoGuard Ltd", "SafeJourney Assurance",
                "National Vehicle Insurers", "Bharat Motor Cover"]
COVER_KINDS = ["Comprehensive", "Third party only", "Third party fire and theft"]
GANTRIES = ["NH-48 Gurugram toll plaza", "Ring Road Lajpat Nagar gantry",
            "Outer Ring Road Mayapuri", "NH-24 Ghaziabad border",
            "DND Flyway Sector 15", "Airport Express T3 approach",
            "Yamuna Expressway km 42", "Noida Sector 62 junction"]


def generate(num_vehicles=1000, db_dir="."):
    s = _fresh_sessions(db_dir)
    today = date.today()
    used = set()
    marks = [_mint_plate(used) for _ in range(num_vehicles)]

    # ---- how each vehicle is distributed across the sources ----
    #
    # A vehicle is only registered, insured, or on the police register if the
    # relevant agency happens to hold a record for it. That raggedness is the
    # point: absence of a row is evidence, not an error.
    registered = set(random.sample(marks, int(num_vehicles * 0.96)))
    unregistered = [m for m in marks if m not in registered]
    ever_insured = set(random.sample(marks, int(num_vehicles * 0.82)))
    never_insured = [m for m in marks if m not in ever_insured]

    stats = {
        "vehicles": num_vehicles,
        "registered": len(registered),
        "unregistered": len(unregistered),
        "never_insured": len(never_insured),
    }

    # ---- 1. RTO register ----
    for mark in marks:
        if mark not in registered:
            continue
        s["rto"].add(VehicleRegister(
            registration_mark=plate_util.as_hyphenated(mark),
            holder_name=fake.name(),
            body_type=random.choice(BODY_TYPES),
            first_reg_on=fake.date_between(start_date="-14y", end_date="-30d"),
            frame_serial="MA3" + "".join(random.choices(string.ascii_uppercase + string.digits, k=14)),
            fuel=random.choice(FUELS),
        ))

    # ---- 2. Insurance ledger: a history of policies, with gaps ----
    policy_seq = 0
    lapsed_now = 0
    for mark in marks:
        if mark not in ever_insured:
            continue
        # Walk forward in time issuing consecutive annual policies. A gap
        # between two policies means the vehicle was uninsured in between.
        #
        # Two thirds of insured vehicles are given a history that reaches the
        # present; the rest lapsed at some point and were never renewed. Both
        # populations matter: the first proves the temporal check accepts valid
        # cover, the second proves it rejects stale cover.
        currently_covered = random.random() < 0.66
        if currently_covered:
            cursor = today - timedelta(days=random.randint(30, 340))
        else:
            cursor = today - timedelta(days=random.randint(500, 2200))
        cover_upto = cursor
        for _ in range(random.randint(1, 3)):
            cover_from = cursor
            cover_upto = cover_from + timedelta(days=random.choice([365, 365, 730]))
            expired = cover_upto < today
            policy_seq += 1
            s["insurance"].add(MotorPolicy(
                policy_ref=f"POL-{policy_seq:08d}",
                # the insurers key on a spaced mark, and a fifth of their
                # back-office entries were typed in lower case
                insured_vehicle_no=(plate_util.as_spaced(mark).lower()
                                    if random.random() < 0.2
                                    else plate_util.as_spaced(mark)),
                underwriter=random.choice(UNDERWRITERS),
                cover_from=cover_from,
                cover_upto=cover_upto,
                # the recorded state is stale for some rows: it still reads
                # Active even though cover_upto has passed. The mediator must
                # trust the date over the label.
                policy_state=("Active" if (not expired or random.random() < 0.3)
                              else random.choice(["Lapsed", "Expired"])),
                cover_kind=random.choice(COVER_KINDS),
            ))
            # gap of 0 to 200 days before the next policy, if any
            cursor = cover_upto + timedelta(days=random.choice([0, 0, 0, 15, 60, 200]))
            if cursor > today:
                break
        if cover_upto < today:
            lapsed_now += 1
    stats["policies"] = policy_seq
    stats["lapsed_at_today"] = lapsed_now

    # ---- 3. Police register: only vehicles with something to report ----
    stolen = set(random.sample(marks, int(num_vehicles * 0.045)))
    scrapped = set(random.sample(marks, int(num_vehicles * 0.03)))
    on_register = stolen | scrapped | set(random.sample(marks, int(num_vehicles * 0.12)))
    for mark in sorted(on_register):
        is_stolen = mark in stolen
        is_scrapped = mark in scrapped
        # a third of stolen vehicles have been recovered but the flag was
        # never cleared — a stale-record conflict the mediator should notice
        recovered = (fake.date_between(start_date="-1y", end_date="-10d")
                     if is_stolen and random.random() < 0.33 else None)
        s["police"].add(TheftAndScrapRegister(
            plate_marking=mark,
            reported_stolen=is_stolen,
            case_ref=f"FIR/{random.randint(2019, 2026)}/{random.randint(1000, 9999)}" if is_stolen else None,
            recovered_on=recovered,
            shredded=is_scrapped,
            shred_cert=f"CoD-{random.randint(100000, 999999)}" if is_scrapped else None,
            last_amended=fake.date_time_between(start_date="-3y", end_date="now"),
        ))
    stats["police_rows"] = len(on_register)
    stats["stolen"] = len(stolen)
    stats["scrapped"] = len(scrapped)

    # ---- 4. ANPR reads ----
    reads = 0
    corrupted = 0
    for mark in marks:
        for _ in range(random.randint(1, 5)):
            score = round(random.uniform(0.55, 0.99), 2)
            observed = mark
            # low-confidence reads sometimes carry a corrupted glyph. Part A
            # cannot resolve these and must abstain on them.
            if score < 0.75 and random.random() < 0.20:
                observed = _corrupt(mark)
                corrupted += 1
            # a few gantries emit padded strings
            if random.random() < 0.08:
                observed = f"  {observed} "
            s["camera"].add(AnprRead(
                observed_mark=observed,
                gantry_location=random.choice(GANTRIES),
                observed_on=fake.date_time_between(start_date="-400d", end_date="now"),
                read_score=score,
            ))
            reads += 1
    stats["anpr_reads"] = reads
    stats["corrupted_reads"] = corrupted

    # ---- 5. MoT sink: a few historical findings ----
    for i, mark in enumerate(random.sample(marks, 20), start=1):
        s["mot"].add(ComplianceReport(
            report_ref=f"MOT-2026-{i:05d}",
            subject_mark=mark,
            finding="UNINSURED",
            severity="MEDIUM",
            decision_confidence=1.0,
            evidence_json=json.dumps({"seeded": True, "note": "historical backlog entry"}),
            raised_on=fake.date_time_between(start_date="-180d", end_date="-30d"),
            triggering_read=None,
        ))
    stats["seeded_reports"] = 20

    for session in s.values():
        session.commit()
        session.close()
    return stats


if __name__ == "__main__":
    stats = generate(1000)
    print("Generated five isolated source databases\n")
    width = max(len(k) for k in stats)
    for key, value in stats.items():
        print(f"  {key.replace('_', ' '):<{width + 2}} {value}")
    print("\n  rto.db  insurance.db  police.db  camera.db  mot.db")
