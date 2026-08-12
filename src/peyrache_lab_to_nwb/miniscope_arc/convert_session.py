"""Convert a single Peyrache Lab miniscope_arc session to NWB."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from neuroconv.utils import dict_deep_update, load_dict_from_file

from .nwbconverter import MiniscopeArcNWBConverter

# McGill University, Montréal — Eastern Time
_SESSION_TZ = ZoneInfo("America/Toronto")

# TODO (open question Q3): confirm the session-ID convention against DANDI:001676
# before the first upload.  Current convention: "{subject_id}_{YYYY_MM_DD}"
# e.g. "A0662_2022_07_28".


def session_to_nwb(
    session_dir_path: str | Path,
    output_dir_path: str | Path,
    append_to_nwb_path: Optional[str | Path] = None,
    stub_test: bool = False,
    overwrite: bool = False,
    verbose: bool = False,
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
        Root directory for output NWB files (ignored when ``append_to_nwb_path``
        is given).
    append_to_nwb_path
        If provided, the function *appends* the Miniscope data to this existing
        NWB file instead of creating a new one.  Use this to add raw video to
        already-converted sessions from DANDI:001676.  Only ``MiniscopeImaging``
        is included in append mode (tracking data is already in the existing file).
    stub_test
        If ``True``, write only a short excerpt of each data stream to
        ``{output_dir_path}/nwb_stub/``.  Ignored in append mode.
    overwrite
        If ``True``, allow overwriting an existing output NWB file.
    verbose
        If ``True``, print progress information.
    """
    session_dir_path = Path(session_dir_path)
    output_dir_path = Path(output_dir_path)

    # Derive identifiers from directory structure
    session_date = session_dir_path.name          # "YYYY_MM_DD"
    subject_id = session_dir_path.parent.name     # e.g. "A0662"
    session_id = f"{subject_id}_{session_date}"

    # ------------------------------------------------------------------ #
    # Resolve output path and write mode                                  #
    # ------------------------------------------------------------------ #
    if append_to_nwb_path is not None:
        nwbfile_path = Path(append_to_nwb_path)
        write_mode = "r+"
        if verbose:
            print(f"[append mode] → {nwbfile_path}")
    else:
        if stub_test:
            output_dir_path = output_dir_path / "nwb_stub"
        output_dir_path.mkdir(parents=True, exist_ok=True)
        nwbfile_path = output_dir_path / f"sub-{subject_id}_ses-{session_date}.nwb"
        write_mode = "w"
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

    # Intan directory for hardware sync decoding
    intan_dir = session_dir_path / "Intan"
    intan_dir_path = intan_dir if intan_dir.is_dir() else None

    # ------------------------------------------------------------------ #
    # Instantiate converter                                               #
    # ------------------------------------------------------------------ #
    converter = MiniscopeArcNWBConverter(
        source_data=source_data,
        intan_dir_path=intan_dir_path,
        verbose=verbose,
    )

    # ------------------------------------------------------------------ #
    # Build metadata                                                      #
    # ------------------------------------------------------------------ #
    metadata = converter.get_metadata()

    if append_to_nwb_path is None:
        # Layer 1: attach timezone to auto-extracted session_start_time
        start_time = metadata["NWBFile"].get("session_start_time")
        if start_time is not None and start_time.tzinfo is None:
            metadata["NWBFile"]["session_start_time"] = start_time.replace(tzinfo=_SESSION_TZ)

        # Layer 2: merge hand-edited lab-level metadata from YAML
        metadata_yaml_path = Path(__file__).parent / "metadata.yaml"
        editable_metadata = load_dict_from_file(metadata_yaml_path)
        metadata = dict_deep_update(metadata, editable_metadata)

        # Layer 3: session-specific overrides
        metadata["NWBFile"]["session_id"] = session_id

        # Subject — subject_id is required by DANDI; other fields come from the YAML
        # TODO (open question Q7): fill in per-subject sex, date_of_birth, weight from lab records
        metadata.setdefault("Subject", {})
        metadata["Subject"]["subject_id"] = subject_id

    # ------------------------------------------------------------------ #
    # Run conversion                                                      #
    # ------------------------------------------------------------------ #
    converter.run_conversion(
        nwbfile_path=nwbfile_path,
        metadata=metadata,
        conversion_options=conversion_options,
        overwrite=overwrite,
        mode=write_mode,
    )

    if verbose:
        print(f"Done → {nwbfile_path}")


if __name__ == "__main__":
    # ------------------------------------------------------------------ #
    # Example: new NWB file (stub test)                                   #
    # ------------------------------------------------------------------ #
    _session = Path("~/source_data/peyrache-lab/A0662/2022_07_28").expanduser()
    _out = Path("~/nwb_output/peyrache").expanduser()

    session_to_nwb(
        session_dir_path=_session,
        output_dir_path=_out,
        stub_test=True,
        verbose=True,
    )

    # ------------------------------------------------------------------ #
    # Example: append raw Miniscope video to an existing DANDI NWB file  #
    # ------------------------------------------------------------------ #
    # Workflow:
    #   1. Download the existing file from DANDI:001676 with dandi CLI:
    #        dandi download "https://dandiarchive.org/dandiset/001676/0.251205.2137/assets/<asset-id>/download/"
    #   2. Run append:
    #        session_to_nwb(
    #            session_dir_path=_session,
    #            output_dir_path=_out,  # ignored in append mode
    #            append_to_nwb_path="/path/to/downloaded/sub-A0662_ses-20220728.nwb",
    #            verbose=True,
    #        )
    #   3. Re-upload with dandi CLI:
    #        dandi upload /path/to/modified.nwb --dandiset 001676
    pass
