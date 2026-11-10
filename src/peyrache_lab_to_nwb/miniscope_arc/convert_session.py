"""Convert a single Peyrache Lab miniscope_arc session to NWB.

The raw session is written to its own file, or, given the session's published DANDI:001676
processed file, added to a copy of it (see ``session_to_nwb``).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import ndx_miniscope  # noqa: F401  (registers the Miniscope type before the published file is opened)
import numpy as np
from neo.rawio import IntanRawIO
from neuroconv.tools.nwb_helpers import (
    configure_backend,
    get_default_backend_configuration,
)
from neuroconv.utils import dict_deep_update, load_dict_from_file
from pynwb import NWBHDF5IO, NWBFile, read_nwb
from pynwb.ophys import ImagingPlane

from peyrache_lab_to_nwb.miniscope_arc.constants import SESSION_TZ
from peyrache_lab_to_nwb.miniscope_arc.nwbconverter import (
    MINISCOPE_SYNC_DETECTION_SPEC,
    OPTITRACK_SYNC_DETECTION_SPEC,
    MiniscopeArcNWBConverter,
)

# before the first upload.  Current convention: "{subject_id}_{YYYY-MM-DD}"
# e.g. "A0662_2022-07-28".

# The lab names the Intan recording directory "{subject}_{YYMMDD}_{HHMMSS}".
_INTAN_DIR_TIMESTAMP = re.compile(r"_(\d{6})_(\d{6})$")

# Neo's name for the Intan ADC input stream, the only stream these recordings have.
_INTAN_ADC_STREAM = "USB board ADC input channel"
# The frame gate is a square wave, high about half the time; the OptiTrack sync is 0.5 ms pulses
# at 120 Hz, high about 6 % of the time.
_FRAME_GATE_HIGH_FRACTION = (0.25, 0.75)

_IMAGING_PLANE_NAME = "ImagingPlane"
# The names of the rigid body's series in every session
_RIGID_BODY_SERIES_NAMES = {"SpatialSeries": "PositionRigidBody", "TimeSeries": "OrientationRigidBody"}

# The published behaviour series and what this conversion adds to their descriptions.
_PUBLISHED_POSITION = ("Position", "2D_position")
_PUBLISHED_HEAD_DIRECTION = "head-direction"
_PUBLISHED_POSITION_NOTE = (
    "Position X and Z of PositionRigidBody in processing/behavior, from the first OptiTrack frame to the last "
    "imaging frame. 0 marks a frame Motive did not track."
)
_PUBLISHED_HEAD_DIRECTION_NOTE = (
    "deg2rad(Rotation Y) mod 2*pi of OrientationRigidBody in processing/behavior, from the first OptiTrack "
    "frame to the last imaging frame. 0 marks a frame Motive did not track."
)

# File-level fields this conversion's metadata replaces in the published file.
_NWBFILE_FIELDS_FROM_RAW = ("session_id", "experimenter", "related_publications", "keywords", "institution", "lab")

# The published descriptions hold the session's environment, its index in the cell-registration
# table ("session k of N") and the phase protocol. They are appended verbatim, each on its own line.
_PUBLISHED_DESCRIPTION_LABELS = {
    "session_description": "Session",
    "experiment_description": "Protocol phase",
}


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


def _find_sync_channels(intan_dir: Path) -> dict[str, str]:
    """Return the ADC channel names of the Miniscope frame gate and the OptiTrack sync.

    Which ADC inputs carry the two signals varies between sessions (ADC-00 and ADC-01 in the
    earliest, later ADC-00 and ADC-02 or ADC-02 and ADC-07, with either signal on either input),
    so the frame gate is found from the signal: it is the one channel high about half the time.
    """
    reader = IntanRawIO(filename=str(intan_dir / "info.rhd"))
    reader.parse_header()
    streams = reader.header["signal_streams"]
    (stream_index,) = np.flatnonzero(streams["name"] == _INTAN_ADC_STREAM)
    channels = reader.header["signal_channels"]
    channel_ids = [str(c) for c in channels["id"][channels["stream_id"] == streams["id"][stream_index]]]
    if len(channel_ids) != 2:
        raise ValueError(f"Expected two Intan ADC channels in {intan_dir}, found {channel_ids}.")

    traces = reader.get_analogsignal_chunk(stream_index=stream_index)
    low, high = traces.min(axis=0).astype(float), traces.max(axis=0).astype(float)
    high_fraction = (traces > (low + high) / 2).mean(axis=0)
    is_gate = (high_fraction > _FRAME_GATE_HIGH_FRACTION[0]) & (high_fraction < _FRAME_GATE_HIGH_FRACTION[1])
    if np.count_nonzero(is_gate) != 1:
        fractions = ", ".join(f"{c} {f:.2f}" for c, f in zip(channel_ids, high_fraction))
        raise ValueError(f"Cannot tell the frame gate from the OptiTrack sync in {intan_dir} (fraction high: {fractions}).")
    gate_index = int(np.flatnonzero(is_gate)[0])
    return dict(frame_gate=channel_ids[gate_index], optitrack=channel_ids[1 - gate_index])


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
    processed_nwbfile_path: str | Path | None = None,
    stub_test: bool = False,
    overwrite: bool = True,
    verbose: bool = True,
) -> None:
    """Convert one raw session to NWB, on its own or added to its published processed file.

    The output is ``sub-{subject}_ses-{date}_behavior+ophys.nwb``. Without
    ``processed_nwbfile_path`` it holds the raw session only. With it, the published DANDI:001676
    file is read, the converter adds the raw session to it in memory, and the result is exported to
    the output path; the published file is only read. The output
    keeps the published processed data unchanged and takes this conversion's metadata, imaging
    plane and Miniscope device, except that the published ``session_description`` and
    ``experiment_description`` are appended to this conversion's and the published
    ``Subject.age`` is kept. The raw frame times are timed like the published imaging
    timestamps, so the frames the published traces cover carry exactly those timestamps.

    Session directory layout expected::

        {session_dir_path}/
        ├── Miniscope/
        │   ├── 0.avi, 1.avi, …   # MJPEG video chunks (2 000 frames each)
        │   ├── metaData.json
        │   └── timeStamps.csv
        ├── Take {date} {time}.csv  # OptiTrack Motive export
        └── {subject}_{YYMMDD}_{HHMMSS}/   # called "Intan/" in the earliest sessions
            ├── info.rhd
            ├── time.dat           # int32 sample indices at 20 kHz
            └── analogin.dat       # uint16 ADC data (2 channels × N samples)

    The subject ID and session date are inferred from the directory structure::

        …/{subject_id}/{YYYY_MM_DD}/   →  subject_id="A0662", date="2022_07_28"

    Timestamps and time origin
    --------------------------
    Every timestamp written here lives on the **Intan clock**: ``t = 0`` is the
    first Intan sample, Miniscope frame times are decoded from the frame-gate
    ADC channel (found per session), and the raw ADC traces are stored as acquired.  ``session_start_time``
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
    processed_nwbfile_path
        The session's published DANDI:001676 file. Only read.
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
    # Raw-only and combined files share one naming convention.
    nwbfile_path = output_dir_path / f"sub-{subject_id}_ses-{session_id}_behavior+ophys.nwb"
    if processed_nwbfile_path is not None:
        processed_nwbfile_path = Path(processed_nwbfile_path)
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

    take_paths = sorted(session_dir_path.glob("Take*.csv"))
    if len(take_paths) > 1:
        raise ValueError(f"Expected one OptiTrack Take CSV in {session_dir_path}, found {len(take_paths)}.")
    if take_paths:
        source_data["OptiTrack"] = dict(file_path=str(take_paths[0]))
        conversion_options["OptiTrack"] = dict(stub_test=stub_test)
    elif verbose:
        print(f"Warning: no OptiTrack Take CSV found in {session_dir_path}")

    # Intan ADC channels — both stored together as TimeSeriesIntanSync in acquisition,
    # plus the frame-gate transitions and OptiTrack sync pulses used for hardware-sync timestamps.
    intan_dir = _find_intan_dir(session_dir_path)
    if intan_dir is not None and _intan_adc_is_valid(intan_dir):
        sync_channels = _find_sync_channels(intan_dir)
        source_data["Intan"] = dict(
            file_path=str(intan_dir / "info.rhd"),
            detection_configuration={
                sync_channels["frame_gate"]: [MINISCOPE_SYNC_DETECTION_SPEC],
                sync_channels["optitrack"]: [OPTITRACK_SYNC_DETECTION_SPEC],
            },
        )
        # IntanConverter takes its options keyed by child interface. Only the ADC traces can be
        # stubbed; the sync events are always detected over the whole recording.
        conversion_options["Intan"] = dict(AnalogADCInput=dict(stub_test=stub_test))
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
    # Describes the published processed data; used only when the session is added to its published file.
    processed_session_description = editable_metadata.pop("ProcessedSessionDescription")
    metadata = dict_deep_update(metadata, editable_metadata, remove_repeats=False)

    metadata["NWBFile"]["session_id"] = session_id
    # Unify the names of the rigid body's series in every session, where Motive called the body "RigidBody01" or "RigidBody"
    if "OptiTrack" in source_data:
        optitrack_metadata_key = converter.data_interface_objects["OptiTrack"].metadata_key
        for metadata_type, name in _RIGID_BODY_SERIES_NAMES.items():
            (key,) = [key for key in metadata[metadata_type] if key.startswith(f"{optitrack_metadata_key}_")]
            metadata[metadata_type][key]["name"] = name
    # dict_deep_update deduplicates identical floats in lists, collapsing
    # [0.0033, 0.0033] → [0.0033] (shape (1,) instead of the required (2,)).
    metadata["Ophys"]["ImagingPlanes"]["miniscope_imaging"]["grid_spacing"] = [0.0033, 0.0033]

    # Subject — subject_id is required by DANDI; other fields come from the YAML
    metadata["Subject"]["subject_id"] = subject_id

    # ------------------------------------------------------------------ #
    # Run conversion                                                      #
    # ------------------------------------------------------------------ #
    if processed_nwbfile_path is not None:
        if nwbfile_path.exists() and not overwrite:
            raise FileExistsError(f"{nwbfile_path} exists. Pass overwrite=True to replace it.")
        session_description = metadata["NWBFile"]["session_description"].strip()
        metadata["NWBFile"]["session_description"] = f"{session_description} {processed_session_description.strip()}"

        # The raw session is added to the published file in memory, and the result is exported to a
        # new file; the published file is only read.
        processed_nwbfile = read_nwb(processed_nwbfile_path)
        with processed_nwbfile.read_io:
            _check_same_session(metadata=metadata, processed=processed_nwbfile)
            # Before add_to_nwbfile: NeuroConv reuses an imaging plane that already has the raw plane's
            # name, so the published one has to be gone for this conversion's plane to be added.
            published_plane = _remove_published_imaging_plane(processed_nwbfile)

            converter.temporally_align_data_interfaces(metadata=metadata, conversion_options=conversion_options)
            converter.add_to_nwbfile(nwbfile=processed_nwbfile, metadata=metadata, conversion_options=conversion_options)

            _relink_published_segmentation(processed_nwbfile, old_plane=published_plane)
            _update_published_metadata(processed_nwbfile, metadata=metadata)
            if "OptiTrack" in source_data:
                _describe_published_behavior(processed_nwbfile)

            backend_configuration = get_default_backend_configuration(nwbfile=processed_nwbfile, backend="hdf5")
            configure_backend(nwbfile=processed_nwbfile, backend_configuration=backend_configuration)
            with NWBHDF5IO(path=nwbfile_path, mode="w") as export_io:
                export_io.export(src_io=processed_nwbfile.read_io, nwbfile=processed_nwbfile)

    else:
        converter.run_conversion(
            nwbfile_path=nwbfile_path,
            metadata=metadata,
            conversion_options=conversion_options,
            overwrite=overwrite,
        )

    if verbose:
        print(f"Done → {nwbfile_path}")


