# Open Questions

Questions that need lab input before the conversion can be finalized or uploaded to DANDI.

Last updated: **2026-10-20**, after the PR #2 review changes (Intan sync now decoded by
NeuroConv's `IntanConverter`, start time from the Intan directory name only), the first full
raw conversion of `A0662 / 2022_08_29`, and a re-run of the DANDI:001676 cross-validation on
that output. See the 2026-10-20 verification log at the end.

Previous version: **2026-09-08**, after the lab meeting that settled the time base
(Q10–Q12, Q16) and after a full re-scan of DANDI:001676.

Earlier version: **2026-09-07**, after cross-validating the new raw session
`A0662 / 2022_08_29` against its DANDI:001676 counterpart
(`sub-A0662_ses-20220829T185721_behavior+ophys.nwb`).

---

## A. Resolved by the 2022-08-29 cross-validation (confirm only)

**R1** *(was Sync-Q2)* — The DANDI timestamps are hardware-derived from the Intan clock.
Every timestamp is an exact integer multiple of 50 µs (= 1 sample @ 20 kHz) — re-checked on
2026-09-08 across an 87-file sample (86 imaging + 87 behaviour series, 6 subjects).
Our independent decode reproduces them to **1–2 samples** (50–100 µs) across a 20-minute session.

*Updated 2026-10-20.* With the converter now using NeuroConv's detection (ADC-01 cut at its
midpoint, every transition), the raw imaging timestamps are the published ones **plus exactly
one sample (50 µs) on all 35 711 shared frames**, with no exceptions and no drift. ADC-00 rising
edges detected the same way match all 143 880 published behaviour timestamps exactly. The
offset is an edge-sample convention: NeuroConv assigns each transition to the first sample in
the new level, while the published imaging times use the last sample in the old level. The raw
conversion keeps NeuroConv's convention; see Q36.

**R2** *(was Sync-Q3)* — Channel assignment confirmed empirically:
ADC-00 = OptiTrack sync (0.5 ms TTL, one per tracking frame);
ADC-01 = Miniscope frame gate (square wave, **both** edges = one frame each).

**R3** — OptiTrack → NWB mapping is bit-exact:
`2D_position` = CSV `[Position X, Position Z]` (max abs diff **0.0**);
`head-direction` = `deg2rad(Rotation Y) mod 2π` (max abs diff **8.9e-16 rad**).

**R4** — The 24.638 Hz vs 29.785 Hz frame-rate difference is an acquisition setting
(`metaData.json` `"25FPS"` in July vs `"30FPS"` in August), not a decoding error.

---

## B. Time base — P1

**Q10 (P1)** — ✅ **ANSWERED (lab meeting, 2026-09-08).** Write the **Intan recording start**
as `session_start_time`. Since every timestamp is on the Intan clock, using the Miniscope
`metaData.json` wall clock would be wrong — it is a different clock (7 s earlier here) and may
just be a file-creation time. The RHD header has no date field, so the time comes from the Intan
directory name `{subject}_{YYMMDD}_{HHMMSS}`. Implemented in `convert_session.py`; the
2022-08-29 raw file now declares `2022-08-29T18:57:28-04:00`.
*Still open for the lab:* whether the published processed files should be corrected too, and
what to do for sessions whose Intan directory is not timestamped (the July ones).

*Updated 2026-10-20 (PR review).* The RHD-header lookup was removed: the header has no start
time and neo exposes none, so the time comes only from the directory name. A session whose
Intan directory is not timestamped (`A0662/2022_07_28`, directory `Intan/`) now **fails with a
`ValueError`** before anything is written, so the July sessions cannot be converted until the
lab gives another source for their Intan start time (or confirms they are excluded, Q9).

**Q11 (P2)** — ✅ The DANDI file writes `18:57:21.**000001**` where
`metaData.json` has `"msec": 1` (milliseconds written into the microsecond field). We no longer
read that field at all, so there is nothing to replicate. Still worth flagging to the lab as a
bug in the published files.

**Q12 (P1)** — ✅ **ANSWERED (lab meeting, 2026-09-08).** The raw file keeps **every** acquired
frame; it does not replicate the crop applied to the processed data (first 51 imaging frames
dropped, behaviour cut at the last imaging frame). We have the TTL frame gate, so each raw frame
gets its own hardware timestamp, and raw ↔ processed alignment happens through the shared Intan
clock rather than through matching frame indices. Verified: our frame 51 is the published
A0662/2022-08-29 asset's first imaging frame. With the NeuroConv decoder its timestamp is
`3.66355 s`, one sample after the published `3.6635 s` (see R1 and Q36).
Raw and processed frame indices therefore do **not** align 1:1, by design.

