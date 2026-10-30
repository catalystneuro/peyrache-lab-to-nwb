# Peyrache Lab → NWB Conversion Notes

## Project Overview

**Lab**: Peyrache Lab, McGill University (PI: Adrien Peyrache)  
**GitHub repo**: https://github.com/catalystneuro/peyrache-lab-to-nwb  
**Conversion name**: `miniscope_arc`  
**Data source**: Google Drive → mounted at `~/source_data/peyrache-lab/`  
**Drive folder**: https://drive.google.com/drive/u/0/folders/1PEYVAdDfKJ4QaOsY7ivQCGnPNKsSTNTs  
**Date started**: 2026-08-04

**Related publication**: Skromne Carrasco, S., Viejo, G. & Peyrache, A. Months-long stability of the head-direction system. *Nature* 652, 167–173 (2026). doi:10.1038/s41586-025-10096-w  
**Existing processed data**: DANDI:001676 (includes DF/F traces, ROI footprints, CellReg registration, behavioral tracking, sync signals, session metadata)

---

## Aims

1. **Miniscope raw video conversion**: Implement `MiniscopeImagingInterface` for UCLA Miniscope V4 raw `.avi` files; append to existing DANDI:001676 sessions for provenance linking.
2. **NWB sleep extension**: Design and implement extension for sleep-specific data streams (EEG, sleep stage annotations, spindles, etc.) — separate from this miniscope_arc conversion.
3. **DANDI upload**: Raw Miniscope videos → DANDI:001676; sleep dataset → new embargoed Dandiset.
4. **Jupyter notebooks**: One for Miniscope streaming from DANDI:001676, one for sleep extension usage.

---

## Experiment Overview

Longitudinal recording of GCaMP6f-expressing cells in the **PostSubiculum** of freely-moving **C57BL/6J mice** (*Mus musculus*, male) using a UCLA Miniscope V4 one-photon fluorescence microscope. Mice explored different environments over several months to study the long-term stability of head-direction cell representations. Behavioural position tracked by OptiTrack Motive 3D motion capture. Intan RHD system used for hardware synchronisation.

---

## Directory Structure

```
{subject_id}/
└── {YYYY_MM_DD}/
    ├── Miniscope/
    │   ├── 0.avi, 1.avi, ... N.avi   # MJPEG video chunks, 2000 frames each
    │   ├── metaData.json              # Device config (frameRate, gain, LED, etc.)
    │   └── timeStamps.csv             # Per-frame timestamps (ms from DAQ start)
    ├── {subject}_{YYMMDD}_{HHMMSS}/   # named "Intan/" in the July sessions; when the
    │   │                              # name is timestamped it gives the recording start
    │   ├── info.rhd                   # Intan header (recording params, channel defs)
    │   ├── time.dat                   # Sample timestamps (int32, 20 kHz)
    │   └── analogin.dat               # Analog input data (uint16, 2 channels, 20 kHz)
    └── Tracking/
        └── Take {date} {time}.csv     # OptiTrack Motive export (rigid body, 120 FPS)
```

**Subjects visible in sample data**: A0662  
**Sessions**: 2022_07_25, 2022_07_28 (2 sessions for A0662 in sample)  
**Total dataset scale**: Unknown — needs confirmation from lab

---

## Data Streams — Detailed Inspection

### 1. Miniscope (Raw Video)

| Property | Value |
|----------|-------|
| Device | UCLA Miniscope V4 |
| Format | MJPEG-compressed .avi chunks |
| Acquisition software | Miniscope DAQ software (Windows, `F:/Miniscope/...`) |
| Frame rate | 25 FPS |
| Frames per file | 2000 |
| Electrowetting lens (EWL) | -78 |
| Gain | Medium |
| LED power (led0) | 33 |
| Session 1 frames | 29,564 (~1,199.9 s = ~20 min) |
| Session 2 frames | 29,568 (~1,199.7 s = ~20 min) |
| Compression | MJPG |

**Timestamps format** (`timeStamps.csv`):
- Columns: `Frame Number`, `Time Stamp (ms)`, `Buffer Index`
- Timestamps in milliseconds from DAQ start
- Frame 0 may have a small negative timestamp (~-38 ms) — slight pre-start offset

**Key insight**: Sessions start with a negative timestamp on frame 0 (e.g., -38 ms). This is a known quirk of the Miniscope DAQ and should be handled during conversion.

**NeuroConv interface**: `MiniscopeImagingInterface(folder_path=<path/to/Miniscope>)` ✓

```python
from neuroconv.datainterfaces import MiniscopeImagingInterface

interface = MiniscopeImagingInterface(
    folder_path="~/source_data/peyrache-lab/A0662/2022_07_25/Miniscope"
)
metadata = interface.get_metadata()
```

---

### 2. Intan (Electrophysiology / Sync)

| Property | Value |
|----------|-------|
| Hardware | Intan RHD2000 |
| Format | "One file per signal type" (info.rhd + .dat files) |
| Sample rate | 20,000 Hz |
| Bandwidth | 0.1 – 7,603.8 Hz |
| Amplifier channels | 0 (no neural recording) |
| Analog input channels | 2 channels (analogin.dat) |
| Timestamps | int32 (time.dat) |
| Data type | uint16 (analogin.dat) |

**Critical finding**: No amplifier (`amplifier.dat`) data — only 2 analog input channels (ADC-00, ADC-01). Both channels carry hardware synchronization TTL signals. Full characterization is in the **Synchronization Analysis** section below.

**Data issue — Session 1 (2022_07_25)**: Both `time.dat` and `analogin.dat` are **0 bytes**. Session 2 (2022_07_28) has proper data (~92 MB each, matching ~20 min at 20 kHz with 2 channels). This needs clarification from the lab — session 1 cannot be hardware-synchronized.

**NeuroConv interface**: `IntanRecordingInterface` handles analog-only recordings. To be tested in Phase 5.

---

### 3. Tracking (Behavioral)

| Property | Value |
|----------|-------|
| System | OptiTrack Motive |
| Format | OptiTrack CSV export v1.23 |
| Frame rate | 120 FPS |
| Rigid bodies | 1 ("RigidBody") |
| Data columns | Frame, Time (s), Rotation (Y, X, Z °), Position (X, Y, Z m) |
| Session 1 frames | 144,612 (~1,205 s = ~20 min) |
| Length units | Meters |
| Rotation type | YXZ Euler angles (degrees) |
| Capture start | 2022-07-25 02:28:38.728 PM |

