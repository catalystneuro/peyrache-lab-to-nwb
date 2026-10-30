"""Primary NWBConverter for the Peyrache Lab miniscope_arc conversion."""

from __future__ import annotations

from typing import Optional

import numpy as np
from neuroconv import NWBConverter
from neuroconv.converters import IntanConverter
from neuroconv.datainterfaces import MiniscopeImagingInterface, OptiTrackInterface

MINISCOPE_SYNC_EVENT_NAME = "miniscope_frame_gate"

# Detection spec for the frame-gate channel in ``IntanConverter``'s
# ``detection_configuration``: every transition of the frame gate marks the start
# of one Miniscope frame.  The gate is a two-level TTL, so it is cut halfway
# between its minimum and maximum.  Each transition is timed at the last sample
# before it, which is how the published DANDI:001676 imaging timestamps were
# derived.  The channel varies between sessions and is found per session.
MINISCOPE_SYNC_DETECTION_SPEC = {
    "signal_conditioning": {"binarize": "midpoint"},
    "detection": "value_change",
    "event_time_convention": "sample_before_transition",
    "event_name": MINISCOPE_SYNC_EVENT_NAME,
}

OPTITRACK_SYNC_EVENT_NAME = "OptiTrackSync"

# Detection spec for the OptiTrack sync channel: Motive sends one 0.5 ms pulse per frame, at
# 120 Hz.  Each rising edge is timed at the first sample after the transition, as in the
# published DANDI:001676 behaviour timestamps.  The cut is halfway between the signal's minimum
# and maximum, and a pulse with a sample partway up its edge can come out one sample (50 µs)
# later than published; this happens for at most 5 pulses per session.
OPTITRACK_SYNC_DETECTION_SPEC = {
    "signal_conditioning": {"binarize": "midpoint"},
    "detection": "rising",
    "event_name": OPTITRACK_SYNC_EVENT_NAME,
}


class MiniscopeArcNWBConverter(NWBConverter):
    """Primary conversion class for Peyrache Lab miniscope_arc data.

    Data streams
    ------------
    OptiTrack
        The OptiTrack Motive ``Take`` CSV export via NeuroConv's
        ``OptiTrackInterface``: the rigid body's position and orientation, written
        to ``processing/behavior``.
    MiniscopeImaging
        Raw UCLA Miniscope V4 video (MJPEG .avi chunks) via the built-in
        ``MiniscopeImagingInterface``.  Produces a ``OnePhotonSeries`` in
        acquisition with hardware-synchronised per-frame timestamps.
    Intan
        NeuroConv's ``IntanConverter``, which discovers the streams in the RHD
        header.  These recordings carry only the ADC input stream, giving two
        children: ``AnalogADCInput`` stores both ADC channels as
        ``TimeSeriesIntanSync`` in acquisition (OptiTrack sync and Miniscope
        frame gate), and ``AnalogEvents`` detects the frame-gate transitions
        with ``MINISCOPE_SYNC_DETECTION_SPEC`` and the OptiTrack sync pulses with
        ``OPTITRACK_SYNC_DETECTION_SPEC``.

    Synchronisation
    ---------------
    ``temporally_align_data_interfaces`` reads the frame-gate transitions from
    ``Intan``'s ``AnalogEvents`` and sets transition i as the time of video
    frame i of ``MiniscopeImaging`` through its ``temporal_alignment``.  Take frame i of
    ``OptiTrack`` is set to OptiTrack sync pulse i.  If ``Intan`` is absent from ``source_data`` (e.g.
    session 2022_07_25 where Intan data files are empty), the method is a
    no-op and the Miniscope interface falls back to USB timestamps.
    """

    data_interface_classes = dict(
        MiniscopeImaging=MiniscopeImagingInterface,
        OptiTrack=OptiTrackInterface,
        Intan=IntanConverter,
    )

    def temporally_align_data_interfaces(
        self,
        metadata: Optional[dict] = None,
        conversion_options: Optional[dict] = None,
    ) -> None:
        """Set Miniscope frame times from the Intan frame-gate transitions, and OptiTrack frame times from its sync.

        The frame gate is a square wave.  One full
        HIGH→LOW cycle spans exactly 2 Miniscope frames:

        - Rising edge  → even frame (0, 2, 4, …)
        - Falling edge → odd  frame (1, 3, 5, …)

        so every transition is one frame.

        Motive sends one sync pulse per OptiTrack frame and keeps sending while it is not
        recording, so a session has more pulses than take frames.  Take frame i is pulse i,
        the first pulse after the Intan start being take frame 0, as in the published behavior timestamps.

        Without ``Intan`` this is a no-op, and each stream it does not find is left as it is.
        """
        if "Intan" not in self.data_interface_objects:
            return

        intan_events = self.data_interface_objects["Intan"].data_interface_objects["AnalogEvents"]

        if "OptiTrack" in self.data_interface_objects:
            optitrack_interface = self.data_interface_objects["OptiTrack"]
            pulse_times = np.asarray(intan_events.get_event_times(OPTITRACK_SYNC_EVENT_NAME))
            n_take_frames = len(optitrack_interface.get_original_timestamps())
            if len(pulse_times) < n_take_frames:
                raise ValueError(
                    f"The Intan OptiTrack sync has only {len(pulse_times)} pulses for {n_take_frames} take frames."
                )
            optitrack_interface.temporal_alignment[optitrack_interface.metadata_key].set_times(
                pulse_times[:n_take_frames]
            )

        if "MiniscopeImaging" in self.data_interface_objects:
            imaging_interface = self.data_interface_objects["MiniscopeImaging"]
            gate_times = np.asarray(intan_events.get_event_times(MINISCOPE_SYNC_EVENT_NAME))
            frame_times = gate_times[: imaging_interface.imaging_extractor.get_num_samples()]
            # The imaging interface registers one time-bearing object, keyed by its metadata key.
            (series_key,) = imaging_interface.temporal_alignment.keys()
            if len(frame_times) < imaging_interface.imaging_extractor.get_num_samples():
                # In some sessions the frame gate stops a few frames before the video ends. The frames after
                # its last transition have no time and are left out, as in the published traces.
                imaging_interface.imaging_extractor = imaging_interface.imaging_extractor.slice_samples(
                    start_sample=0, end_sample=len(frame_times)
                )
                imaging_interface.temporal_alignment[series_key]._get_number_of_samples = (
                    imaging_interface.imaging_extractor.get_num_samples
                )
            imaging_interface.temporal_alignment[series_key].set_times(frame_times)