**Q13 (P2)** — ADC-01 produced **10 more gate edges than there are video frames** (35 772 vs 35 762).
Is the gate free-running past the end of the write, or were 10 frames dropped by the DAQ?
If frames were dropped, at which end — and can that happen mid-session?
*Current handling (2026-10-20):* all 35 772 transitions are stored in the `MiniscopeFrameGate`
events table, and the first 35 762 become the `OnePhotonSeries` timestamps. The 10 extra
transitions fall in the 0.37 s after the last frame, which fits a free-running gate, but only the
lab can confirm that no frames were dropped at the start.

**Q14 (P2)** — Symmetrically, ADC-00 produced **491 more edges than OptiTrack CSV rows**
(144 562 vs 144 071). Did Motive drop frames, or stop exporting early? Is `Frame` in the CSV
guaranteed to be a gap-free 1:1 index into the ADC-00 edge train?

**Q1 (P2)** — Why are `time.dat` and `analogin.dat` empty (0 bytes) for `A0662/2022_07_25`?
Upload problem, or was Intan not running? How was that session synchronised?

---

## C. OptiTrack / behaviour — P2

**Q15 (P2)** — Tracking rate varies across sessions (**120 Hz** and **100 Hz** both observed in
A0662). Deliberate? Are there other rates? *(Our decode is rate-agnostic — it reads the edges —
but the docs and `conversion_notes.md` currently say "120 Hz" everywhere.)*

**Q16 (P2)** — ✅ **ANSWERED (lab meeting, 2026-09-08).** Yes — publish all six rigid-body DOF.
The lab did not analyse `Position Y` (height), `Rotation X` (pitch) or `Rotation Z` (roll), which
is why the processed files carry only 2D position and head direction, but they may be useful to
others. `OptiTrackInterface` already reads and writes all six; wiring it into the converter and
aligning it to ADC-00 is scheduled for a **follow-up PR**.

**Q5 (P2)** — What is the rigid body physically attached to — the miniscope body, or a separate
head-mounted marker set? Is `Rotation Y` the animal's head direction or the scope's orientation,
and is there a fixed offset between them?

**Q17 (P3)** — `reference_frame` says "(0,0) is arbitrarily set around the center of the
environment". Is there a calibration we should record instead? What are the actual environment
geometries (circular arena diameter, square side, 8-arm maze dimensions, open field)?

---

## D. `scratch/` — cross-session cell registration — P1

**Q18 (P2)** *(largely settled — confirm only)* — **Column semantics.**
`scratch/Cell registration` is an `(n_registered_ROI, n_session)` int64 array; entry `[i, j]` is
the 0-based ROI index into **session j's** `PlaneSegmentation`, or −1.
Column `j` ↔ the session whose description reads "session j+1 of N", in chronological order.
Verified across all 72 A0662 sessions: the counter runs 1..N in strict date order within each
block, and every column's max ROI id is < that session's ROI count. The 2026-09-08 A0667 scan
confirms the same 1..N-in-date-order structure for all 75 of its files (see Q20). Confirm for
A0642 too — nothing in the files actually states it.

**Q19 (P1)** — **Nothing in the file identifies the other sessions.** A user reading one asset
cannot tell which 36 other assets the columns refer to. Can we add explicit session identifiers
(e.g. a `DynamicTable` with a session-id column) rather than relying on a free-text description?

**Q20 (P2)** *(partly answered)* — **The registration blocks are experimental phases.**
Mapping all 72 A0662 sessions shows three clean phases, each with its own CellReg table:

| Phase | Dates | n | CellReg | Protocol |
|-------|-------|---|---------|----------|
| 1 | 2022-08-29 → 2022-10-21 | 37 | 233 × 37 | **Blocked** — Circular ×10, Square ×7, 8-arm ×10, Open field ×10, in consecutive runs |
| 2 | 2022-10-24 → 2022-11-17 | 15 | 100 × 15 | **Weekly random order** — all 4 environments each week, order shuffled |
| 3 | 2022-11-21 → 2022-12-16 | 20 | 86 × 20 | **Circular only**, 20 consecutive sessions |

**A0667 — nothing is missing.** ✅ The earlier "19 + 40 = 59 vs 58 assets" discrepancy came from
an incomplete asset listing, not from the archive. A full re-scan of all 75 A0667 files
(2026-09-08) shows **three** registration blocks, not two, and every counter present:

