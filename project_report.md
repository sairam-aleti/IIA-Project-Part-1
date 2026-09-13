# Part A — Traditional Data Integration

**Course** CSE656 Information Integration and Application, IIIT Delhi
**Problem** Identification of uninsured vehicles while they are on the road
**Architecture** Global-As-View mediator over five autonomous sources

---

## 1. The problem, stated precisely

A vehicle is observed on the road. The Ministry of Transportation needs its
complete view: is it insured, was it insured *at that moment*, when was it
registered, has it been reported stolen, has it been scrapped — and if anything
is wrong, a report must be raised.

The data to answer this exists, but in five agencies that have never agreed on
a schema:

| Source | Table | Identifier column | Plate format |
|---|---|---|---|
| `rto.db` | `vehicle_register` | `registration_mark` | `DL-3C-AB-1234` |
| `insurance.db` | `motor_policy` | `insured_vehicle_no` | `DL 3C AB 1234`, some lower case |
| `police.db` | `theft_and_scrap_register` | `plate_marking` | `DL3CAB1234` |
| `camera.db` | `anpr_read` | `observed_mark` | `DL3CAB1234`, some padded, some misread |
| `mot.db` | `compliance_report` | `subject_mark` | `DL3CAB1234` |

No two name the identifier the same way and no two store it the same way. The
coverage is also ragged: a vehicle in one source need not appear in another.

---

## 2. Central design commitment

The course frames integration as *constructing defensible knowledge from
heterogeneous evidence*, and asks what an intelligent integration system should
do when it does not know the answer. Part A takes both seriously, so the system
is built around three commitments:

**Every fact is traceable.** Each value in the global view carries the source,
table, local column, confidence, retrieval time, and — where the value was
derived rather than read — the derivation that produced it.

**Every conflict is resolved by a declared rule, or not at all.** Six rules are
declared in `mediator.py` and exposed at `GET /api/v1/rules`. Any rule applied
in reaching a conclusion is recorded in that conclusion. Where two sources
assert mutually impossible facts and no rule settles it, the system reports the
contradiction rather than silently choosing.

**The system can decline.** There are four outcomes, not three:

| Outcome | Meaning |
|---|---|
| `COMPLIANT` | Insured at the moment observed, nothing adverse |
| `UNINSURED` | No cover in force at the moment observed |
| `SUSPICIOUS` | Stolen, scrapped, unregistered, or self-contradictory |
| `INSUFFICIENT_EVIDENCE` | The system declines to conclude |

The fourth matters because a report to the Ministry is an accusation against a
citizen. Filing one on weak evidence is a worse failure than filing none. Part
A reaches abstention through three distinct routes: a plate that resolves to no
known vehicle, a vehicle never observed so there is no moment to assess, and a
source that would settle the question being unreachable.

---

## 3. Architecture

```
                         ┌──────────────────────────┐
   plate, any format ───►│  plate.canonical()       │
                         │  format → canonical mark │
                         └────────────┬─────────────┘
                                      ▼
                         ┌──────────────────────────┐
                         │  LinkIndex               │  identity as a table:
                         │  mark → source → raw     │  method + score per link
                         └────────────┬─────────────┘
                                      ▼
      ┌──────────────────────────────────────────────────────────┐
      │  GAVMediator                                             │
      │    dispatch → merge → evaluate at an instant →           │
      │    detect contradictions → assess → report               │
      └──┬──────────┬──────────┬──────────┬──────────┬───────────┘
         ▼          ▼          ▼          ▼          ▼
      RTO       Insurance   Police     Camera      MoT
     wrapper     wrapper    wrapper    wrapper    wrapper
         │          │          │          │          │
      rto.db   insurance.db police.db  camera.db   mot.db
         ▲          ▲          ▲          ▲          ▲
         └──────────┴──────────┴──────────┴──────────┘
                 attribute mapping, discovered at startup
                          by SchemaMatcher
```

Nothing is materialised. The mediator holds no vehicle data; it dispatches,
merges in memory, and derives.

---

## 4. Schema matching

The matcher discovers which local column carries each attribute of the global
schema. Three properties are worth defending in the viva.

**It matches every attribute, not just the join key.** Thirty-two
attribute-to-column mappings across five sources. The wrappers therefore
contain no local column names: rename `holder_name` to `owner_of_record` and
the system keeps working. An earlier iteration of this project matched only the
key and hardcoded everything else, which meant the claim "works even if column
names differ" was true of one column out of twenty-odd.

