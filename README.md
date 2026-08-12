# peyrache-lab-to-nwb

NWB conversion scripts for the [Peyrache Lab](https://www.peyrachelab.com/)
(McGill University) data, using
[NeuroConv](https://github.com/catalystneuro/neuroconv).

Related publication: Skromne Carrasco, S., Viejo, G. & Peyrache, A.
*Months-long stability of the head-direction system.*
doi: [10.1101/2024.06.13.598909](https://doi.org/10.1101/2024.06.13.598909)

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
| OptiTrack tracking (CSV) | `OptiTrackInterface` (custom) | `Position` + `body_rotation_euler_yxz` in behavior |
| Intan sync channels (ADC) | *(decode-only, not stored)* | provides hardware timestamps |

**Synchronisation:** Intan RHD analog inputs carry two TTL signals that
hardware-stamp every Miniscope frame and every OptiTrack frame.
`MiniscopeArcNWBConverter.temporally_align_data_interfaces()` decodes these
pulses and replaces the Miniscope USB timestamps (which drift up to 236 ms
over a 20-minute session) with precise hardware timestamps.

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

### Single session — new NWB file

```python
from peyrache_lab_to_nwb.miniscope_arc.miniscope_arc_convert_session import session_to_nwb
from pathlib import Path

session_to_nwb(
    session_dir_path=Path("~/source_data/peyrache-lab/A0662/2022_07_28"),
    output_dir_path=Path("~/nwb_output/peyrache"),
    stub_test=True,   # set False for full conversion
    verbose=True,
)
```

### Append raw Miniscope video to an existing DANDI:001676 file

```python
# 1. Download the existing file from DANDI (requires dandi CLI)
#    dandi download "https://api.dandiarchive.org/api/assets/<asset-id>/download/"

# 2. Append raw video
session_to_nwb(
    session_dir_path=Path("~/source_data/peyrache-lab/A0662/2022_07_28"),
    output_dir_path=Path("~/nwb_output"),   # ignored in append mode
    append_to_nwb_path=Path("~/downloads/sub-A0662_ses-20220728.nwb"),
    verbose=True,
)

# 3. Re-upload with dandi CLI
#    dandi upload ~/downloads/sub-A0662_ses-20220728.nwb --dandiset 001676
```

### All sessions

```python
from peyrache_lab_to_nwb.miniscope_arc.miniscope_arc_convert_all_sessions import dataset_to_nwb

dataset_to_nwb(
    data_dir_path=Path("~/source_data/peyrache-lab"),
    output_dir_path=Path("~/nwb_output/peyrache"),
    max_workers=4,
    stub_test=False,
)
```

---

## Data source

Raw data are on Google Drive.  Mount with rclone:

```bash
~/.local/bin/rclone nfsmount "gdrive:" "$HOME/source_data/peyrache-lab" \
  --drive-root-folder-id="1PEYVAdDfKJ4QaOsY7ivQCGnPNKsSTNTs" \
  --read-only --vfs-cache-mode full --daemon
```
