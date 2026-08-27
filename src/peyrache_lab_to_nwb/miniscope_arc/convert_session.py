"""Convert a single Peyrache Lab miniscope_arc session to NWB."""

from __future__ import annotations

import warnings
from datetime import datetime
from pathlib import Path

from neuroconv.utils import dict_deep_update, load_dict_from_file

from peyrache_lab_to_nwb.miniscope_arc.constants import INTAN_ADC_STREAM, SESSION_TZ
from peyrache_lab_to_nwb.miniscope_arc.nwbconverter import MiniscopeArcNWBConverter

# TODO (open question Q3): confirm the session-ID convention against DANDI:001676
# before the first upload.  Current convention: "{subject_id}_{YYYY-MM-DD}"
# e.g. "A0662_2022-07-28".


def _intan_adc_is_valid(intan_dir: Path) -> bool:
    """Return True only when the Intan directory has non-empty ADC data files."""
    return (
        (intan_dir / "info.rhd").is_file()
        and (intan_dir / "time.dat").is_file()
        and (intan_dir / "analogin.dat").is_file()
        and (intan_dir / "time.dat").stat().st_size > 0
        and (intan_dir / "analogin.dat").stat().st_size > 0
    )


def session_to_nwb(
    session_dir_path: str | Path,
    output_dir_path: str | Path,
    stub_test: bool = False,
    overwrite: bool = True,
    verbose: bool = True,
) -> None:
    """Convert one raw session to NWB.

    Session directory layout expected::

        {session_dir_path}/
        ├── Miniscope/
        │   ├── 0.avi, 1.avi, …   # MJPEG video chunks (2 000 frames each)
        │   ├── metaData.json
        │   └── timeStamps.csv
        └── Intan/
            ├── info.rhd
            ├── time.dat           # int32 sample indices at 20 kHz
            └── analogin.dat       # uint16 ADC data (2 channels × N samples)

    The subject ID and session date are inferred from the directory structure::

        …/{subject_id}/{YYYY_MM_DD}/   →  subject_id="A0662", date="2022_07_28"

    Parameters
    ----------
    session_dir_path
        Path to the session directory (``YYYY_MM_DD``).
    output_dir_path
        Root directory for output NWB files.
    stub_test
        If ``True``, write only a short excerpt of each data stream to
        ``{output_dir_path}/nwb_stub/``.
    overwrite
        If ``True``, allow overwriting an existing output NWB file.
    verbose
        If ``True``, print progress information.
    """
    session_dir_path = Path(session_dir_path)
    output_dir_path = Path(output_dir_path)

    # Derive identifiers from directory structure
    session_date = session_dir_path.name       # "YYYY_MM_DD"
    subject_id = session_dir_path.parent.name  # e.g. "A0662"
    session_id = session_date.replace("_", "-")  # e.g. "2022-07-28"

    if stub_test:
        output_dir_path = output_dir_path / "nwb_stub"
    output_dir_path.mkdir(parents=True, exist_ok=True)
    nwbfile_path = output_dir_path / f"sub-{subject_id}_ses-{session_id}_desc-raw_ophys.nwb"
    if verbose:
        print(f"[new file] → {nwbfile_path}")

    # ------------------------------------------------------------------ #
    # Build source_data                                                   #
    # ------------------------------------------------------------------ #
    source_data: dict = {}
    conversion_options: dict = {}

    miniscope_dir = session_dir_path / "Miniscope"
    if miniscope_dir.is_dir():
        source_data["MiniscopeImaging"] = dict(folder_path=str(miniscope_dir))
        conversion_options["MiniscopeImaging"] = dict(stub_test=stub_test)
    elif verbose:
        print(f"Warning: no Miniscope directory found in {session_dir_path}")

    # Intan ADC channels — both stored together as TimeSeriesIntanSync in acquisition
    # and used for hardware-sync timestamp derivation.  Skipped when files are absent
    # or empty (e.g. session 2022_07_25); Miniscope then falls back to USB timestamps.
    intan_dir = session_dir_path / "Intan"
    if intan_dir.is_dir() and _intan_adc_is_valid(intan_dir):
        source_data["IntanSync"] = dict(
            file_path=str(intan_dir / "info.rhd"),
            stream_name=INTAN_ADC_STREAM,
            metadata_key="TimeSeriesIntanSync",
        )
    elif verbose:
        print(f"Warning: Intan ADC data absent or empty in {intan_dir} — falling back to USB timestamps.")

    # ------------------------------------------------------------------ #
    # Instantiate converter                                               #
    # ------------------------------------------------------------------ #
    converter = MiniscopeArcNWBConverter(source_data=source_data, verbose=verbose)

    # ------------------------------------------------------------------ #
    # Build metadata                                                      #
    # ------------------------------------------------------------------ #
    metadata = converter.get_metadata()

    # Layer 1: ensure session_start_time has timezone.
    # MiniscopeImagingInterface reads it from a session-level metaData.json that
    # the Peyrache lab data does not include, so fall back to midnight on the
    # recording date (YYYY_MM_DD directory name) in Eastern Time.
    start_time = metadata["NWBFile"].get("session_start_time")
    if start_time is None:
        y, m, d = session_date.split("_")
        start_time = datetime(int(y), int(m), int(d), tzinfo=SESSION_TZ)
    elif start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=SESSION_TZ)
    metadata["NWBFile"]["session_start_time"] = start_time

    # Layer 2: merge hand-edited lab-level metadata from YAML
    metadata_yaml_path = Path(__file__).parent / "metadata.yaml"
    editable_metadata = load_dict_from_file(metadata_yaml_path)
    metadata = dict_deep_update(metadata, editable_metadata, remove_repeats=False)

    # Layer 3: session-specific overrides
    metadata["NWBFile"]["session_id"] = session_id

    # dict_deep_update deduplicates identical floats in lists, collapsing
    # [0.0033, 0.0033] → [0.0033] (shape (1,) instead of the required (2,)).
    metadata["Ophys"]["ImagingPlane"][0]["grid_spacing"] = [0.0033, 0.0033]

    # Subject — subject_id is required by DANDI; other fields come from the YAML
    # TODO (open question Q7): fill in per-subject sex, date_of_birth, weight from lab records
    metadata["Subject"]["subject_id"] = subject_id

    # ------------------------------------------------------------------ #
    # Run conversion                                                      #
    # ------------------------------------------------------------------ #
    converter.run_conversion(
        nwbfile_path=nwbfile_path,
        metadata=metadata,
        conversion_options=conversion_options,
        overwrite=overwrite,
    )

    if verbose:
        print(f"Done → {nwbfile_path}")


if __name__ == "__main__":
    miniscope_folder_path = Path("/Users/weian/source_data/peyrache-lab-local/A0662/2022_07_28")
    nwb_folder_path = Path("/Users/weian/nwb_output/peyrache")

    session_to_nwb(
        session_dir_path=miniscope_folder_path,
        output_dir_path=nwb_folder_path,
        stub_test=True,
        verbose=True,
    )