**Its vocabulary contains no local column names.** Scoring is against
plain-language descriptions of the *global* schema — "calendar date on which
insurance cover expires" — not against a list of column names to look for. This
is a real distinction: an earlier version listed `reg_num`, `plate_id` and
`license_tag` as reference terms, which were verbatim the columns it was meant
to discover. That is a lookup table wearing a matcher's clothes.

**It uses column types, not just names.** A concept expecting a date is not
assigned to a text column. This is what stops `observed_mark` being mistaken
for a sighting timestamp on name similarity alone.

Scoring is a weighted sum, less a type penalty:

```
score(column, attribute) = 0.55 · cosine(embed(column), embed(description))
                         + 0.45 · token_levenshtein(column, description)
                         − 0.45 · [type incompatible]
```

Assignment is greedy and one-to-one per source. Anything below a threshold of
0.34 is left **unmapped** rather than forced, and the mediator reports an
unmapped attribute as unavailable. Forcing a low-confidence match would produce
a confidently wrong value, which is the one failure mode that actually causes
harm.

### 4.1 Instance-level evidence for the join key

Name-based matching is adequate for ordinary attributes: a mismapped `severity`
costs one field. The identifier is different — a wrong join key links nothing,
so every downstream fact is lost and no care further down recovers it.

For that one attribute the matcher also inspects the data, sampling the column
and measuring what fraction of values canonicalise into a valid registration
mark. A column of plates is recognisable as plates whatever it is called.

### 4.2 Measured robustness

`matcher_eval.py` copies the databases, renames every column to vocabulary the
matcher has never seen, and scores the result. Reported honestly, including the
regime where it fails:

| Regime | Example rename | Correct | Unmapped (safe) | Wrong (unsafe) |
|---|---|---|---|---|
| As shipped | — | 32/32 | 0 | 0 |
| Abbreviated | `registration_mark` → `regn_mk` | 30/32 | 2 | 0 |
| Synonymous | `registration_mark` → `licence_tag` | 21/32 | 4 | 7 |
| Opaque | `registration_mark` → `c25` | 6/32 | 25 | 1 |

(Figures from lexical-only mode. The semantic model recovers much of the
synonymous regime, which is precisely what embeddings are for; run the harness
with sentence-transformers available to see it.)

Two things to note. First, the join key resolves correctly in **all four
regimes** including the opaque one, because instance evidence does not depend
on naming. Second, failures concentrate in the *unmapped* column, not the
*wrong* column — the system degrades toward "I cannot tell you" rather than
toward a false report.

Recovering the opaque case in general needs instance-level evidence for every
attribute: value distributions, formats, ranges. That is Part B work, and this
harness is the measurement it will be judged against.

---

## 5. Identity resolution

Entity resolution is a **table**, not a join condition. `LinkIndex` builds, per
source, a mapping from canonical mark to the raw values that source holds:

```
DL3CAB1234
    rto        "DL-3C-AB-1234"     exact_canonical  1.0
    insurance  "dl 3c ab 1234"     exact_canonical  1.0
    police     "DL3CAB1234"        exact_canonical  1.0
    camera     "  DL3CAB1234 "     exact_canonical  1.0
```

Every link carries a method and a score. In Part A the only method is
`exact_canonical` and every score is 1.0, because canonicalisation is
deterministic — a link either exists or it does not. The columns exist so Part
B can add probabilistic links without changing anything downstream.

**Canonicalisation is load-bearing, not cosmetic.** Measured by `verify.py`:

| Source pair | Raw equi-join | After canonicalisation |
|---|---|---|
| rto ∩ insurance | 0 | 791 |
| rto ∩ camera | 0 | 945 |
| insurance ∩ camera | 0 | 805 |
| rto ∩ police | 0 | 179 |

A join on the raw identifier columns recovers nothing at all.

Part A deliberately does **not** resolve character-level corruption. A read of
`DL3CA81234` for `DL3CAB1234` canonicalises cleanly and still matches nothing,
so it becomes an unattributed read and the system abstains. `confusable_key`
collapses OCR-confusable glyphs and is computed but not acted on: acting on it
means producing a match that might be wrong, which is Part B's problem to solve
with probabilities.

---

## 6. Temporal insurance evaluation

The use case asks about a vehicle **on the road**. The question is therefore not
"is this vehicle insured now" but "was it insured when it was observed". These
give different answers, and an example from the live dataset shows it:

```
Vehicle DL09M2591
  policy on record   2026-06-29 → 2028-06-28  (Active)
  observed on        2026-05-30

  assessed at the sighting :  lapsed   → UNINSURED
  assessed at today        :  covered  → COMPLIANT
```

Checking against today would have cleared a vehicle that was uninsured when it
was actually on the road.

Insurance is therefore modelled as a **history**, not a flag. `motor_policy`
holds one row per policy, a vehicle may hold several consecutive policies with
gaps between them, and evaluation walks the history looking for a period
containing the assessment instant. `GET /api/v1/vehicle/{plate}?as_of=YYYY-MM-DD`
assesses against any instant.

Four insurance states are distinguished, and the difference between the last
two is the point:

| State | Meaning |
|---|---|
| `covered` | A policy period contains the instant |
| `lapsed` | Policies exist, none covers the instant |
| `never_recorded` | The insurer holds no policy at all |
| `unknown` | The insurance source was unreachable |

`never_recorded` is evidence of non-insurance. `unknown` is not evidence of
anything and forces abstention. An earlier iteration of this project collapsed
both into a null and tested `is_insured is False`, so a vehicle that had never
been insured produced `None`, failed the test, and passed as unflagged — the
system's headline question silently returning the wrong answer. `verify.py`
section 5 demonstrates the fix against live data.

---

## 7. Conflict resolution rules

| Rule | Statement |
|---|---|
| `date_over_label` | When a policy's status label disagrees with its cover dates, the dates govern |
| `absence_is_evidence` | A reachable source holding no record is evidence, not missing data |
| `unreachable_is_not_evidence` | An unreachable source forces abstention, never a default assumption |
| `assess_at_sighting` | Insurance is evaluated at the moment observed, not at query time |
| `contradiction_needs_adjudication` | Mutually impossible facts are both reported; no silent winner |
| `identity_before_assessment` | No conclusion is reached for a plate that does not resolve |

`date_over_label` earns its keep: 111 policy rows in the generated data are
labelled `Active` with a cover period that has already ended. The label is
stale; the dates are not.

---

## 8. Contradiction detection

Six classes, each reported with the colliding sources and what the collision
could mean. Counts from a 1000-vehicle run:

| Contradiction | Count | What it could mean |
|---|---|---|
| `policy_label_contradicts_dates` | 111 | Stale label — resolved by rule |
| `scrapped_but_observed` | 29 | Scrap record wrong, or plate cloned |
| `insured_but_unregistered` | 29 | Unregistered vehicle, or divergent records |
| `stolen_and_still_driving` | 24 | Active theft, or plate cloned |
| `observed_before_registration` | 17 | Plate reuse, backdated entry, or bad read |
| `stolen_flag_not_cleared` | 13 | Police record internally stale |

Only the first has a rule that settles it. The other five set
`requires_adjudication` and push the outcome to `SUSPICIOUS`. A scrapped vehicle
photographed on a highway is either a wrong scrap record or a cloned plate, and
the honest response is to say so rather than pick.

---

## 9. Reporting to the Ministry

