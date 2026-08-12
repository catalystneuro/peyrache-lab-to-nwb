# Open Questions

Questions that need lab input before the conversion can be finalized or uploaded to DANDI.

---

## Session / data

**Q1** — Why are `time.dat` and `analogin.dat` empty (0 bytes) for session `A0662/2022_07_25` but present for `2022_07_28`? Upload issue or intentional? How was that session synchronized?

**Q3** — How do the raw sessions map to the existing NWB files in DANDI:001676? What session-ID convention is used there? (Current assumption: `{subject_id}_{YYYY_MM_DD}`, e.g. `A0662_2022_07_28` — needs confirmation before upload.)

**Q4** — Total dataset scale: how many subjects and sessions exist in the full raw Miniscope dataset? Are there additional subjects/sessions not yet on Google Drive?

---

## Synchronisation

**Sync-Q3** — Channel assignment confirmation: is ADC-00 wired to the OptiTrack "sync out" port and ADC-01 to the Miniscope DAQ "frame out"? (Analysis is consistent with this, but lab confirmation needed.)

**Sync-Q4** — The 168 trailing OptiTrack frames (≈1.4 s) after the last Intan sync pulse: should they be included with extrapolated 120 Hz timestamps, or truncated? Currently truncated.

**Sync-Q2** — What synchronisation method was used for the already-processed data in DANDI:001676? Are the hardware-derived timestamps from our Intan sync analysis consistent with the existing NWB files?

---

## Subject metadata

**Q7** *(partially resolved — confirmed from DANDI:001676 NWB files 2026-08-12)* — Species: `Mus musculus`. Genotype: `C57BL/6J`. Sex: `M`. GCaMP variant: `GCaMP6f`. Example subject A0642 has age `P243D`. Outstanding: confirm per-subject date-of-birth / age-at-recording and weight from lab records so per-session `age` can be set in `convert_session.py`.

**Q8** — Session timezone confirmed as `America/Toronto` (McGill, Montréal)?

---

## Experimental setup

**Q5** — Does the OptiTrack rigid body track head direction, body position, or both? Which physical marker/attachment is it tracking?

**Q6** *(resolved — confirmed from DANDI:001676 NWB files 2026-08-12)* — Excitation wavelength: `470.0 nm`. Emission wavelength (GreenChannel): `525.0 nm`. Both are stored in the existing NWB ImagingPlane and now in `metadata.yaml`.
