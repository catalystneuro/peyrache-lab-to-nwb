# Peyrache Lab → NWB Conversion Notes

## Project Overview

**Lab**: Peyrache Lab, McGill University (PI: Adrien Peyrache)  
**GitHub repo**: https://github.com/catalystneuro/peyrache-lab-to-nwb  
**Conversion name**: `miniscope_arc`  
**Data source**: Google Drive → mounted at `~/source_data/peyrache-lab/`  
**Drive folder**: https://drive.google.com/drive/u/0/folders/1PEYVAdDfKJ4QaOsY7ivQCGnPNKsSTNTs  
**Date started**: 2026-08-04

**Related publication**: Skromne Carrasco, S., Viejo, G. & Peyrache, A. Months-long stability of the head-direction system. *Nature* 652, 167–173 (2026). doi:10.1038/s41586-026-XXXX  
**Existing processed data**: DANDI:001676 (includes DF/F traces, ROI footprints, CellReg registration, behavioral tracking, sync signals, session metadata)

---

## Aims

1. **Miniscope raw video conversion**: Implement `MiniscopeImagingInterface` for UCLA Miniscope V4 raw `.avi` files; append to existing DANDI:001676 sessions for provenance linking.
2. **NWB sleep extension**: Design and implement extension for sleep-specific data streams (EEG, sleep stage annotations, spindles, etc.) — separate from this miniscope_arc conversion.
3. **DANDI upload**: Raw Miniscope videos → DANDI:001676; sleep dataset → new embargoed Dandiset.
4. **Jupyter notebooks**: One for Miniscope streaming from DANDI:001676, one for sleep extension usage.

---

## Experiment Overview

SFARI Autism Rat Models Consortium (ARC) project. Rats implanted with UCLA Miniscope V4 for calcium imaging while freely exploring an arena. Behavioral position tracked via OptiTrack Motive 3D motion capture. Intan RHD system used for electrophysiology/sync acquisition. Sessions span months for longitudinal head-direction cell stability study.

---

## Directory Structure

```
{subject_id}/
└── {YYYY_MM_DD}/
    ├── Miniscope/
    │   ├── 0.avi, 1.avi, ... N.avi   # MJPEG video chunks, 2000 frames each
    │   ├── metaData.json              # Device config (frameRate, gain, LED, etc.)
    │   └── timeStamps.csv             # Per-frame timestamps (ms from DAQ start)
    ├── Intan/
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

**NeuroConv interface**: None available → **CUSTOM INTERFACE NEEDED** (`OptiTrackInterface`)

---

---

## Synchronization Analysis (Phase 4 — completed early from data inspection)

> **Analyzed session**: A0662 / 2022_07_28 (session 1 / 2022_07_25 has empty Intan files)

### Intan ADC Channels Identified

| Channel | ADC name | Signal | Frequency | Pulse width | Frames |
|---------|----------|--------|-----------|-------------|--------|
| Ch 0 (analogin col 0) | ADC-00 | **OptiTrack sync** | 120.01 Hz | 0.500 ms | 144,444 edges → 144,444/144,612 frames (99.88%) |
| Ch 1 (analogin col 1) | ADC-01 | **Miniscope frame gate** | 12.32 Hz (2-frame cycle) | 40.585 ms | 14,784 cycles × 2 = 29,568 frames (100%) |

### Channel 0 = OptiTrack TTL sync (120 Hz)

- 0.500 ms TTL pulse at 120 Hz — one pulse per OptiTrack frame
- `ch0_rising[k]` in Intan time → OptiTrack frame `k`
- **168 trailing tracking frames (1.40 s) have no Intan sync** — the OptiTrack kept running ~1.4 s after the Intan stopped

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
t =    2.091 s  Miniscope frame 0 (first Ch1 rising edge)
t =    3.458 s  OptiTrack frame 0 (first Ch0 rising edge)
t = 1201.878 s  Last Miniscope sync pulse (frame 29566)
t = 1207.098 s  Last synced OptiTrack frame (frame 144443)
t = 1207.908 s  Intan recording ends
(OptiTrack frames 144444–144611 run 1.4s past Intan end)
```

Overlap (all three systems active and synced): **3.46 – 1201.85 s (1198.4 s = ~20 min)**

### NWB mapping for synchronized timestamps

- `OnePhotonSeries.timestamps` = `miniscope_timestamps_intan` (Intan clock, seconds)
- `SpatialSeries.timestamps` (position) = `tracking_timestamps_intan` (Intan clock, seconds)
- `NWBFile.session_start_time` = Intan recording start (wall-clock time — need from lab)
- Do NOT use `OnePhotonSeries.rate` — use `timestamps` to capture real frame-rate variability

### Open sync questions

- [ ] **Sync-Q1**: Why is session 1 (2022_07_25) missing Intan data? How was it synchronized?
- [ ] **Sync-Q2**: What synchronization method was used for the PROCESSED data in DANDI:001676? Are our derived timestamps consistent with the existing NWB files?
- [ ] **Sync-Q3**: Is ADC-00 wired to the OptiTrack "sync out" port, and ADC-01 to the Miniscope DAQ "frame out"? (Or vice versa — to be confirmed with lab.)
- [ ] **Sync-Q4**: The 168 unsynced trailing tracking frames — should they be included with extrapolated timestamps (constant 120 Hz), or truncated at the last Intan edge?

---

## Interface Mapping

| Stream | Interface | source_data | Status |
|--------|-----------|-------------|--------|
| Miniscope video | `MiniscopeImagingInterface` | `folder_path=.../Miniscope` | Ready to test |
| Intan analog inputs | `IntanRecordingInterface` | `folder_path=.../Intan` | Needs verification (analog-only) |
| OptiTrack tracking | CUSTOM `OptiTrackInterface` | `file_path=.../Take*.csv` | Needs implementation |

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
- [x] **Q2**: What are the 2 analog input channels in Intan? → ADC-00 = OptiTrack sync (120 Hz TTL), ADC-01 = Miniscope frame gate (square wave). See Synchronization Analysis section.
- [ ] **Q3**: How do these sessions map to existing NWB files in DANDI:001676? What is the session naming convention used there?
- [ ] **Q4**: Total dataset scale — how many subjects and sessions in the full raw Miniscope dataset?
- [ ] **Q5**: Is the OptiTrack rigid body tracking head direction, body position, or both?
- [ ] **Q6**: Are there additional sessions/subjects not yet uploaded to Google Drive?
- [ ] **Q7**: Subject metadata for A0662 — species (Rattus norvegicus?), sex, date of birth, genotype, weight?
- [ ] **Q8**: Session timezone — what timezone were recordings made in? (likely America/Toronto for McGill)

---

## Phase Status

- [x] Phase 1: Experiment discovery — COMPLETE
- [x] Phase 2: Data inspection — COMPLETE
- [ ] Phase 3: Metadata collection — IN PROGRESS (open questions above)
- [x] Phase 4: Synchronization analysis — COMPLETE (analyzed during data inspection; open Sync-Q1 through Q4)
- [ ] Phase 5: Code generation
- [ ] Phase 6: Testing & validation
- [ ] Phase 7: DANDI upload
