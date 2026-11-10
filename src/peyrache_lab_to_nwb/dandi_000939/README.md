# dandi_000939: HED annotation of sleep states

Adds machine-readable definitions of the sleep states to the published NWB files of
[DANDI:000939](https://dandiarchive.org/dandiset/000939/0.261016.2310), "Large-scale recordings of head
direction cells in mouse postsubiculum" (Duszkiewicz et al., Nature Neuroscience 2024,
doi:[10.1038/s41593-024-01588-5](https://doi.org/10.1038/s41593-024-01588-5)).

The published files store sleep scoring in `/intervals/sleep_states`, a `TimeIntervals` table with one row
per continuous period of one state. Its `state` column holds `wake`, `nrem` or `rem`. This conversion
downloads a session, reads it, adds the following objects, and exports the result to a new file with the
same name:

| Object | Location in the file | Content |
|---|---|---|
| `HedLabMetaData` (ndx-hed) | `/general/hed_schema` | HED schema versions `["8.4.0", "sc:score_2.1.0"]` |
| `MeaningsTable` | `/intervals/sleep_states/meanings_tables/state_meanings` | One row per state: `value`, `meaning`, `HED` |
| HERD | `/general/external_resources` | Each state linked to a Neuro Behavior Ontology term |

The `sleep_states` columns and rows and all other data are copied unchanged, so code that reads the file
keeps working.

The MeaningsTable is named `state_meanings` because hdmf-common names a MeaningsTable after the column it
describes (`{column}_meanings`).

## Annotations

The HED tags follow the proposed NWB best practice for sleep states,
https://github.com/NeurodataWithoutBorders/nwbinspector/pull/775 (open as of 2026-11-10).

| state | meaning | HED | ontology term |
|---|---|---|---|
| `wake` | Wakefulness. | `Awake` | [NBO:0000066](http://purl.obolibrary.org/obo/NBO_0000066) wakefulness |
| `nrem` | Non-rapid eye movement (NREM) sleep. | `Asleep` | [NBO:0000161](http://purl.obolibrary.org/obo/NBO_0000161) non-rapid eye movement sleep behavior |
| `rem` | Rapid eye movement (REM) sleep. | `Asleep, sc:Sleep-stage-REM` | [NBO:0000159](http://purl.obolibrary.org/obo/NBO_0000159) rapid eye movement sleep |

The standard HED schema has `Awake` and `Asleep` but no NREM or REM tag. REM comes from the SCORE library
(prefix `sc:`). NREM is tagged `Asleep` alone because the lab scored it as one state, not as the human
stages N1 to N3.

The MeaningsTable description records the scoring method: the automated SleepScoreMaster algorithm, then
manual checking in TheStateEditor (Buzsaki lab), using LFP and a pseudo-EMG derived from correlated
high-frequency activity across probe channels.

All of this is set in `metadata.yaml`.

## Files

| File | Purpose |
|---|---|
| `metadata.yaml` | Dandiset version, HED schema versions, and the meaning, HED and ontology term of each state |
| `convert_session.py` | `session_to_nwb`: download one session and export the annotated file |
| `convert_all_sessions.py` | `dataset_to_nwb`: run `session_to_nwb` on every session |
| `notebooks/sleep_states_hed_demo.ipynb` | Runs the conversion on one session and shows the result |

## Installation

This conversion has its own environment, separate from the DANDI:001676 conversion. From the repository root:

```bash
uv venv .venv-dandi-000939
source .venv-dandi-000939/bin/activate
uv pip install -e ".[dandi_000939]"
```

This installs `ndx-hed` 0.3.0, which requires `pynwb>=4.2.0` and `hdmf>=6.2.0`, the DANDI client, h5py and
PyYAML.

## Usage

One session:

```python
from pathlib import Path

from peyrache_lab_to_nwb.dandi_000939.convert_session import session_to_nwb

session_to_nwb(
    asset_path="sub-A1821/sub-A1821_ses-190910_behavior+ecephys+ogen.nwb",
    output_dir_path=Path("~/nwb_output/dandi_000939").expanduser(),
    download_dir_path=Path("~/source_data/dandi/000939").expanduser(),
)
```

All 31 sessions:

```python
from peyrache_lab_to_nwb.dandi_000939.convert_all_sessions import dataset_to_nwb

dataset_to_nwb(
    output_dir_path="/Volumes/T9/nwb_output/dandi_000939",
    download_dir_path="/Volumes/T9/source_data/dandi/000939",
)
```

Both write the annotated files in the Dandiset layout, `{output_dir_path}/sub-{subject}/{file name}`, with
the published file names. The published file is downloaded to `{download_dir_path}/{asset_path}`, reused
if it is already there with the right size, and never modified.

The published files are 12.7 to 30.2 GB each, about 730 GB for all 31. The export is a full copy with the
same chunking and compression, so the annotated files need another 730 GB. The download of a session can be
deleted once its export is written. The export of sub-A1821 (23.6 GB) took 30 s on an external SSD.

`dataset_to_nwb` skips sessions whose annotated file already exists (pass `overwrite=True` to redo them). A
session that fails writes its traceback to `{output_dir_path}/ERROR_{file name}.txt`, and the others
continue.

## Cached schemas

An NWB file caches the schemas it was written with under `/specifications`. The published files cache core
2.9.0, hdmf-common 1.8.0 and hdmf-experimental 0.5.0. `MeaningsTable` needs hdmf-common 1.10.0.

Appending to the published file in place would cache core 2.11.0, hdmf-common 1.10.0, hdmf-experimental
0.6.0 and ndx-hed 0.3.0 next to the old versions. With two core versions cached, tools that read the cached
schemas (PyNWB's validator, NWB Inspector, `dandi validate`) fail with
`No specification for 'DurationVectorData' in namespace 'ndx-hed'`, because ndx-hed depends on `core`
without a version and the loader resolves it to 2.9.0.

Exporting writes a new file that caches only the current versions and sets `nwb_version` to 2.11.0, so the
file loads in these tools.

## Validation

Checked on sub-A1821 (2026-11-10):

- `HedNWBValidator` (ndx-hed): no issues. `session_to_nwb` raises if the HED annotations do not validate.
- `python -m pynwb.validation_cli`: no errors.
- `nwbinspector --config dandi`: three best practice suggestions (electrode `x`, `y`, `z` columns are all
  NaN), the same as for the published file.
- All 72 datasets of the published file are in the export with the same values (small datasets compared
  in full, the three large ones on 50 chunks spread over the recording plus the end), with no links to the
  published file.

Tests: `pytest tests/test_dandi_000939.py`.

## Upload

The annotated files would replace the published ones in a new version of DANDI:000939. Confirm with the lab
before uploading, and decide whether the upload goes to the DANDI sandbox or the production archive.