def _check_same_session(*, metadata: dict, processed: NWBFile) -> None:
    """Refuse a published file that cannot be this session."""
    subject_id = metadata["Subject"]["subject_id"]
    if processed.subject is None or processed.subject.subject_id != subject_id:
        found = processed.subject.subject_id if processed.subject is not None else None
        raise ValueError(f"The processed file is for subject {found!r}, this session for {subject_id!r}.")
    # The published start time is the Miniscope DAQ clock and this one the Intan clock, seconds
    # apart; the recording date is what both state.
    session_date = metadata["NWBFile"]["session_start_time"].date()
    if processed.session_start_time.date() != session_date:
        raise ValueError(
            f"The processed file was recorded on {processed.session_start_time.date()}, this session on {session_date}."
        )
    if _IMAGING_PLANE_NAME not in processed.imaging_planes:
        raise ValueError(f"The processed file has no imaging plane named {_IMAGING_PLANE_NAME!r}.")


def _remove_published_imaging_plane(processed: NWBFile) -> ImagingPlane:
    """Remove the published imaging plane and its device, which this conversion's replace."""
    published_plane = processed.imaging_planes.pop(_IMAGING_PLANE_NAME)
    processed.devices.pop(published_plane.device.name)
    return published_plane


def _relink_published_segmentation(processed: NWBFile, *, old_plane: ImagingPlane) -> None:
    """Point the published segmentation at this conversion's imaging plane."""
    new_plane = processed.imaging_planes[_IMAGING_PLANE_NAME]
    for container in processed.all_children():
        if container.fields.get("imaging_plane") is old_plane:
            container.fields["imaging_plane"] = new_plane
            container.set_modified()


