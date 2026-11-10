"""Shared constants for the Peyrache Lab miniscope_arc conversion."""

from datetime import timedelta, timezone

# McGill University, Montréal. A fixed UTC-04:00 all year, as in every published DANDI:001676
# session_start_time, including sessions recorded while Montréal was on EST.
SESSION_TZ = timezone(timedelta(hours=-4))
