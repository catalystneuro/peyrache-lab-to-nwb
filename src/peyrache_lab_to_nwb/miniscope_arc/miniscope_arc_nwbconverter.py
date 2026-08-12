"""Primary NWBConverter for the Peyrache Lab miniscope_arc conversion."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

from neuroconv import NWBConverter
from neuroconv.datainterfaces import MiniscopeImagingInterface

from .interfaces import OptiTrackInterface

# Intan RHD recording parameters (hardware-fixed, not in data files)
_INTAN_SR = 20_000  # samples / second
_ADC_VMAX = 3.3  # volts full-scale for uint16
_ADC_THRESH = 1.0  # volts — threshold for TTL detection

# ADC channel assignments (confirmed from sync exploration notebook)
_CH_OPTITRACK = 0   # ADC-00: 120 Hz TTL, 0.5 ms pulse, one per OptiTrack frame
_CH_MINISCOPE = 1   # ADC-01: square wave; rising = even frame, falling = odd frame


class MiniscopeArcNWBConverter(NWBConverter):
    """Primary conversion class for Peyrache Lab miniscope_arc data.

    Data streams
    ------------
    MiniscopeImaging
        Raw UCLA Miniscope V4 video (MJPEG .avi chunks) via the built-in
        ``MiniscopeImagingInterface``.  Produces a ``OnePhotonSeries`` in
        acquisition with hardware-synchronised per-frame timestamps.

    OptiTrack
        3-D rigid-body position and YXZ Euler rotation from OptiTrack Motive
        CSV export.  Produces ``Position`` (SpatialSeries) and
        ``body_rotation_euler_yxz`` (TimeSeries) in the behavior module with
        hardware-synchronised timestamps.

    Synchronisation
    ---------------
    Hardware sync is decoded from the Intan RHD analog inputs
    (``time.dat`` + ``analogin.dat``) in ``temporally_align_data_interfaces``.
    If the Intan files are absent or empty (e.g. session 2022_07_25), the
    interfaces fall back to their native timestamps.

    Parameters
    ----------
    source_data
        Standard NeuroConv source data dict.  Keys: ``MiniscopeImaging``,
        ``OptiTrack`` (both optional).
    intan_dir_path
        Path to the session's ``Intan/`` directory.  Must contain ``time.dat``
        and ``analogin.dat``.  Pass ``None`` to skip hardware sync.
    verbose
        Whether to print progress information.
    """

    data_interface_classes = dict(
        MiniscopeImaging=MiniscopeImagingInterface,
        OptiTrack=OptiTrackInterface,
    )

    def __init__(
        self,
        source_data: dict,
        intan_dir_path: Optional[Path | str] = None,
        verbose: bool = False,
    ):
        super().__init__(source_data=source_data, verbose=verbose)
        self.intan_dir_path = Path(intan_dir_path) if intan_dir_path is not None else None

    def temporally_align_data_interfaces(
        self,
        metadata: Optional[dict] = None,
        conversion_options: Optional[dict] = None,
    ) -> None:
        """Decode Intan hardware sync pulses and set aligned timestamps.

        Channel mapping (from sync exploration notebook, A0662/2022-07-28):

        ADC-00  OptiTrack TTL
            0.5 ms pulse at 120 Hz; each **rising edge** marks one OptiTrack frame.

        ADC-01  Miniscope frame gate (square wave)
            One full HIGH→LOW cycle spans exactly 2 Miniscope frames:
            - Rising edge  → even frame (0, 2, 4, …)
            - Falling edge → odd  frame (1, 3, 5, …)
            Pulse width ≈ 40.6 ms = one Miniscope frame period.

        If Intan data is unavailable or empty, this method is a no-op and
        the interfaces use their native timestamps.
        """
        if self.intan_dir_path is None:
            return

        time_dat = self.intan_dir_path / "time.dat"
        adc_dat = self.intan_dir_path / "analogin.dat"

        # Abort if files are missing or empty (e.g. session 2022_07_25)
        if (
            not time_dat.is_file()
            or not adc_dat.is_file()
            or time_dat.stat().st_size == 0
            or adc_dat.stat().st_size == 0
        ):
            if self.verbose:
                print(
                    "temporally_align_data_interfaces: Intan files missing or empty — "
                    "skipping hardware sync, falling back to native timestamps."
                )
            return

        # Load Intan data
        time_s = np.fromfile(time_dat, dtype=np.int32).astype(np.float64) / _INTAN_SR
        adc_raw = np.fromfile(adc_dat, dtype=np.uint16)
        n_samples = time_s.size
        if n_samples == 0:
            return
        n_ch = adc_raw.size // n_samples
        adc_v = adc_raw.reshape(n_samples, n_ch).astype(np.float64) * (_ADC_VMAX / 65535.0)

        # ---- OptiTrack timestamps (one per rising edge on ADC-00) ------------
        if "OptiTrack" in self.data_interface_objects:
            ch0_above = (adc_v[:, _CH_OPTITRACK] > _ADC_THRESH).astype(np.int8)
            ch0_rising = np.where(np.diff(ch0_above) == 1)[0]
            opt_timestamps = time_s[ch0_rising]
            self.data_interface_objects["OptiTrack"].set_aligned_timestamps(opt_timestamps)
            if self.verbose:
                print(
                    f"OptiTrack: {len(opt_timestamps):,} synced frames "
                    f"({1.0 / np.diff(opt_timestamps).mean():.2f} Hz)"
                )

        # ---- Miniscope timestamps (rising=even, falling=odd on ADC-01) -------
        if "MiniscopeImaging" in self.data_interface_objects:
            ch1_above = (adc_v[:, _CH_MINISCOPE] > _ADC_THRESH).astype(np.int8)
            ch1_diff = np.diff(ch1_above)
            ch1_rising = np.where(ch1_diff == 1)[0]
            ch1_falling = np.where(ch1_diff == -1)[0]
            n = min(len(ch1_rising), len(ch1_falling))

            ms_timestamps = np.empty(2 * n, dtype=np.float64)
            ms_timestamps[0::2] = time_s[ch1_rising[:n]]   # even frames
            ms_timestamps[1::2] = time_s[ch1_falling[:n]]  # odd frames

            self.data_interface_objects["MiniscopeImaging"].set_aligned_timestamps(
                ms_timestamps
            )
            if self.verbose:
                fps = len(ms_timestamps) / (ms_timestamps[-1] - ms_timestamps[0])
                print(
                    f"Miniscope: {len(ms_timestamps):,} synced frames "
                    f"({fps:.4f} FPS actual — do NOT use rate=25.0)"
                )
