"""Convert a single Peyrache Lab miniscope_arc session to NWB."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from neuroconv.utils import dict_deep_update, load_dict_from_file

from peyrache_lab_to_nwb.miniscope_arc.constants import SESSION_TZ
from peyrache_lab_to_nwb.miniscope_arc.nwbconverter import (
    MINISCOPE_SYNC_DETECTION_CONFIGURATION,
    MiniscopeArcNWBConverter,
)

# TODO (open question Q3): confirm the session-ID convention against DANDI:001676
# before the first upload.  Current convention: "{subject_id}_{YYYY-MM-DD}"
# e.g. "A0662_2022-07-28".

# The lab names the Intan recording directory "{subject}_{YYMMDD}_{HHMMSS}".
_INTAN_DIR_TIMESTAMP = re.compile(r"_(\d{6})_(\d{6})$")


def _find_intan_dir(session_dir_path: Path) -> Optional[Path]:
    """Locate the Intan "one file per signal type" directory in a session.

    The directory is called ``Intan`` in the earliest sessions and
    ``{subject}_{YYMMDD}_{HHMMSS}`` (the lab's naming convention) in later
    ones, so it is found by content — an ``info.rhd`` next to ``time.dat``
    and ``analogin.dat`` — rather than by name.  When several candidates
    match (e.g. a convenience ``Intan`` symlink beside the real directory)
    the timestamped name wins, because its name carries the recording start
    time.  Returns ``None`` when no candidate directory exists.
    """
    candidates = []
    for info_rhd in sorted(session_dir_path.glob("*/info.rhd")):
        directory = info_rhd.parent
        if (directory / "time.dat").is_file() and (directory / "analogin.dat").is_file():
            candidates.append(directory)

    # Deduplicate symlink/real-path pairs, keeping the timestamped name.
    by_target: dict[Path, Path] = {}
    for directory in candidates:
        target = directory.resolve()
        current = by_target.get(target)
        if current is None or _INTAN_DIR_TIMESTAMP.search(directory.name):
            by_target[target] = directory

    if not by_target:
        return None
    return sorted(by_target.values(), key=lambda p: (_INTAN_DIR_TIMESTAMP.search(p.name) is None, p.name))[0]


def _intan_adc_is_valid(intan_dir: Path) -> bool:
    """Return True only when the Intan directory has non-empty ADC data files."""
    return (
        (intan_dir / "info.rhd").is_file()
        and (intan_dir / "time.dat").is_file()
        and (intan_dir / "analogin.dat").is_file()
        and (intan_dir / "time.dat").stat().st_size > 0
        and (intan_dir / "analogin.dat").stat().st_size > 0
    )


def _intan_start_time_from_dir_name(intan_dir: Path) -> Optional[datetime]:
    """Parse the Intan recording start time out of ``{subject}_{YYMMDD}_{HHMMSS}``."""
    match = _INTAN_DIR_TIMESTAMP.search(intan_dir.name)
    if match is None:
        return None
    date_part, time_part = match.groups()
    try:
        naive = datetime.strptime(f"{date_part}_{time_part}", "%y%m%d_%H%M%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=SESSION_TZ)


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
        └── {subject}_{YYMMDD}_{HHMMSS}/   # called "Intan/" in the earliest sessions
            ├── info.rhd
            ├── time.dat           # int32 sample indices at 20 kHz
            └── analogin.dat       # uint16 ADC data (2 channels × N samples)

    The subject ID and session date are inferred from the directory structure::

        …/{subject_id}/{YYYY_MM_DD}/   →  subject_id="A0662", date="2022_07_28"

    Timestamps and time origin
    --------------------------
    Every timestamp written here lives on the **Intan clock**: ``t = 0`` is the
    first Intan sample, Miniscope frame times are decoded from the ADC-01 frame
    gate, and the raw ADC traces are stored as acquired.  ``session_start_time``
    is therefore the Intan recording start, parsed from the Intan directory name,
    not the Miniscope DAQ wall clock.  No frames are dropped to match the
    cropping applied to the published processed data — the raw file keeps every
    acquired frame, and hardware timestamps are what line it up with the
    processed files.

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
    # Build source_data                                                  #
    # ------------------------------------------------------------------ #
    source_data: dict = {}
    conversion_options: dict = {}

    miniscope_dir = session_dir_path / "Miniscope"
    if miniscope_dir.is_dir():
        source_data["MiniscopeImaging"] = dict(folder_path=str(miniscope_dir))
        conversion_options["MiniscopeImaging"] = dict(stub_test=stub_test)
    elif verbose:
        print(f"Warning: no Miniscope directory found in {session_dir_path}")

    # Intan ADC channels — both stored together as TimeSeriesIntanSync in acquisition,
    # plus the ADC-01 frame-gate transitions used for hardware-sync timestamps.
    intan_dir = _find_intan_dir(session_dir_path)
    if intan_dir is not None and _intan_adc_is_valid(intan_dir):
        source_data["Intan"] = dict(
            file_path=str(intan_dir / "info.rhd"),
            detection_configuration=MINISCOPE_SYNC_DETECTION_CONFIGURATION,
        )
        conversion_options["Intan"] = dict(stub_test=stub_test)
    elif verbose:
        location = intan_dir if intan_dir is not None else session_dir_path
        print(f"Warning: Intan ADC data absent or empty in {location} — falling back to USB timestamps.")

    # ------------------------------------------------------------------ #
    # Instantiate converter                                              #
    # ------------------------------------------------------------------ #
    converter = MiniscopeArcNWBConverter(source_data=source_data, verbose=verbose)

    # ------------------------------------------------------------------ #
    # Build metadata                                                     #
    # ------------------------------------------------------------------ #
    metadata = converter.get_metadata()

    # All timestamps in this file are on the Intan clock (t = 0 is the first Intan sample)
    start_time = _intan_start_time_from_dir_name(intan_dir) if intan_dir is not None else None
    if start_time is None:
        raise ValueError(f"Cannot determine Intan session start time for {session_dir_path}. "
                         f"The Intan directory is expected to be named 'subject_YYMMDD_HHMMSS'.")

    metadata["NWBFile"]["session_start_time"] = start_time

    metadata_yaml_path = Path(__file__).parent / "metadata.yaml"
    editable_metadata = load_dict_from_file(metadata_yaml_path)
    metadata = dict_deep_update(metadata, editable_metadata, remove_repeats=False)

    metadata["NWBFile"]["session_id"] = session_id
    # dict_deep_update deduplicates identical floats in lists, collapsing
    # [0.0033, 0.0033] → [0.0033] (shape (1,) instead of the required (2,)).
    metadata["Ophys"]["ImagingPlanes"]["miniscope_imaging"]["grid_spacing"] = [0.0033, 0.0033]

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
    miniscope_folder_path = Path("/Users/weian/source_data/peyrache-lab-local/A0662/2022_08_29")
    nwb_folder_path = Path("/Users/weian/nwb_output/peyrache")

    session_to_nwb(
        session_dir_path=miniscope_folder_path,
        output_dir_path=nwb_folder_path,
        stub_test=True,
        verbose=True,
    )
