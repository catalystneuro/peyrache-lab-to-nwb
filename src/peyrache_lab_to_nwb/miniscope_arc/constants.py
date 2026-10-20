"""Shared constants for the Peyrache Lab miniscope_arc conversion."""

from zoneinfo import ZoneInfo

# McGill University, Montréal — Eastern Time
SESSION_TZ = ZoneInfo("America/Toronto")

# Channel names of the two Intan ADC inputs, as read from the RHD header
CH_OPTITRACK = "ADC-00"  # OptiTrack sync — 120 Hz TTL, 0.5 ms pulse per frame
CH_MINISCOPE = "ADC-01"  # Miniscope frame gate — square wave, 2-frame cycle
