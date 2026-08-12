"""Interface for OptiTrack Motive 3D rigid-body tracking CSV exports."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from hdmf.backends.hdf5.h5_utils import H5DataIO
from pynwb import NWBFile, TimeSeries
from pynwb.behavior import Position, SpatialSeries

from neuroconv.basedatainterface import BaseDataInterface
from neuroconv.tools.nwb_helpers import get_module
from neuroconv.utils import DeepDict


class OptiTrackInterface(BaseDataInterface):
    """Interface for OptiTrack Motive 3D rigid-body tracking data.

    Reads CSV exports from OptiTrack Motive (format version 1.23) and writes
    to the NWB behavior processing module:

    - ``position`` (SpatialSeries inside Position): 3D position [X, Y, Z] in
      the OptiTrack global coordinate system, in meters.
    - ``body_rotation_euler_yxz`` (TimeSeries): 3D YXZ Euler angles in degrees.
      Column 0 (Rotation Y) is the yaw / head-direction angle in the horizontal
      plane — the primary variable of interest for head-direction studies.

    Temporal alignment
    ------------------
    Call ``set_aligned_timestamps(hw_timestamps)`` with Intan-clock timestamps
    before running conversion.  If hardware timestamps contain fewer frames than
    the CSV (e.g. 144,444 instead of 144,612), only the synced prefix of the
    tracking data is written; trailing unsynced frames are silently dropped.
    Without a ``set_aligned_timestamps`` call the OptiTrack-internal ``Time
    (Seconds)`` column is used as-is.
    """

    keywords = ["behavior", "position", "head direction", "OptiTrack", "tracking"]

    def __init__(self, file_path: str | Path, verbose: bool = False):
        """
        Parameters
        ----------
        file_path
            Path to the OptiTrack Motive CSV export
            (e.g. ``Take 2022-07-25 02.28.38 PM.csv``).
        verbose
            Whether to print progress information.
        """
        self.file_path = Path(file_path)
        self.verbose = verbose
        self._timestamps: Optional[np.ndarray] = None
        super().__init__(file_path=str(file_path))

    # ------------------------------------------------------------------
    # Temporal alignment API (mirrors BaseImagingExtractorInterface)
    # ------------------------------------------------------------------

    def get_original_timestamps(self) -> np.ndarray:
        """Return raw timestamps from the OptiTrack CSV (internal clock, seconds)."""
        df, _ = _read_optitrack_csv(self.file_path)
        time_col = _find_column(df, ["time (seconds)", "time (s)"])
        return df[time_col].values.astype(np.float64)

    def set_aligned_timestamps(self, aligned_timestamps: np.ndarray) -> None:
        """Replace CSV timestamps with hardware-synchronised timestamps.

        Parameters
        ----------
        aligned_timestamps
            Per-frame timestamps in seconds on the Intan master clock.
            May be shorter than the total frame count; trailing unsynced
            frames are dropped during conversion.
        """
        self._timestamps = np.asarray(aligned_timestamps, dtype=np.float64)

    def get_timestamps(self) -> np.ndarray:
        """Return the timestamps that will be written to NWB."""
        if self._timestamps is not None:
            return self._timestamps
        return self.get_original_timestamps()

    # ------------------------------------------------------------------
    # NeuroConv interface methods
    # ------------------------------------------------------------------

    def get_metadata(self) -> DeepDict:
        metadata = super().get_metadata()
        return metadata

    def add_to_nwbfile(
        self,
        nwbfile: NWBFile,
        metadata: Optional[dict] = None,
        stub_test: bool = False,
    ) -> None:
        df, _ = _read_optitrack_csv(self.file_path)
        timestamps = self.get_timestamps()

        n_synced = len(timestamps)
        if stub_test:
            # ~8 s of tracking at 120 FPS
            n_synced = min(n_synced, 1000)
            timestamps = timestamps[:n_synced]

        # Trim CSV data to the number of available (synced) frames
        df = df.iloc[:n_synced].reset_index(drop=True)

        timestamps_compressed = H5DataIO(timestamps, compression="gzip")

        # ---- 3-D position [X, Y, Z] in metres --------------------------------
        pos_x = _find_column(df, ["position x", "pos x"])
        pos_y = _find_column(df, ["position y", "pos y"])
        pos_z = _find_column(df, ["position z", "pos z"])
        position_data = df[[pos_x, pos_y, pos_z]].values.astype(np.float64)

        position_series = SpatialSeries(
            name="position",
            description=(
                "3-D position of the rigid body (rat head) tracked by OptiTrack Motive. "
                "Columns: [X, Y, Z] in the OptiTrack global coordinate system (Y-up). "
                "Values are in metres (raw from OptiTrack export, no rescaling applied)."
            ),
            data=H5DataIO(position_data, compression="gzip"),
            reference_frame="OptiTrack global coordinate system (Y-up)",
            unit="m",
            conversion=1.0,
            resolution=-1.0,
            timestamps=timestamps_compressed,
        )
        position_container = Position(name="Position")
        position_container.add_spatial_series(position_series)

        # ---- 3-D rotation YXZ Euler angles [Y, X, Z] in degrees -------------
        rot_y = _find_column(df, ["rotation y", "rot y"])
        rot_x = _find_column(df, ["rotation x", "rot x"])
        rot_z = _find_column(df, ["rotation z", "rot z"])
        rotation_data = df[[rot_y, rot_x, rot_z]].values.astype(np.float64)

        rotation_series = TimeSeries(
            name="body_rotation_euler_yxz",
            description=(
                "3-D rotation of the rigid body (rat head) as YXZ Euler angles from "
                "OptiTrack Motive. Columns: [Rotation Y (yaw / head-direction angle in "
                "the horizontal plane), Rotation X (pitch), Rotation Z (roll)]. "
                "Column 0 (Rotation Y) is the primary head-direction variable. "
                "Units are degrees."
            ),
            data=H5DataIO(rotation_data, compression="gzip"),
            unit="degrees",
            resolution=-1.0,
            timestamps=H5DataIO(timestamps, compression="gzip"),
        )

        behavior_module = get_module(nwbfile, "behavior", "Processed behavioral data")
        behavior_module.add(position_container)
        behavior_module.add(rotation_series)


# ---------------------------------------------------------------------------
# CSV parsing helpers
# ---------------------------------------------------------------------------


def _read_optitrack_csv(file_path: Path) -> tuple[pd.DataFrame, dict]:
    """Read an OptiTrack Motive CSV export, tolerating variable header lengths.

    Scans the file to locate the row whose first cell is ``Frame``, uses that as
    the column header, then drops any immediately following non-numeric sub-header
    rows (e.g. unit labels that some Motive versions insert).

    Returns
    -------
    df : pd.DataFrame
        Data-only rows with original column names.
    csv_metadata : dict
        Key–value pairs from the header section (``frame_rate``, ``capture_start_time``).
    """
    csv_metadata: dict = {}

    with open(file_path, "r", encoding="utf-8-sig") as f:
        lines = f.readlines()

    # Parse header key-value pairs
    for line in lines[:20]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        key, value = parts[0], parts[1]
        if key in ("Capture Frame Rate", "Export Frame Rate") and "frame_rate" not in csv_metadata:
            try:
                csv_metadata["frame_rate"] = float(value)
            except ValueError:
                pass
        elif key == "Capture Start Time":
            csv_metadata["capture_start_time"] = value

    # Find the row whose first non-quoted cell equals "Frame"
    header_row_idx: Optional[int] = None
    for i, line in enumerate(lines):
        first_cell = line.split(",")[0].strip().strip('"').strip()
        if first_cell.lower() == "frame":
            header_row_idx = i
            break

    if header_row_idx is None:
        raise ValueError(
            f"Could not find a 'Frame' column header row in {file_path}. "
            "Is this a valid OptiTrack Motive CSV export?"
        )

    df = pd.read_csv(file_path, skiprows=header_row_idx, header=0, low_memory=False)

    # Normalise column names (strip whitespace)
    df.columns = [str(c).strip() for c in df.columns]

    # Drop non-numeric rows that follow the header (e.g. unit-label rows)
    frame_col = df.columns[0]
    df = df[pd.to_numeric(df[frame_col], errors="coerce").notna()].copy()
    df[frame_col] = df[frame_col].astype(int)
    df = df.reset_index(drop=True)

    return df, csv_metadata


def _find_column(df: pd.DataFrame, candidates: list[str]) -> str:
    """Return the first column matching any candidate (case-insensitive).

    Tries exact match first, then substring match.
    """
    lower_to_orig = {c.lower(): c for c in df.columns}
    # Exact match
    for candidate in candidates:
        if candidate.lower() in lower_to_orig:
            return lower_to_orig[candidate.lower()]
    # Substring match
    for candidate in candidates:
        for col_lower, col_orig in lower_to_orig.items():
            if candidate.lower() in col_lower:
                return col_orig
    raise KeyError(
        f"None of {candidates!r} found in columns: {list(df.columns)}"
    )
