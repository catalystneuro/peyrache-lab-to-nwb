# peyrache-lab-to-nwb

NWB conversion scripts for the [Peyrache Lab](https://www.peyrachelab.com/)
(McGill University) data, using
[NeuroConv](https://github.com/catalystneuro/neuroconv).

Related publication: Skromne Carrasco, S., Viejo, G. & Peyrache, A.
*Months-long stability of the head-direction system.*
doi: [10.1038/s41586-025-10096-w](https://doi.org/10.1038/s41586-025-10096-w)

Processed dataset: [DANDI:001676](https://dandiarchive.org/dandiset/001676/0.251205.2137)

---

## Conversions

### `miniscope_arc`

Converts raw UCLA Miniscope V4 calcium imaging and OptiTrack 3-D motion capture
data from the SFARI ARC longitudinal head-direction study.

**Data streams:**

| Stream | Interface | NWB output |
|--------|-----------|------------|
| Miniscope raw video (MJPEG .avi) | `MiniscopeImagingInterface` | `OnePhotonSeries` in acquisition |
| OptiTrack tracking (Motive `Take` CSV) | NeuroConv `OptiTrackInterface` | `PositionRigidBody` + `OrientationRigidBody` in behavior |
| Intan sync channels (ADC) | `IntanConverter` | `TimeSeriesIntanSync` in acquisition |
| Miniscope frame gate (Intan ADC input, found per session) | `IntanConverter` (analog events) | `MiniscopeFrameGate` events table; provides hardware timestamps |
| OptiTrack sync (the other Intan ADC input) | `IntanConverter` (analog events) | `OptiTrackSync` events table; provides hardware timestamps |

**Synchronisation:** Intan RHD analog inputs carry two TTL signals that
hardware-stamp every Miniscope frame and every OptiTrack frame.
`MiniscopeArcNWBConverter.temporally_align_data_interfaces()` reads the
frame-gate transitions and OptiTrack sync pulses detected by NeuroConv's `IntanConverter`
and replaces the Miniscope USB timestamps (which drift up to 236 ms over a
20-minute session) and the Motive frame times with hardware timestamps. Video frame i is
frame-gate transition i, with transitions detected by the lab's own rule
(`frame_gate_samples`, from [gviejo/PSBImaging](https://github.com/gviejo/PSBImaging/blob/main/python/wrappers.py)),
which drops glitch transitions and reproduces the published imaging timestamps. Frames missing
from the video are not accounted for, as in the published files. Take frame i is OptiTrack pulse i.

---

## Installation

```bash
git clone https://github.com/catalystneuro/peyrache-lab-to-nwb.git
cd peyrache-lab-to-nwb

uv venv
source .venv/bin/activate
uv pip install -e .
```

---

## Usage

### Single session — raw file

```python
from pathlib import Path

from peyrache_lab_to_nwb.miniscope_arc.convert_session import session_to_nwb

session_to_nwb(
    session_dir_path=Path("~/source_data/peyrache-lab/A0662/2022_11_14").expanduser(),
    output_dir_path=Path("~/nwb_output/peyrache").expanduser(),
    stub_test=True,  # set False for full conversion
    verbose=True,
)
```

Writes `sub-A0662_ses-2022-11-14_behavior+ophys.nwb`, the same name a combined file gets. The session start time is read from the
Intan directory name (`{subject}_{YYMMDD}_{HHMMSS}`), so sessions whose Intan directory is
called `Intan/` (the July 2022 sessions) raise an error.

### Single session — raw data added to its DANDI:001676 file

```bash
dandi download "https://api.dandiarchive.org/api/assets/7606bd39-d264-46bc-908b-4e1bbbac410f/download/" \
  -o ~/source_data/dandi/001676/sub-A0662
```

```python
session_to_nwb(
    session_dir_path=Path("~/source_data/peyrache-lab/A0662/2022_11_14").expanduser(),
    output_dir_path=Path("~/nwb_output/peyrache").expanduser(),
    processed_nwbfile_path=Path(
        "~/source_data/dandi/001676/sub-A0662/sub-A0662_ses-20221114T101446_behavior+ophys.nwb"
    ).expanduser(),
    verbose=True,
)
```

Writes `sub-A0662_ses-2022-11-14_behavior+ophys.nwb`; the downloaded file is only read. The raw
session is built in memory and added to a copy of the published file, which keeps its processed
data unchanged and gains the raw video, `TimeSeriesIntanSync`, `MiniscopeFrameGate`, the raw
OptiTrack take in `processing/behavior` with `OptiTrackSync`, and this conversion's imaging plane
and Miniscope device. The published `Position/2D_position` and `head-direction` keep their values
and timestamps; their descriptions name the raw series they come from, and the position unit
becomes `meters`. This conversion's metadata replaces the
published file-level and subject metadata. The session description from `metadata.yaml` (the
raw data) is extended with `ProcessedSessionDescription` and followed by the published one on a
line starting `Session:`, and the experiment description by
the published protocol on a line starting `Protocol phase:`; `Subject.age` is kept as published.
Frame-gate transitions and OptiTrack sync pulses are detected with the lab's own rule, as in the
published files, so the raw frames the ROI traces cover carry the published ROI timestamps and the
raw take carries the published behaviour timestamps. Like the published timestamps, this does not
account for frames dropped from the video; `dataset_to_nwb` leaves out the sessions listed in
`sessions_on_hold.py` unless `include_sessions_on_hold=True`. See `conversion_notes.md`,
*Append mode* and *Frame timing on hold*.

Run NWB Inspector and `dandi validate` on the result before any upload.

### All sessions

```python
from peyrache_lab_to_nwb.miniscope_arc.convert_all_sessions import dataset_to_nwb

dataset_to_nwb(
    data_dir_path=Path("~/source_data/peyrache-lab").expanduser(),
    output_dir_path=Path("~/nwb_output/peyrache").expanduser(),
    processed_dir_path=Path("~/source_data/dandi/001676").expanduser(),  # optional
    max_workers=4,
    stub_test=False,
)
```

With `processed_dir_path`, each session whose published file
(`sub-{subject}/sub-{subject}_ses-{YYYYMMDD}T*_*.nwb`, same subject and date) exists is added to
a copy of it; the others are written as raw files.

---

## Data source

Raw data are on Google Drive.  Mount with rclone:

```bash
~/.local/bin/rclone nfsmount "gdrive:" "$HOME/source_data/peyrache-lab" \
  --drive-root-folder-id="1PEYVAdDfKJ4QaOsY7ivQCGnPNKsSTNTs" \
  --read-only --vfs-cache-mode full --daemon
```