def _update_published_metadata(processed: NWBFile, *, metadata: dict) -> None:
    """Replace the published file-level and subject metadata with this conversion's."""
    nwbfile_metadata = metadata["NWBFile"]
    for field, label in _PUBLISHED_DESCRIPTION_LABELS.items():
        description = nwbfile_metadata[field].strip()
        published = getattr(processed, field)
        if published:
            description = f"{description}\n\n{label}: {published.strip()}"
        processed.fields[field] = description

    processed.fields["identifier"] = str(uuid.uuid4())
    # Every published timestamp is on the Intan clock, so the Intan start is the correct origin.
    processed.fields["session_start_time"] = nwbfile_metadata["session_start_time"]
    processed.fields["timestamps_reference_time"] = nwbfile_metadata["session_start_time"]
    for field in _NWBFILE_FIELDS_FROM_RAW:
        if field in nwbfile_metadata:
            processed.fields[field] = nwbfile_metadata[field]

    # Fields this conversion leaves unset, such as age, keep their published value.
    for field, value in metadata["Subject"].items():
        processed.subject.fields[field] = value

    # Export writes objects read from the file as they were stored unless they are marked modified.
    processed.set_modified()
    processed.subject.set_modified()


def _describe_published_behavior(processed: NWBFile) -> None:
    """Point the published behaviour series at the raw ones and correct the position unit."""
    position = processed.acquisition[_PUBLISHED_POSITION[0]][_PUBLISHED_POSITION[1]]
    head_direction = processed.acquisition[_PUBLISHED_HEAD_DIRECTION]
    for series, note in ((position, _PUBLISHED_POSITION_NOTE), (head_direction, _PUBLISHED_HEAD_DIRECTION_NOTE)):
        series.fields["description"] = f"{series.description.strip()}. {note}"
        series.set_modified()
    # The published unit "m" is not one NWB Inspector accepts.
    position.fields["unit"] = "meters"


if __name__ == "__main__":
    miniscope_folder_path = Path("/Users/weian/source_data/peyrache-lab-local/A0662/2022_11_14")
    nwb_folder_path = Path("/Users/weian/nwb_output/peyrache")
    processed_nwbfile_path = Path(
        "/Users/weian/source_data/dandi/001676/sub-A0662/sub-A0662_ses-20221114T101446_behavior+ophys.nwb"
    )

    session_to_nwb(
        session_dir_path=miniscope_folder_path,
        output_dir_path=nwb_folder_path,
        processed_nwbfile_path=processed_nwbfile_path,
        stub_test=True,
        verbose=True,
        overwrite=True,
    )