| Block | Dates | n | CellReg | Protocol |
|-------|-------|---|---------|----------|
| 1 | 2022-11-22 → 2022-12-16 | 19 | 207 × 19 | Circular only |
| 2 | 2023-01-09 → 2023-03-03 | 40 | 183 × 40 | Blocked — Circular ×10, Square ×10, 8-arm ×10, Open field ×10 |
| 3 | 2023-03-06 → 2023-03-30 | 16 | 125 × 16 | Weekly random order — all 4 environments each week, order shuffled |

19 + 40 + 16 = **75 = the number of A0667 assets**, with `session j of N` running 1..N with no
gaps in any block. (The same scan also corrects the dataset-scale figures — see Q4.)

Remaining: confirm the phases and what each was testing, and why registration is redone per
phase rather than across the whole experiment.

**Q20b (P2)** — ❌ **WITHDRAWN — the claim was wrong.** I previously reported that
`general/experiment_description` reads *"2 consecutive weeks in each environment, for a total of
4 environments"* in all 72 A0662 files. Re-read directly from all 72 A0662 and all 75 A0667 files
(2026-09-08): the field is **already per-phase**, and every file's text matches its own phase:

| Phase type | `experiment_description` | A0662 | A0667 |
|---|---|---|---|
| Blocked | "2 consecutive weeks in each environment, for a total of 4 environments" | 37 files | 40 files |
| Circular only | "4 consecutive weeks in a circular environment" | 20 files | 19 files |
| Weekly random order | "4 environments are visited weekly in a random order, for 4 weeks" | 15 files | 16 files |

Each registration block carries exactly one description and no block mixes two, so the field
partitions the sessions the same way the CellReg tables do. The lab's metadata is right here.

Root cause: `docs/meeting-2026-09-07/inv.py`, the script that inventoried all 72 A0662 files,
collected `session_description`, `session_start_time`, `nroi`, `cellreg` and `age` — but never
`general/experiment_description`. The claim was generalised from the one session inspected by
hand (2022-08-29, which *is* in the blocked phase, where that text is correct) to all 72.

What survives of the question: the description is free text and does not *name* the phase, so a
user still cannot filter by protocol programmatically, and `session_description` remains the only
place the environment appears. Worth asking whether phase and environment should be proper
metadata fields — but this is an enhancement, not a correction.

**Q21 (P2)** — In the A0662 block-1 matrix, a large group of ROIs appears only from column ~16
onward. Is that a FOV shift, a re-registration, or something biological?

**Q22 (P2)** — Not every ROI in a session gets registered (e.g. column 10 has 54 entries but that
session has 59 ROIs). Is the unregistered remainder meaningful (new cells) or rejected?

**Q23 (P2, was P3)** — What exactly are `Cell registration scores`? The 0.09–1.00 / median 0.95
range quoted here earlier is one file's (A0662 phase 1). Across the 86 files sampled on
2026-09-08 the values run from **−1.239** to 1.000, with per-file medians spanning 0.705–0.992.
**Negative scores** rule out a plain `p_same` probability, so the question is sharper than it was:
what is the metric, what is its range, and what does a negative value mean?

**Q24 (P2)** — NWB's `scratch/` is explicitly documented as a place for working data that is
*not* intended for archival sharing. Cross-session registration is a genuinely useful result that
deserves a documented home. Options: a proper `DynamicTable` in `processing/ophys`, or a small
NWB extension. Does the lab want us to propose one?

---

## E. Processed-data provenance — P2

**Q25 (P1)** — **What is the transform from the 608×608 raw frame to the ROI mask grid?**
Masks are 285×285 for A0662/A0667 and 201×211 for A0642. Without the crop/downsample parameters
the ROI footprints cannot be placed back onto the raw video — which is the main scientific reason
to publish the raw data alongside the processed data.

**Q26 (P2)** — Which pipeline produced the segmentation and traces (CNMF-E? CaImAn?
Miniscope Analysis?), which version, and what parameters? Was motion correction applied, and are
the motion-correction shifts available? *(These would go in `processing/ophys` as
`MotionCorrection` / in the `PlaneSegmentation` description.)*

**Q27 (P2)** — `ΔF/F` has `unit: "arbitrary"`. How is F0 defined (percentile? rolling baseline?)?

**Q28 (P3)** — `processing/ophys/tuning_curves`: 120 HD bins per ROI. Occupancy-normalised?
Computed over the whole session or a subset? What are the `HD_bin` units (radians, bin centres)?

**Q29 (P3)** — `acquisition/miniscope_FOV` (285×285 float64) — is this a mean projection, a max
projection, or a single frame? From which session?
