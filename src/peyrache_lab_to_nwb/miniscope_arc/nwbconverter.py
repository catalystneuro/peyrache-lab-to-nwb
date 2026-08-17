"""Primary NWBConverter for the Peyrache Lab miniscope_arc conversion."""

from __future__ import annotations

import warnings
from typing import Optional

import numpy as np

from neuroconv import NWBConverter
from neuroconv.datainterfaces import IntanAnalogInterface, MiniscopeImagingInterface

# TODO: investigate why this is needed
# neuroconv 0.9.3 calls get_channel_names() on all ImagingExtractors, but
# roiextractors 0.9.x has not yet added it to MiniscopeImagingExtractor.
# Patch it here so the single-channel (green) Miniscope extractor works.
try:
    from roiextractors.extractors.miniscopeimagingextractor.miniscopeimagingextractor import (
        MiniscopeImagingExtractor,
    )

    if not hasattr(MiniscopeImagingExtractor, "get_channel_names"):
        MiniscopeImagingExtractor.get_channel_names = lambda self: ["GreenChannel"]
except ImportError:
    pass

# Stream name for Intan RHD ADC input channels
_INTAN_ADC_STREAM = "USB board ADC input channel"

# ADC channel indices within the two-channel analogin.dat
_CH_OPTITRACK = 0   # ADC-00: OptiTrack sync — 120 Hz TTL, 0.5 ms pulse per frame
_CH_MINISCOPE = 1   # ADC-01: Miniscope frame gate — square wave, 2-frame cycle

# Threshold for binarising sync channels in Volts.
# get_traces(return_scaled=True) returns μV; divide by 1e6 to get V.
_ADC_THRESH_V = 1.0


class MiniscopeArcNWBConverter(NWBConverter):
    """Primary conversion class for Peyrache Lab miniscope_arc data.

    Data streams
    ------------
    MiniscopeImaging
        Raw UCLA Miniscope V4 video (MJPEG .avi chunks) via the built-in
        ``MiniscopeImagingInterface``.  Produces a ``OnePhotonSeries`` in
        acquisition with hardware-synchronised per-frame timestamps.
    IntanSync
        Both Intan RHD ADC input channels stored as ``TimeSeriesIntanSync``
        in acquisition.  Channel 0 (ADC-00) = OptiTrack sync; channel 1
        (ADC-01) = Miniscope frame gate.  Also used to derive hardware
        timestamps for ``OnePhotonSeries`` in
        ``temporally_align_data_interfaces``.

    Synchronisation
    ---------------
    ``temporally_align_data_interfaces`` decodes rising/falling edges on
    ADC-01 and calls ``set_aligned_timestamps()`` on ``MiniscopeImaging``.
    If ``IntanSync`` is absent from ``source_data`` (e.g. session 2022_07_25
    where Intan data files are empty), the method is a no-op and the
    Miniscope interface falls back to USB timestamps.
    """

    data_interface_classes = dict(
        MiniscopeImaging=MiniscopeImagingInterface,
        IntanSync=IntanAnalogInterface,
    )

    def temporally_align_data_interfaces(
        self,
        metadata: Optional[dict] = None,
        conversion_options: Optional[dict] = None,
    ) -> None:
        """Decode Intan ADC-01 hardware sync pulses and set aligned timestamps.

        ADC-01 carries the Miniscope frame gate (square wave).  One full
        HIGH→LOW cycle spans exactly 2 Miniscope frames:

        - Rising edge  → even frame (0, 2, 4, …)
        - Falling edge → odd  frame (1, 3, 5, …)

        Pulse width ≈ 40.6 ms = one Miniscope frame period.  If ``IntanSync``
        is absent, this is a no-op.
        """
        if "IntanSync" not in self.data_interface_objects:
            return

        recording = self.data_interface_objects["IntanSync"].recording_extractor
        n_samples = recording.get_num_samples()
        if n_samples == 0:
            return

        time_s = recording.get_times()                           # (n_samples,) seconds
        adc_v = recording.get_traces(return_scaled=True) / 1e6  # μV → V

        if "MiniscopeImaging" in self.data_interface_objects:
            ch_above = (adc_v[:, _CH_MINISCOPE] > _ADC_THRESH_V).astype(np.int8)
            ch_diff = np.diff(ch_above)
            rising  = np.where(ch_diff == 1)[0]
            falling = np.where(ch_diff == -1)[0]
            n = min(len(rising), len(falling))

            ms_timestamps = np.empty(2 * n, dtype=np.float64)
            ms_timestamps[0::2] = time_s[rising[:n]]   # even frames
            ms_timestamps[1::2] = time_s[falling[:n]]  # odd frames

            n_frames = self.data_interface_objects["MiniscopeImaging"].imaging_extractor.get_num_samples()
            n_detected = len(ms_timestamps)

            if n_detected < n_frames:
                warnings.warn(
                    f"Miniscope sync: only {n_detected} hardware timestamps detected "
                    f"for {n_frames} video frames — {n_frames - n_detected} frames will "
                    f"lack hardware timestamps. Check the Intan ADC-01 signal.",
                    UserWarning,
                    stacklevel=2,
                )

            # Trim the (typically small) tail where Intan runs past the last frame
            ms_timestamps = ms_timestamps[:n_frames]

            self.data_interface_objects["MiniscopeImaging"].set_aligned_timestamps(ms_timestamps)