`mot.db` is the fifth source required by the brief — the reporting sink. It is
readable like any other source (so prior findings appear in a vehicle's view)
and is the only source the mediator writes to in normal operation.

`POST /api/v1/sweep` assesses vehicles and files a finding for each
non-compliant one. Each report stores the outcome, findings, reasons, rules
applied, the assessment instant and its basis, contradiction kinds, the identity
resolution including every raw value matched, and per-source reachability. A
reviewing officer can reconstruct the decision without access to the running
system.

Abstentions are filed too. A record that the system looked and could not tell
is exactly what an officer needs in order to go and look themselves.

### 9.1 Understanding the User Interface (UI Tabs)

The React dashboard visualizes this architecture through several distinct views:

- **Flagged Vehicles**: This view filters the global state to show only vehicles that have returned a `SUSPICIOUS` or `UNINSURED` outcome. It highlights *why* they were flagged (e.g., Stolen, Scrapped, or Lapsed Insurance). It acts as the primary actionable queue for enforcement officers.
- **Unattributed Reads**: This tab shows camera sightings (`anpr_reads`) where the license plate could not be linked to any registered vehicle in the RTO or Insurance databases, even after canonicalization (removing hyphens/spaces). These are essentially "ghost cars" that force the `INSUFFICIENT_EVIDENCE` outcome.
- **Ministry Reports**: This acts as a live feed of the `mot.db` sink. Every time the system evaluates a vehicle and finds non-compliance (or abstains), a permanent audit log is generated here. It shows the Severity, Confidence, and the exact Contradiction rule that was triggered.

---

## 10. Distributed writes

The write endpoints apply a **compensating rollback**: if any source rejects a
write, rows already committed elsewhere are deleted again and the response
reports what happened per source.

This is worth flagging honestly. An earlier version of this document claimed
"only if all local database transactions commit successfully does the Mediator
return a success response" while the code committed each source independently
with no rollback, happily returning `"partially created"`. SQLite provides no
cross-database transaction, so atomicity has to be **built** rather than
claimed. What is implemented is compensation, not two-phase commit: a
compensating delete can itself fail, and the response says so rather than
pretending otherwise.

---

## 11. Limitations

Stated plainly, because each one is a Part B or Part C entry point.

1. **Character-level misreads are not resolved.** 301 canonical marks in the
   generated data are camera-only and unattributable. Part A abstains on all of
   them.
2. **Every value confidence is 1.0.** Part A's uncertainty lives in identity and
   in absence, not in the values. The field is plumbed through the whole stack
   so Part B populates it rather than adding it.
3. **No source reliability weighting.** All five sources are trusted equally.
   When police and camera contradict each other, Part A reports both; it has no
   basis for preferring one.
4. **The linkage index is rebuilt on write.** A sub-second scan at this scale;
   a production system would maintain it incrementally.
5. **Instance evidence is used for the join key only.** Extending it to every
   attribute is what recovers the opaque-rename regime.
6. **Contradiction rules are hand-written.** Six classes, enumerated by a human.
   A learned or LLM-assisted approach would generalise.

---

## 12. Reproducing the results

```bash
python data_generator.py     # build the five source databases
python verify.py             # nine sections of evidence for the claims above
python matcher_eval.py       # matcher robustness under column renaming
python -m uvicorn main:app --port 8000
```

`verify.py` is the script to run in the demo. Each section prints something a
marker can check independently rather than a claim they must take on trust.

Both scripts run without network access. If `sentence-transformers` or its model
is unavailable, the matcher falls back to lexical plus type scoring and says so
in its output and at `GET /health`; the mapping is still derived, not hardcoded.

---

## 13. Viva preparation

**Why a mediator rather than a warehouse?**
The sources are autonomous and the compliance question is time-sensitive. More
importantly, a warehouse would have to decide at load time what the canonical
value of a contradictory fact is, and that decision is exactly what we want to
keep visible and defer to a reviewer.

**Your schema matcher scores 100%. Did you tell it the answer?**
Partly, unavoidably — the global schema descriptions use domain vocabulary that
overlaps the local column names, because that is what the domain vocabulary is.
So we measured it instead of asserting it. `matcher_eval.py` renames every
column to unseen vocabulary and reports accuracy across three regimes, including
one where it drops to 6/32. The defensible claim is not "it is perfect" but
"here is its accuracy under perturbation, and here is the shape of its
failures."

**What if two attributes want the same column?**
Assignment is one-to-one per source. The stronger pair wins; the loser either
takes its next-best column or falls below threshold and is reported unmapped.

**Why does the identifier get special treatment?**
Because its failure mode is unrecoverable. A wrong `severity` costs one field. A
wrong join key loses every fact about every vehicle.

**A source is down. What happens?**
It depends which one. An unreachable camera loses sightings, so there is no
assessment instant and the system abstains. An unreachable insurer means
insured status is unknown, so the system abstains. An unreachable police
register means adverse flags cannot be checked; the insurance question can
still be answered, and the report records which sources were consulted. The
governing rule is `unreachable_is_not_evidence` — absence of contact is never
read as absence of a problem.

**Is this vehicle insured?**
Not answerable as asked. Insured *when*? The system requires an instant and
defaults to the most recent sighting, because that is the question the use case
actually poses.

**What does your system do when it does not know?**
It returns `INSUFFICIENT_EVIDENCE`, withholds a confidence value rather than
inventing one, lists the specific reasons it could not conclude, and files the
abstention with the Ministry so a human can pick it up. That is the answer to
the course's closing challenge, and Part A reaches it deterministically —
through missing records, unresolvable identity, and unreachable sources. Part B
will reach the same state through probability.
