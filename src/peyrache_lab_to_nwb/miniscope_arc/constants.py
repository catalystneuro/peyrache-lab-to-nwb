"""Shared constants for the Peyrache Lab miniscope_arc conversion."""

from zoneinfo import ZoneInfo

# McGill University, Montréal — Eastern Time
SESSION_TZ = ZoneInfo("America/Toronto")

# Intan RHD stream name for analog (ADC) input channels
INTAN_ADC_STREAM = "USB board ADC input channel"

# Column indices within the two-channel analogin.dat
CH_OPTITRACK = 0  # ADC-00: OptiTrack sync — 120 Hz TTL, 0.5 ms pulse per frame
CH_MINISCOPE = 1  # ADC-01: Miniscope frame gate — square wave, 2-frame cycle

# Threshold for binarising sync channels in Volts.
# get_traces(return_scaled=True) returns μV; divide by 1e6 to get V before comparing.
ADC_THRESH_V = 1.0
