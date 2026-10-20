"""Primary NWBConverter for the Peyrache Lab miniscope_arc conversion."""

from __future__ import annotations

import warnings
from typing import Optional

from neuroconv import NWBConverter
from neuroconv.converters import IntanConverter
from neuroconv.datainterfaces import MiniscopeImagingInterface

from peyrache_lab_to_nwb.miniscope_arc.constants import CH_MINISCOPE

MINISCOPE_SYNC_EVENT_NAME = "miniscope_frame_gate"

# Detection configuration for ``IntanConverter``: every transition of
# the ADC-01 frame gate marks the start of one Miniscope frame.  The gate is a
# two-level TTL, so it is cut halfway between its minimum and maximum.
MINISCOPE_SYNC_DETECTION_CONFIGURATION = {
    CH_MINISCOPE: [
        {
            "signal_conditioning": {"binarize": "midpoint"},
            "detection": "value_change",
            "event_name": MINISCOPE_SYNC_EVENT_NAME,
        },
    ],
}


class MiniscopeArcNWBConverter(NWBConverter):
    """Primary conversion class for Peyrache Lab miniscope_arc data.

    Data streams
    ------------
    MiniscopeImaging
        Raw UCLA Miniscope V4 video (MJPEG .avi chunks) via the built-in
        ``MiniscopeImagingInterface``.  Produces a ``OnePhotonSeries`` in
        acquisition with hardware-synchronised per-frame timestamps.
    Intan
        NeuroConv's ``IntanConverter``, which discovers the streams in the RHD
        header.  These recordings carry only the ADC input stream, giving two
        children: ``AnalogADCInput`` stores both ADC channels as
        ``TimeSeriesIntanSync`` in acquisition (ADC-00 = OptiTrack sync;
        ADC-01 = Miniscope frame gate), and ``AnalogEvents`` detects the
        ADC-01 transitions with ``MINISCOPE_SYNC_DETECTION_CONFIGURATION``.

    Synchronisation
    ---------------
    ``temporally_align_data_interfaces`` reads the ADC-01 transitions from
    ``Intan``'s ``AnalogEvents`` and calls ``set_aligned_timestamps()`` on
    ``MiniscopeImaging``.  If ``Intan`` is absent from ``source_data`` (e.g.
    session 2022_07_25 where Intan data files are empty), the method is a
    no-op and the Miniscope interface falls back to USB timestamps.
    """

    data_interface_classes = dict(
        MiniscopeImaging=MiniscopeImagingInterface,
        Intan=IntanConverter,
    )

    def temporally_align_data_interfaces(
        self,
        metadata: Optional[dict] = None,
        conversion_options: Optional[dict] = None,
    ) -> None:
        """Set Miniscope frame times from the Intan ADC-01 hardware sync pulses.

        ADC-01 carries the Miniscope frame gate (square wave).  One full
        HIGH→LOW cycle spans exactly 2 Miniscope frames:

        - Rising edge  → even frame (0, 2, 4, …)
        - Falling edge → odd  frame (1, 3, 5, …)

        so every transition is one frame.  Pulse width ≈ 40.6 ms = one
        Miniscope frame period.  If ``Intan`` or ``MiniscopeImaging`` is
        absent, this is a no-op.
        """
        if "Intan" not in self.data_interface_objects:
            return
        if "MiniscopeImaging" not in self.data_interface_objects:
            return

        intan_events = self.data_interface_objects["Intan"].data_interface_objects["AnalogEvents"]
        ms_timestamps = intan_events.get_event_times(MINISCOPE_SYNC_EVENT_NAME)

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
