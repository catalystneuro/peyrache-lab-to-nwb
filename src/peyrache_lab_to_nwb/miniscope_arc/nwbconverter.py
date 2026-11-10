"""Primary NWBConverter for the Peyrache Lab miniscope_arc conversion."""

from __future__ import annotations

from typing import Optional

import numpy as np
import scipy.signal
from neuroconv import NWBConverter
from neuroconv.converters import IntanConverter
from neuroconv.datainterfaces import MiniscopeImagingInterface, OptiTrackInterface

MINISCOPE_SYNC_EVENT_NAME = "miniscope_frame_gate"

# Detection spec for the frame-gate channel in ``IntanConverter``'s
# ``detection_configuration``: every transition of the frame gate, written to the
# ``MiniscopeFrameGate`` events table.  The gate is a two-level TTL, so it is cut
# halfway between its minimum and maximum, and each transition is timed at the
# last sample before it.  The channel varies between sessions and is found per
# session; the converter reads it from this entry to find the trace that
# ``frame_gate_samples`` takes the frame times from.
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
# later than published; this happens for at most 4 pulses per session.
OPTITRACK_SYNC_DETECTION_SPEC = {
    "signal_conditioning": {"binarize": "midpoint"},
    "detection": "rising",
    "event_name": OPTITRACK_SYNC_EVENT_NAME,
}

# The lab's frame-gate detection, from gviejo/PSBImaging python/wrappers.py
# (https://github.com/gviejo/PSBImaging/blob/main/python/wrappers.py): peaks of the absolute
# sample-to-sample change of the raw ADC counts, at least this high and this many samples apart.
_GATE_PEAK_HEIGHT = 30000
_GATE_PEAK_DISTANCE = 500


def frame_gate_samples(gate_trace: np.ndarray) -> np.ndarray:
    """Return the sample index of each frame-gate transition, by the lab's detection.

    Each index is the last sample before a transition. Two transitions closer than
    ``_GATE_PEAK_DISTANCE`` samples (25 ms, three quarters of a frame period) are a glitch on the
    gate, and only the one with the larger jump is kept. This reproduces the published
    DANDI:001676 imaging timestamps sample for sample, glitch sessions included. Frame i of the
    video is transition i; frames missing from the video are not accounted for, as in the
    published files.

    Parameters
    ----------
    gate_trace : np.ndarray
        The frame-gate ADC channel in raw counts (uint16).

    Returns
    -------
    np.ndarray
        Sample indices into ``gate_trace``.
    """
    jumps = np.abs(np.diff(gate_trace.astype(np.int32)))
    peaks, _ = scipy.signal.find_peaks(jumps, height=_GATE_PEAK_HEIGHT, distance=_GATE_PEAK_DISTANCE)
    return peaks


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
    ``temporally_align_data_interfaces`` detects the frame-gate transitions in
    the raw frame-gate trace of ``Intan``'s ``AnalogADCInput`` with
    ``frame_gate_samples`` (the lab's detection) and sets transition i as the
    time of video frame i of ``MiniscopeImaging`` through its
    ``temporal_alignment``.  Take frame i of
    ``OptiTrack`` is set to OptiTrack sync pulse i.  If ``Intan`` is absent from ``source_data`` (e.g.
    session 2022_07_25 where Intan data files are empty), the method is a
    no-op and the Miniscope interface falls back to USB timestamps.
    """

    data_interface_classes = dict(
        MiniscopeImaging=MiniscopeImagingInterface,
        OptiTrack=OptiTrackInterface,
        Intan=IntanConverter,
    )

    def __init__(self, source_data: dict[str, dict], verbose: bool = False):
        super().__init__(source_data=source_data, verbose=verbose)
        # The frame-gate channel is the one whose detection spec names the Miniscope frame gate.
        detection_configuration = source_data.get("Intan", {}).get("detection_configuration", {})
        self._frame_gate_channel = next(
            (
                channel_id
                for channel_id, specs in detection_configuration.items()
                if any(spec.get("event_name") == MINISCOPE_SYNC_EVENT_NAME for spec in specs)
            ),
            None,
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

        so every transition is one frame.  Pulse width ≈ 33.5 ms = one
        Miniscope frame period.  The transitions are detected by the lab's rule
        (``frame_gate_samples``), which drops glitch transitions as the
        published timestamps do.

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

        if "MiniscopeImaging" not in self.data_interface_objects:
            return

        if self._frame_gate_channel is None:
            raise ValueError(
                f"No Intan detection_configuration entry names the event '{MINISCOPE_SYNC_EVENT_NAME}', so the "
                "frame-gate channel is unknown."
            )
        adc_recording = self.data_interface_objects["Intan"].data_interface_objects["AnalogADCInput"].recording_extractor
        gate_trace = adc_recording.get_traces(channel_ids=[self._frame_gate_channel], return_in_uV=False)[:, 0]
        gate_times = adc_recording.sample_index_to_time(frame_gate_samples(gate_trace), segment_index=0)

        imaging_interface = self.data_interface_objects["MiniscopeImaging"]
        frame_times = gate_times[: imaging_interface.imaging_extractor.get_num_samples()]
        # The imaging interface registers one time-bearing object, keyed by its metadata key.
        (series_key,) = imaging_interface.temporal_alignment.keys()
        if len(frame_times) < imaging_interface.imaging_extractor.get_num_samples():
            # In some sessions the frame gate stops a few frames before the video ends. The frames after
            # its last transition have no time and are left out, as in the published traces.
            imaging_interface.imaging_extractor = imaging_interface.imaging_extractor.slice_samples(
                start_sample=0, end_sample=len(frame_times)
            )
            # The interface counts samples on the extractor it was created with.
            imaging_interface.temporal_alignment[series_key]._get_number_of_samples = (
                imaging_interface.imaging_extractor.get_num_samples
            )
        imaging_interface.temporal_alignment[series_key].set_times(frame_times)