**File naming**: `Take {YYYY-MM-DD} {HH.MM.SS AM/PM}.csv`  
The capture start time in the filename provides session wall-clock time, useful for synchronization.

**CSV structure**: Multi-row header (7 rows), then data rows with Frame + Time (s) + 6 data columns per rigid body (3 rotation + 3 position).

**NWB mapping**:
- `Position (X, Y, Z)` → `SpatialSeries` (units: meters, reference_frame: "OptiTrack global coordinate system")
- `Rotation (Y, X, Z)` → `TimeSeries` or `SpatialSeries` (units: degrees, Euler angles)
- Both stored in `nwbfile.processing["behavior"]`

**NeuroConv interface**: `OptiTrackInterface` (neuroconv#2085, https://github.com/catalystneuro/neuroconv/pull/2085), used since 2026-10-29. See *OptiTrack (added 2026-10-29)*.

---

---

## Synchronization Analysis (Phase 4 — completed early from data inspection)

> **Analyzed session**: A0662 / 2022_07_28 (session 1 / 2022_07_25 has empty Intan files)

### Intan ADC Channels Identified

| Channel | ADC name | Signal | Frequency | Pulse width | Frames |
|---------|----------|--------|-----------|-------------|--------|
| Ch 0 (analogin col 0) | ADC-00 | **OptiTrack sync** | 120.005 Hz | 0.500 ms | 144,444 rising edges (session 2022_07_28) |
| Ch 1 (analogin col 1) | ADC-01 | **Miniscope frame gate** | 12.32 Hz (2-frame cycle) | 40.585 ms | 14,784 cycles × 2 = 29,568 frames (100%) |

### Channel 0 = OptiTrack TTL sync (120 Hz)

- 0.500 ms TTL pulse at 120 Hz — one pulse per OptiTrack frame
- `ch0_rising[k]` in Intan time → OptiTrack frame `k`

```python
time_s = np.fromfile("time.dat", dtype=np.int32) / 20000.0
adc_v  = np.fromfile("analogin.dat", dtype=np.uint16).reshape(-1, 2) * (3.3 / 65535.0)
ch0_rising = np.where(np.diff((adc_v[:, 0] > 1.0).astype(np.int8)) == 1)[0]
tracking_timestamps_intan = time_s[ch0_rising]  # shape (144444,)
```

### Channel 1 = Miniscope frame gate (square wave, 2-frame period)

- **NOT** a simple one-pulse-per-frame signal. It is a square wave where one full cycle spans exactly 2 Miniscope frames:
  - Rising edge → start of even frame (0, 2, 4, …)
  - Falling edge → start of odd frame (1, 3, 5, …)
- Pulse width = 40.585 ms = one Miniscope frame period ✓
- 14,784 rising edges × 2 = 29,568 = exact Miniscope frame count — all frames accounted for

```python
ch1_above   = adc_v[:, 1] > 1.0
ch1_rising  = np.where(np.diff(ch1_above.astype(np.int8)) == 1)[0]
ch1_falling = np.where(np.diff(ch1_above.astype(np.int8)) == -1)[0]
n = min(len(ch1_rising), len(ch1_falling))
miniscope_timestamps_intan = np.empty(2 * n)
miniscope_timestamps_intan[0::2] = time_s[ch1_rising[:n]]   # even frames
miniscope_timestamps_intan[1::2] = time_s[ch1_falling[:n]]  # odd frames
```

### Critical: USB timestamps are unreliable

The Miniscope `timeStamps.csv` records frame arrival times on the USB bus, NOT actual camera exposure times. Comparison with the hardware Ch1 signal reveals:

| Metric | Value |
|--------|-------|
| Mean clock offset (Miniscope USB → Intan) | 2,119.8 ms |
| USB timestamp jitter std | **73.3 ms** |
| Max jitter | **235.7 ms** |

→ **USB timestamps are off by up to 236 ms.** They are unsuitable for precise synchronization. The Ch1 hardware sync is the authoritative source for Miniscope frame timing.

### Actual frame rates

| Stream | Nominal | Actual (from sync) |
|--------|---------|-------------------|
| Miniscope | 25 FPS | **24.638 FPS** |
| OptiTrack | 120 FPS | **120.01 Hz** |

The Miniscope runs ~1.4% below nominal rate. Do not use `rate=25.0` in the NWB `OnePhotonSeries` — use per-frame timestamps instead.

### Session timeline (session 2, Intan as master clock, t=0 = Intan start)

```
t =    0.000 s  Intan recording starts
t =    1.857 s  Miniscope frame 0 (first Ch1 rising edge)
t =    3.458 s  OptiTrack frame 0 (first Ch0 rising edge)
t = 1201.878 s  Last Miniscope sync pulse (frame 29566)
t = 1207.098 s  Last OptiTrack sync edge (edge 144443)
t = 1207.908 s  Intan recording ends
```

Overlap (all three systems active and synced): **3.46 – 1201.88 s (≈1198.4 s = ~20 min)**

### NWB mapping for synchronized timestamps

- `OnePhotonSeries.timestamps` = `miniscope_timestamps_intan` (Intan clock, seconds). The converter
  now gets these from NeuroConv's `IntanConverter` (ADC-01 cut at its midpoint, every transition),
  not from the 1.0 V `np.diff` decode shown above; see the 2026-10-20 cross-validation re-run.
- `SpatialSeries.timestamps` (position) = `tracking_timestamps_intan` (Intan clock, seconds)
- `NWBFile.session_start_time` = Intan recording start, read from the Intan directory name
  `{subject}_{YYMMDD}_{HHMMSS}` (the RHD header has no date field) — confirmed by the lab 2026-09-08
- Do NOT use `OnePhotonSeries.rate` — use `timestamps` to capture real frame-rate variability

### Open sync questions

- [ ] **Sync-Q1**: Why is session 1 (2022_07_25) missing Intan data? How was it synchronized?
- [x] **Sync-Q2**: What synchronization method was used for the PROCESSED data in DANDI:001676? Are our derived timestamps consistent with the existing NWB files? → Same Intan hardware sync; see *DANDI:001676 cross-validation*. Our imaging timestamps sat exactly one sample after DANDI's (re-run 2026-10-20); since 2026-10-29 they match exactly (see *Timestamp convention*), except in sessions with gate glitches (see *Frame timing on hold*).
- [x] **Sync-Q3**: Is ADC-00 wired to the OptiTrack "sync out" port, and ADC-01 to the Miniscope DAQ "frame out"? → Confirmed empirically by the DANDI comparison.

---

## DANDI:001676 cross-validation — A0662 / 2022-08-29  (added 2026-09-07)

### Result: our Intan decode reproduces the DANDI timestamps exactly

| Stream | n (ours) | n (DANDI) | max abs difference | in 20 kHz samples |
|--------|----------|-----------|--------------------|-------------------|
| Imaging (ADC-01, both edges) | 35 772 edges → 35 762 frames | 35 711 | **50 µs** | 1 sample |
| Behaviour (ADC-00, rising)   | 144 562 edges | 143 880 | **100 µs** | 2 samples |

The residual is a fixed ±1–2 sample edge-indexing convention (`np.diff` index vs. index+1),
not drift: the residual std is 0.7 µs over the full 20-minute session.

*(This table was produced with the earlier in-repo decoder: 1.0 V threshold, timestamp at the
last sample before each crossing. The branch now uses NeuroConv; see the re-run below.)*

### Re-run with NeuroConv's `IntanConverter` (2026-10-20)

Repeated on the full raw file written by the current converter
(`sub-A0662_ses-2022-08-29_desc-raw_ophys.nwb`), against the published asset
`sub-A0662/sub-A0662_ses-20220829T185721_behavior+ophys.nwb` (DANDI:001676 version
0.251205.2137, asset `7606bd39-d264-46bc-908b-4e1bbbac410f`). Imaging timestamps come from
`processing/ophys/Fluorescence/ROI_fluorescence` (identical to `DfOverF/ROI_dFF`); behaviour
timestamps from `acquisition/Position/2D_position` (identical to `head-direction`).

The lab's recipe below, applied to our output, gives the same counts as DANDI: frames from
index 51 on (35 711) and ADC-00 rising edges up to the last kept frame (143 880 of 144 562).

| Stream | Detection | n | Difference from DANDI, in 20 kHz samples |
|--------|-----------|---|------------------------------------------|
| Imaging, `OnePhotonSeries.timestamps` | ADC-01, `binarize: midpoint` (1.65 V), `value_change` | 35 711 | **+1 on every frame** (17 855 rising, 17 856 falling) |
| Imaging, earlier in-repo decoder | ADC-01, 1.0 V, last sample before crossing | 35 711 | 0 on 35 704 frames, −1 on 2, +1 on 5 |
| Behaviour (not yet written by the converter) | ADC-00, `binarize: midpoint`, `rising` | 143 880 | **0 on every sample** |

For this session the raw imaging timestamps are the published ones plus exactly one sample
(50 µs) on every shared frame, with no drift. Both files keep every timestamp on the 50 µs
sample grid.

### Timestamp convention: sample before the transition (decided 2026-10-29)

Each frame-gate edge completes between two consecutive Intan samples, so a decoder has to
assign it to either the last sample in the old level (k−1) or the first sample in the new level
(k). NeuroConv used k for every detection reading until catalystneuro/neuroconv#2133
(https://github.com/catalystneuro/neuroconv/pull/2133) added `event_time_convention` to the
detection specs. The published imaging timestamps correspond to k−1, while the published
behaviour timestamps correspond to k, which is why imaging showed the one-sample offset in the
2026-10-20 re-run and behaviour matched exactly.

`MINISCOPE_SYNC_DETECTION_SPEC` sets `"event_time_convention": "sample_before_transition"`,
so `OnePhotonSeries.timestamps` and `MiniscopeFrameGate` hold sample k−1 in every output file,
standalone or appended, and the frames the published traces cover carry exactly the published
timestamps. This replaces the earlier approach (2026-10-20), where standalone files kept sample k
and append mode measured the offset and shifted the frame times. The OptiTrack sync keeps the
default `sample_after_transition` (`OPTITRACK_SYNC_DETECTION_SPEC`; see *OptiTrack*).

**Checked on 13 sessions across four subjects (2026-10-29).** Frame times are the first `n_frames`
frame-gate transitions (`n_frames` = rows of `Miniscope/timeStamps.csv`), compared with
`ROI_fluorescence.timestamps` of the published asset. With `sample_before_transition` every shared
frame is bit-identical in every session; with the default every frame is one sample later.

| Session | Gate channel | Frames | Published | First shared frame | Identical |
|---|---|---|---|---|---|
| A0662/2022_08_29 | ADC-01 | 35 762 | 35 711 | 51 | yes |
| A0662/2022_10_03 | ADC-01 | 35 766 | 35 734 | 32 | yes |
| A0662/2022_11_14 | ADC-00 | 35 785 | 35 751 | 34 | yes |
| A0662/2022_12_09 | ADC-02 | 35 771 | 35 737 | 34 | yes |
| A0667/2022_11_22 | ADC-02 | 35 765 | 35 712 | 53 | yes |
| A0667/2023_02_02 | ADC-02 | 35 742 | 35 697 | 45 | yes |
| A0667/2023_03_30 | ADC-02 | 35 767 | 35 732 | 35 | yes |
| A0668/2022_11_22 | ADC-02 | 35 779 | 35 710 | 69 | yes |
| A0668/2023_02_02 | ADC-02 | 35 737 | 35 706 | 31 | yes |
| A0668/2023_03_30 | ADC-02 | 35 784 | 35 733 | 51 | yes |
| A0670/2022_11_22 | ADC-02 | 35 773 | 35 728 | 45 | yes |
| A0670/2023_01_09 | ADC-02 | 35 784 | 35 745 | 39 | yes |
| A0670/2023_03_30 | ADC-02 | 35 792 | 35 758 | 34 | yes |

A0642 was not checked here: its sessions are stored on the Drive only as ~10 GB zips with the
video. All 343 sessions with raw and published data were checked later; see *Frame timing on hold*.

### The frame-gate channel varies between sessions (found 2026-10-29)

The two ADC inputs are not always ADC-00 and ADC-01. The headers list ADC-00/ADC-01 (A0662 until
at least 2022-10-03), ADC-00/ADC-02, and ADC-02/ADC-07 (A0667 and A0668 on 2023-02-02), and the
signals are not always on the same input: on A0662/2022-11-14 the frame gate is ADC-00 and the
OptiTrack sync ADC-02. `_find_sync_channels` in `convert_session.py` therefore picks the frame gate
from the signal (the one ADC channel high between 25 % and 75 % of the time; the OptiTrack sync is
about 6 %) and stops if there are not exactly two ADC channels or not exactly one such channel. The
descriptions do not name the channels.

**Every DANDI timestamp in this Dandiset is an exact integer multiple of 50 µs** — i.e. an
Intan sample index at 20 kHz. Verified on 120 Hz and 100 Hz behaviour sessions alike, and
re-checked 2026-09-08 across an 87-file sample spanning 6 subjects (max deviation 6e-8 samples).

### Confirmed by this comparison

- **Sync-Q2 → RESOLVED.** The processed DANDI data uses the same hardware sync we derive.
- **Sync-Q3 → RESOLVED.** ADC-00 = OptiTrack (120 Hz TTL, 0.5 ms), ADC-01 = Miniscope frame
  gate (square wave, both edges). Channel assignment confirmed empirically for this session; other
  sessions use other inputs (see *The frame-gate channel varies between sessions*).
- **The DANDI time origin (t = 0) is the Intan recording start**, *not* the declared
  `session_start_time`. See open question Q10 — this is an inconsistency in the published files.

### The lab's frame-selection recipe (reverse-engineered, deterministic)

```
n_video   = number of AVI frames                       (35 762)
n_edges   = ADC-01 both-edge decode                    (35 772)   -> 10 surplus gate edges
imaging   = edges[:n_video]                                        # truncate to video
first     = first index i with imaging[i] >= tracking[0]  (i = 51) # crop to tracking window
imaging   = imaging[first:]                                        (35 711)  == DANDI
behaviour = tracking[tracking <= imaging[-1]]                      (143 880) == DANDI
```

Both counts match DANDI exactly. Note the two independent truncations:
- **10 surplus ADC-01 edges** — the frame gate keeps toggling ~0.34 s after the DAQ stops
  writing video. `temporally_align_data_interfaces` handles this (`gate_times[:n_frames]`).
- **51 leading imaging frames** dropped because they precede the first OptiTrack pulse.
- **682 trailing ADC-00 edges / 191 trailing CSV rows** dropped (OptiTrack outlives Intan+scope).

### OptiTrack → DANDI column mapping (bit-exact)

| DANDI object | Source | Transform | Agreement |
|--------------|--------|-----------|-----------|
| `acquisition/Position/2D_position` (N,2) | Motive CSV `Position X`, `Position Z` | none | **max abs diff = 0.0** |
| `acquisition/head-direction` (N,) | Motive CSV `Rotation Y` (yaw, degrees) | `deg2rad(x) mod 2*pi` | **max abs diff = 8.9e-16 rad** |
| *(not published)* | `Position Y` (height), `Rotation X` (pitch), `Rotation Z` (roll) | — | discarded by the lab |

### Frame-rate discrepancy explained

The July session runs at 24.638 Hz and every DANDI session at 29.785 Hz. This is **not** a
decoding error — it is an acquisition setting:

| Session | `Miniscope/metaData.json` `frameRate` | Actual (from ADC-01) | `ewl` | `led0` |
|---------|--------------------------------------|----------------------|-------|--------|
| 2022_07_28 | `"25FPS"` | 24.638 Hz | −78 | 33 |
| 2022_08_29 | `"30FPS"` | 29.785 Hz | 16 | 40 |

Both run ~1.4 % below nominal. Together with the fact that **2022-07-25 and 2022-07-28 are
absent from DANDI** (A0662 on DANDI starts 2022-08-29), this suggests the July sessions are
pilot//setup recordings rather than part of the published experiment — needs confirming (Q9).

### Experimental design recovered from DANDI (A0662, all 72 sessions)

Streaming every A0662 asset and parsing `session_description` + the `scratch` table shape gives
three phases, each with its own CellReg table:

| Phase | Dates | n | CellReg shape | Environments |
|-------|-------|---|---------------|--------------|
| 1 | 2022-08-29 → 2022-10-21 | 37 | 233 × 37 | Circular ×10, Square ×7, 8-arm ×10, Open field ×10 (blocked) |
| 2 | 2022-10-24 → 2022-11-17 | 15 | 100 × 15 | all four each week, order shuffled |
| 3 | 2022-11-21 → 2022-12-16 | 20 | 86 × 20 | Circular only |

Within every phase the "session k of N" counter runs 1..N in strict date order, which confirms
**CellReg column j ↔ session j+1 of that phase**.

Two metadata consequences:
- `general/experiment_description` is **per-phase and correct** — re-checked in all 72 A0662 files
  on 2026-09-08. Phase 1 reads "2 consecutive weeks in each environment, for a total of 4
  environments" (37 files), Phase 2 "4 environments are visited weekly in a random order, for 4
  weeks" (15), Phase 3 "4 consecutive weeks in a circular environment" (20); no block mixes two.
  *(An earlier note here claimed the Phase 1 text appeared in all 72 files — that was wrong.)*
- `Subject.age` runs P202D → P311D, giving **A0662 date of birth = 2022-02-08**, consistent
  across every file. The same derivation will work for A0642 and A0667.


---

## OptiTrack (added 2026-10-29)

The raw take is read with NeuroConv's `OptiTrackInterface`
(https://github.com/catalystneuro/neuroconv/pull/2085) and written to `processing/behavior` as
`PositionRigidBody` (X, Y, Z in meters) and `OrientationRigidBody` (Euler x, y, z in degrees, with
Motive's rotation order in the description). Untracked frames are NaN. Every session gets these
two names, also where Motive called the body `RigidBody01` (58 sessions), in
`session_to_nwb`. The in-repo `interfaces/optitrack_interface.py` was removed.

The OptiTrack sync is detected in the same `IntanConverter` call as the frame gate, on the other
ADC channel `_find_sync_channels` returns, with `OPTITRACK_SYNC_DETECTION_SPEC` (rising edges,
midpoint cut, first sample after the transition), and written as the `OptiTrackSync` events
table. `temporally_align_data_interfaces` sets take frame i to pulse i and stops if there are
fewer pulses than take frames. Motive keeps sending pulses while it is not recording, so every
session has more pulses than take frames (24 to 27 466 more). `session_start_time` stays the
Intan start; the take's `Capture Start Time` is not used.

In append mode the published `acquisition/Position/2D_position` and `acquisition/head-direction`
keep their values and timestamps. Their descriptions gain a sentence naming the raw series they
come from and saying that 0 marks an untracked frame (16 frames in 4 A0642 sessions:
2021-04-22, 04-23, 04-26, 04-27), and the position unit `m`, the only NWB Inspector finding on the
combined files, becomes `meters`. The raw series and `OptiTrackSync` are added beside them.

Open with the lab:
- In the 7 A0642 sessions exported with XZY rotation order (2021-05-31 to 2021-06-08), the
  published head direction is Rotation Y as in the YXZ sessions, which is not the same yaw.
- Should the published untracked frames stay 0?

---

## Frame timing on hold (2026-10-30)

Session counts. DANDI:001676 (version 0.251205.2137) has 406 assets: 402 imaging sessions of ten
mice and 4 electrophysiology sessions. Raw data is on the Drive for the five mice of this
conversion (A0642, A0662, A0667, A0668, A0670), which have 367 published imaging sessions. Of
these, 17 A0642 sessions (2021-05-20, 2021-06-18 and 15 between 2021-09-28 and 2021-10-21) have
no raw folder, and 7 A0642 raw zips are empty, leaving 343 sessions with both published and
readable raw data; every count below is out of these. Three raw A0662 sessions (2022-09-20 to
09-22) have no published file. The other five mice (A0671, A0676, A0678, A0682, A0683, 7 sessions
each) have no raw data on the Drive.

The converter times video frame i at frame-gate transition i, the rule that reproduces the
published imaging timestamps: they are a contiguous run of gate transitions in 324 of 343
sessions, and within one sample in 4 more. The other 15 have glitches in the gate (extra
transitions inside one frame period, e.g. 521 + 150 samples in A0668/2023-02-09, a burst of 7 in
A0667/2023-02-10); there the published timestamps are the gate transitions with the glitch
transitions removed, by a rule we could not infer. In these sessions the converter counts each
glitch transition as a frame, so its frame times fall one frame earlier than the published ones
for every glitch passed.

The Miniscope's USB timestamps also show frames missing from the video (2022-08-29 loses 10 at
frame 718), which neither the published timestamps nor this rule account for. A rule that drops
glitch transitions and skips the transitions of missing frames (`frame_times_from_gate`, with
tests) changes the frame times of 77 sessions, by up to 79 frames, and both video durations and
head-direction tuning favour it where the difference is 3 frames or more. It is kept in the git
stash "Precise frame alignment (frame_times_from_gate), held until the lab replies" until the lab
shares the code behind the published timestamps (asked 2026-10-30).

In 10 sessions the gate stops 1 to 8 frames before the video ends (A0642 2021-06-16, A0662
2022-10-27, A0667 2022-12-07, A0668 2022-11-23, 2023-03-13, 2023-03-23, A0670 2023-01-11,
2023-02-01, 2023-02-17, 2023-02-20). The published traces end at the last gate transition, and
the converter leaves out the frames after it too (verified on A0662/2022-10-27: 35 744 of 35 745
frames written, NWB Inspector clean).

---

## New Google Drive layout  (added 2026-09-07)

The newly shared session folder has a **different structure** from the July sample:

```
{session}/                                   # e.g. A0662/2022_08_29
├── metaData.json                            # NEW — Miniscope DAQ session metadata
├── notes.csv                                # NEW — 0 bytes in this session
├── Take 2022-08-29 06.57.31 PM.csv          # OptiTrack Motive export (11.2 MB)
├── experiment/                              # NEW — empty
├── Miniscope/
│   ├── 0.avi … 17.avi                       # 35 762 frames total, 608x608, MJPG
│   ├── metaData.json
│   └── timeStamps.csv                       # 35 762 rows (USB timestamps)
└── A0662_220829_185728/                     # <-- was "Intan/" in the July sample
    ├── info.rhd
    ├── time.dat        (96.8 MB, int32 @ 20 kHz -> 1210.5 s)
    └── analogin.dat    (96.8 MB, uint16, 2 ch)
```

Total: **700 MB / session**.

### Breaking change: the Intan directory is no longer called `Intan`

It is now `{subject}_{YYMMDD}_{HHMMSS}`. This is the lab's naming convention; an earlier
version of these notes called it the Intan software default, which was not checked and was
corrected in PR review.
`convert_session.py` used to look for a literal `Intan/` subdirectory, so on the new layout it
**silently skipped the sync interface and fell back to USB timestamps** — which we know are
off by up to 236 ms.

**Fixed (2026-09-08).** `_find_intan_dir()` now locates the directory by content
(`info.rhd` + `time.dat` + `analogin.dat`) rather than by name, preferring the timestamped
name when both it and a convenience `Intan` symlink are present — because that name is now
also the source of `session_start_time`. Still open: whether a missing Intan directory should
*raise* rather than warn (only the July sessions legitimately lack one).

### Top-level `metaData.json` — Miniscope DAQ clock, *not* the time origin

```json
{"animalName": "A0662", "researcherName": "Sofia,Guillaume",
 "year": 2022, "month": 8, "day": 29, "hour": 18, "minute": 57, "second": 21, "msec": 1,
 "msecSinceEpoch": 1661813841001}
```

This is the Miniscope DAQ wall clock — 18:57:21, seven seconds *before* the Intan recording
started (18:57:28, from the Intan directory name) — and may be a file-creation time rather
than an acquisition start. `MiniscopeImagingInterface` reports it as `session_start_time`, and
the published DANDI files declare it (as `18:57:21.000001`, `msec` written into the microsecond
field), even though all their timestamps are on the Intan clock.

**Decision (lab meeting, 2026-09-08): do not use it.** Every timestamp we write — imaging
frames, ADC traces, and later OptiTrack — is relative to the Intan clock, so
`session_start_time` must be the Intan recording start. See *Time base* below.

### Test run on the new session (2026-09-07)

`session_to_nwb(..., stub_test=True)` succeeded once `Intan/` was symlinked to
`A0662_220829_185728/`. Verified in the output:
- `OnePhotonSeries.timestamps` are 20 kHz-quantised and identical to a standalone decode.
- `TimeSeriesIntanSync` written with the full (24 210 720, 2) ADC array.
- `session_start_time` = `2022-08-29T18:57:21.001000-04:00` from `metaData.json`.
- `OptiTrackInterface` is **not** wired into `MiniscopeArcNWBConverter`, so the Take CSV was
  ignored — position and head direction are absent from our raw output.

### Re-run after the time-base change (2026-09-08)

The session directory is now found without the symlink, and the output declares
`session_start_time = 2022-08-29T18:57:28-04:00` (Intan start, from the directory name).
`TimeSeriesIntanSync` is unchanged at (24 210 720, 2). Alignment check against the published
asset: our **frame 51** carries timestamp `3.6635 s`, which is *exactly* the first imaging
timestamp in `sub-A0662_ses-20220829T185721_behavior+ophys.nwb` — the raw file keeps the 51
leading frames the lab dropped, and the shared Intan clock is what lines the two files up.
*(With NeuroConv's default convention frame 51 was at `3.66355 s`, one sample later; since
2026-10-29 the converter uses `sample_before_transition` and frame 51 is at `3.6635 s` again.)*

---

## Time base and truncation policy (lab meeting, 2026-09-08)

Everything in the raw file is on the **Intan clock**, and the raw file keeps everything that
was acquired. Alignment to the published processed files happens *through that clock*, not by
reproducing the lab's frame selection.

**1. `session_start_time` is the Intan recording start.**
`t = 0` is the first Intan sample, so the time origin has to be the moment Intan started.
The RHD header carries no date/time (format v1.5; the three note fields are empty, and neo
exposes nothing either), so the time is read from the Intan directory name
`{subject}_{YYMMDD}_{HHMMSS}` — `A0662_220829_185728` → `2022-08-29T18:57:28-04:00`.
The Miniscope DAQ `metaData.json` wall clock (18:57:21) is *not* used: it is a different clock,
7 s off here, and possibly a file-creation rather than an acquisition time.

*Updated 2026-10-20 (PR review):* the header lookup was removed, since neither the RHD format
nor neo provides a start time and NeuroConv would pick one up if that changed. Sessions with no
timestamped Intan directory (the July ones, `Intan/`) now **raise a `ValueError`** before
anything is written, so 2022_07_28 cannot be converted until its start time has another source.

**2. Miniscope frames are not truncated.**
The lab's processed files drop the 51 imaging frames that precede the first OptiTrack pulse and
cut behaviour at the last imaging frame. The raw conversion does **not** replicate that: every
acquired AVI frame is written, each with its hardware timestamp decoded from the ADC-01 frame
gate. Because both files sit on the same Intan clock, a user maps raw → processed by timestamp,
and nothing has to be inferred from frame indices. Verified on the A0662/2022-08-29 asset: our
frame 51 is the published file's first imaging frame, and it and every later frame carry
exactly the published timestamps (`sample_before_transition`, 2026-10-29).

The one trim that remains is the *surplus gate edges* — ADC-01 kept toggling for ~0.34 s after
the DAQ stopped writing video (35 772 edges vs 35 762 frames), so the decoded timestamp array is
cut to the frame count (`gate_times[:n_frames]` in `nwbconverter.py`). That discards timestamps
with no corresponding frame, not frames. The exception (2026-10-30): in 10 sessions the gate stops
1 to 8 frames before the video ends, and the frames after its last transition, which have no
time, are left out, as in the published traces (see *Frame timing on hold*).

**3. The sync traces are written in full.**
`TimeSeriesIntanSync` holds the complete `(n_samples, 2)` ADC array as acquired — both channels,
no truncation (the 2022-08-29 session writes all 24 210 720 samples). Anyone can re-derive the
frame times with a different threshold or edge convention. *Stub conversions (2026-10-20):*
`stub_test=True` now also shortens `TimeSeriesIntanSync`, passed to `IntanConverter` as
`{"AnalogADCInput": {"stub_test": True}}`; the frame-gate events are still detected over the
whole recording, so a stub keeps every `MiniscopeFrameGate` row.

**4. Publish all six OptiTrack DOF.**
The lab confirmed that `Position Y` (height), `Rotation X` (pitch) and `Rotation Z` (roll) should
be included even though they were not analysed and are absent from the processed files: they may
be useful to others. Done 2026-10-29 with NeuroConv's `OptiTrackInterface`, aligned to the
OptiTrack sync; see *OptiTrack*.

---

## Append mode: raw data added to a published DANDI:001676 file (2026-10-20)

`session_to_nwb(..., processed_nwbfile_path=...)` writes
`sub-{subject}_ses-{session_id}_behavior+ophys.nwb`: a copy of the session's published file with
the raw session added. Without `processed_nwbfile_path` it writes the standalone raw file as
before. Implementation: the private helpers at the end of `convert_session.py`.

**Mechanism** (since 2026-10-30). The published file is read with `read_nwb` and the checks
below run first. The published imaging plane and `1p Miniscope` device are removed, and
`MiniscopeArcNWBConverter.add_to_nwbfile` (after `temporally_align_data_interfaces`) adds the raw
session to the published file in memory, as it would to a new one: the raw imaging plane,
Miniscope device and device model, `OnePhotonSeries`, `TimeSeriesIntanSync`, `MiniscopeFrameGate`,
the raw OptiTrack series in a new `behavior` module, and `OptiTrackSync`. The published
`PlaneSegmentation` is relinked to the raw plane, the file-level and subject metadata are updated
from the conversion's metadata (below), NeuroConv's default backend configuration is applied, and
the result is exported to the new path. The published file is only read; no raw file is written
to disk. The export writes NWB 2.11.0 with the core, hdmf and ndx-miniscope schemas cached.
NeuroConv's `OptiTrackInterface` imports ndx-pose even when it writes no pose estimation, so
ndx-pose is cached too and PyNWB validation fails on it
(https://github.com/NeurodataWithoutBorders/pynwb/issues/1777); `_remove_unused_namespace` deletes
that unused spec from every output file until NeuroConv imports it only when needed.

Until 2026-10-30 the raw session was built as a separate in-memory file and its objects were
moved into the published one. The current version gives the same file (all 311 groups, datasets,
attributes and links compared on the 2022-08-29 stub), except that the published `2D_position`
and `head-direction` datasets are now gzip-compressed: their description and unit change marks
them modified, so the backend configuration covers them. Their values are unchanged.

NeuroConv's own append mode
(`run_conversion(append_on_disk_nwbfile=True)`) is not used: it modifies the file in place and can
only add objects, and here existing ones change.

**Checks before anything is written** (each stops it):
- the subject IDs match;
- the recording dates match (the published start time is the Miniscope DAQ clock and this
  conversion's the Intan clock, seconds apart, so only the date is compared);
- the published file has an imaging plane named `ImagingPlane`.

**Metadata.** This conversion's metadata is the truth, except where only the published file has
the information:

| Kept as published | From this conversion |
|---|---|
| `session_description`, appended verbatim on a line starting `Session:` (environment, "session k of N", the CellReg column) | `session_description` from `metadata.yaml` (the raw data) followed by `ProcessedSessionDescription` from `metadata.yaml` (the processed data); raw-only files get the first part alone |
| `experiment_description`, appended verbatim on a line starting `Protocol phase:` (per-phase protocol) | `experiment_description` from `metadata.yaml` |
| `Subject.age` (this conversion sets none) | `session_start_time`, `timestamps_reference_time` (Intan start) |
| all processed data: ROI masks and traces, CellReg tables, tuning curves, behaviour, FOV image | `identifier` (new UUID: a different file from the published asset) |
| | `session_id` (`YYYY-MM-DD`), `experimenter`, `related_publications`, `keywords`, `institution`, `lab`; every `Subject` field this conversion sets |
| | the raw `ImagingPlane` (AP/ML/DV `origin_coords` with `reference_frame`, `millimeters`, `Postsubiculum`, paper description, measured `imaging_rate`) and the ndx-miniscope `Miniscope` device with its DAQ settings and `DeviceModel` |

Changing `session_start_time` moves no timestamp: every published timestamp is already relative
to the Intan start (the published frame times are the Intan-clock times of the raw frames).

**Timestamps.** The frame times come from the frame gate with `sample_before_transition`
(see *Timestamp convention*), the same convention as the published imaging timestamps, so no
shift is applied. Until 2026-10-29 this step measured a one-sample offset and shifted
`OnePhotonSeries` and `MiniscopeFrameGate` by it. `TimeSeriesIntanSync` is stored as recorded.

**Verified on A0662/2022-08-29** (stub and full, 2026-10-21): the full conversion with
`processed_nwbfile_path` takes about 4 minutes, about the same as a standalone raw conversion,
and writes 4.9 GB. All published datasets other than the two descriptions are value-identical to
the source; frames 51 onward are bit-identical to the published ROI timestamps (then by a one-sample
shift; since 2026-10-29 directly); the device is ndx-miniscope `Miniscope`; all raw datasets are gzip.
NWB Inspector and `dandi validate` report only the published `2D_position` unit `m`.
Regenerated 2026-10-30 with the raw OptiTrack take and the `meters` unit: 4.9 GB, the frames from
51 on equal all 35 711 published ROI timestamps, the take times and position X, Z equal the
published behaviour, and NWB Inspector reports no issues.

**Verified on A0662/2022-11-14** (full, 2026-10-29), the first session with the frame gate on
ADC-00 and the OptiTrack sync on ADC-02. The combined file is 5.6 GB. `OnePhotonSeries` has 35 785
frames (the `timeStamps.csv` count), monotonic timestamps at 29.81 Hz, and frames 34 onward are
bit-identical to all 35 751 published ROI timestamps. `MiniscopeFrameGate` has 35 785 rows equal to
the frame times. Of the 46 published datasets, only the
ones this conversion replaces by design differ (file and subject metadata, imaging plane fields,
`identifier`, start and reference times), and only the `1p Miniscope` device and the old cached
schemas are gone. NWB Inspector and `dandi validate` report only the published `2D_position` unit `m`.
This file predates the OptiTrack additions and the fixed time zone, and has not been regenerated.

**Time zone (decided 2026-10-29).** Every published `session_start_time` (all 297 files of
A0662, A0667, A0668 and A0670) carries `-04:00`, including sessions between 2022-11-06 and
2023-03-12, when Montréal was on EST (`-05:00`). This conversion uses the same fixed `-04:00`
(`SESSION_TZ` in `constants.py`), so the combined files agree with the published start times.
The 2022-11-14 verification above ran with `America/Toronto` and wrote `10:14:44-05:00`.

**Batch.** `dataset_to_nwb(..., processed_dir_path=...)` gives each session the published
`sub-{subject}/sub-{subject}_ses-{YYYYMMDD}T*_*.nwb` (the `dandi download` layout) of the same
subject and date as `processed_nwbfile_path`, converts sessions without one to raw files, and
stops if a date has several.

---

## Interface Mapping

| Stream | Interface | source_data | NWB output | Status |
|--------|-----------|-------------|------------|--------|
| Miniscope video | `MiniscopeImagingInterface` | `folder_path=.../Miniscope` | `OnePhotonSeries` in acquisition | Implemented |
| Intan ADC inputs | `IntanConverter` (child `AnalogADCInput`) | `file_path=.../{subject}_{YYMMDD}_{HHMMSS}/info.rhd`, `detection_configuration` with `MINISCOPE_SYNC_DETECTION_SPEC` and `OPTITRACK_SYNC_DETECTION_SPEC` on the channels `_find_sync_channels` returns | `TimeSeriesIntanSync` in acquisition (metadata key `intan_adc_input`) | Implemented |
| Miniscope frame gate | `IntanConverter` (child `AnalogEvents`) | same entry: the frame-gate channel, `binarize: midpoint`, `value_change`, `sample_before_transition` | `MiniscopeFrameGate` `EventsTable` in `events`; row i is the time of video frame i (`OnePhotonSeries.timestamps`) | Implemented |
| OptiTrack sync | `IntanConverter` (child `AnalogEvents`) | same entry: the OptiTrack channel, `binarize: midpoint`, `rising` | `OptiTrackSync` `EventsTable` in `events`; the first `n` rows become the take's timestamps | Implemented |
| OptiTrack tracking | NeuroConv `OptiTrackInterface` | `file_path=.../Take*.csv` | `PositionRigidBody` (X, Y, Z, meters) + `OrientationRigidBody` (Euler x, y, z, degrees) in behavior | Implemented |

### Intan ADC — data provenance rationale

The raw ADC traces (`TimeSeriesIntanSync`) are stored in the NWB file rather than discarded after timestamp extraction. The two channels carry the hardware sync signals from which all inter-system timestamps are derived:

- OptiTrack frame sync (120 Hz TTL)
- Miniscope frame gate (square wave; rising = even frame, falling = odd frame)

Which ADC inputs carry them varies between sessions; see *The frame-gate channel varies between sessions*.

Storing the raw waveforms means any future user can independently verify or re-derive the per-frame timestamps with a different threshold or algorithm, without needing access to the original Intan recording. The signals compress extremely well in HDF5 (mostly flat with sharp transitions), adding only ~2–5 MB per session in practice.

---

## Data Source

- **Google Drive**: https://drive.google.com/drive/u/0/folders/1PEYVAdDfKJ4QaOsY7ivQCGnPNKsSTNTs
- **Mount command**:
  ```bash
  ~/.local/bin/rclone nfsmount "gdrive:" "$HOME/source_data/peyrache-lab" \
    --drive-root-folder-id="1PEYVAdDfKJ4QaOsY7ivQCGnPNKsSTNTs" \
    --read-only --vfs-cache-mode full --daemon
  ```

---

## Open Questions

- [ ] **Q1**: Why are `time.dat` and `analogin.dat` empty (0 bytes) for session 2022_07_25 but not 2022_07_28? Upload issue or intentional?
- [x] **Q2**: What are the 2 analog input channels in Intan? → OptiTrack sync (120 Hz TTL) and Miniscope frame gate (square wave), on inputs that vary between sessions. See *The frame-gate channel varies between sessions*.
- [x] **Q3**: How do these sessions map to existing NWB files in DANDI:001676? What is the session naming convention used there?
- [x] **Q4**: Total dataset scale — how many subjects and sessions in the full raw Miniscope dataset?
- [x] **Q5**: Is the OptiTrack rigid body tracking head direction, body position, or both?
- [ ] **Q6**: Are there additional sessions/subjects not yet uploaded to Google Drive?
- [x] **Q7** *(resolved 2026-08-12 from DANDI NWB stream)*: species=Mus musculus, genotype=C57BL/6J, sex=M, indicator=GCaMP6f. Per-subject date-of-birth / weight still needed from lab.
- [x] **Q8**: Session timezone — what timezone were recordings made in? → Fixed `-04:00`, as in the published files (decided 2026-10-29).

---

## Ophys Metadata Sourced from the Paper

Checked against Skromne Carrasco, Viejo & Peyrache, *Nature* 652, 167-173 (2026),
doi:10.1038/s41586-025-10096-w (Methods), 2026-09-10:

| Field | Value | Methods section |
|-------|-------|-----------------|
| `ImagingPlane.location` | `Postsubiculum` (Allen CCF term; was `PostSubiculum`, which fails the NWB Inspector CCF check) | "Stereotaxic GRIN lens implantation" |
| `ImagingPlane.origin_coords` | `[0.32, -2.35, -1.3]` mm in (AP, ML, DV) order | "Stereotaxic GRIN lens implantation" |
| `ImagingPlane.reference_frame` | AP +0.32 mm from lambda, ML -2.35 mm from midline (left), DV -1.3 mm from skull surface | "Stereotaxic GRIN lens implantation" |
| `ImagingPlane.description` | 1.0 mm GRIN lens (Inscopix); AAV2/9-SYN-GCaMP6f (Neurophotonics, batch 1357), 100-120 nl at 50 nl/min | "Viral vectors", "Stereotaxic injections" |
| `NWBFile.related_publications` | `doi:10.1038/s41586-025-10096-w` (replaced the bioRxiv preprint DOI) | — |

**`origin_coords` order — resolved 2026-09-10, deliberately diverges from DANDI:001676.**
This file stores `[0.32, -2.35, -1.3]` in **(AP, ML, DV)** order. The published DANDI:001676
file appears to store ML first (`[-2.35, 0.32, -1.3]`), which is where the earlier value here
came from.

The NWB `ImagingPlane` spec (`nwb.ophys.yaml`) declares `origin_coords` dims as `x, y, z` and
mandates no anatomical order; `reference_frame` is the field that "is necessary to interpret
origin_coords", and the spec's own worked example uses AP, then ML, then DV. So (AP, ML, DV)
plus an explicit `reference_frame` is the documented convention, and it is also the order the
paper states. An ML-first array with no `reference_frame` is not interpretable at all, so it was
not treated as the value to match.

If the processed DANDI files are ever re-converted, they should be corrected the same way
rather than this file being changed back.

**Still to confirm with the lab:** `Subject.genotype` is set to `C57BL/6J`, which is a strain
rather than a genotype. The paper describes wild-type C57BL/6J mice injected with AAV, so
this most likely belongs in `Subject.strain` with `genotype` left unset.

---

## Ophys Metadata Format

`metadata.yaml` uses NeuroConv's dict-based metadata format (neuroconv >= 0.10), which keys
each entry by name instead of by list position:

- `Devices["miniscope"]` — the instrument, named from the Miniscope DAQ `metaData.json`
  (`deviceName`). Its per-session configuration (frame rate, gain, LED power, EWL) is written
  by `MiniscopeImagingInterface` from the same file; only the link to the model is set by hand.
- `DeviceModels["miniscope_v4"]` — the hardware design (`deviceType: Miniscope_V4`), carrying
  the manufacturer, model number and description. pynwb 4 deprecated `Device.manufacturer`,
  `Device.model_name` and `Device.model_number` in favor of this linked `DeviceModel`, so the
  make of the scope belongs here, shared by every session recorded on it.
- `Ophys["ImagingPlanes"]["miniscope_imaging"]` / `Ophys["MicroscopySeries"]["miniscope_imaging"]`
  — keyed by the interface's `metadata_key`; the plane points at the device with
  `device_metadata_key`, the series at the plane with `imaging_plane_metadata_key`.

The old list-based format (`Ophys["Device"]`, `Ophys["ImagingPlane"]`, `Ophys["OnePhotonSeries"]`)
is deprecated and, under neuroconv 0.10, silently loses the hand-written imaging-plane fields
(the file gets a `PlaceholderMicroscope` with `excitation_lambda: nan`), so it must not be used.

---

## Phase Status

- [x] Phase 1: Experiment discovery — COMPLETE
- [x] Phase 2: Data inspection — COMPLETE
- [x] Phase 3: Metadata collection — COMPLETE (ophys metadata confirmed from DANDI:001676 NWB stream 2026-08-12; per-subject DoB/weight pending from lab)
- [x] Phase 4: Synchronization analysis — COMPLETE (analyzed during data inspection; open Sync-Q1 through Q4)
- [x] Phase 5: Code generation
- [ ] Phase 6: Testing & validation
- [ ] Phase 7: DANDI upload
