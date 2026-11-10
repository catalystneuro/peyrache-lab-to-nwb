"""Batch conversion of all Peyrache Lab miniscope_arc sessions."""

from __future__ import annotations

import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from pprint import pformat

from tqdm import tqdm

from .convert_session import _find_intan_dir, session_to_nwb
from .sessions_on_hold import SESSIONS_ON_HOLD


def dataset_to_nwb(
    *,
    data_dir_path: str | Path,
    output_dir_path: str | Path,
    processed_dir_path: str | Path | None = None,
    max_workers: int = 1,
    stub_test: bool = False,
    verbose: bool = False,
    include_sessions_on_hold: bool = False,
) -> None:
    """Convert all sessions in the dataset to NWB.

    Discovers sessions by iterating over the directory tree::

        {data_dir_path}/
        └── {subject_id}/
            └── {YYYY_MM_DD}/    ← session directory

    A directory is treated as a session if it contains a ``Miniscope``
    sub-directory or an Intan recording directory.

    Parameters
    ----------
    data_dir_path
        Root of the source data (e.g. ``~/source_data/peyrache-lab/``).
    output_dir_path
        Root directory for output NWB files.
    processed_dir_path
        Local copy of DANDI:001676 in the ``dandi download`` layout
        (``{processed_dir_path}/sub-{subject}/*.nwb``). When given, each session with a published
        file on the same date is added to a copy of it; the others are written as raw files.
    max_workers
        Number of parallel workers (default 1 = sequential).
    stub_test
        If ``True``, write short stub files only.
    verbose
        If ``True``, print per-session progress.
    include_sessions_on_hold
        If ``True``, also convert the sessions in ``SESSIONS_ON_HOLD`` (dropped frames, gate and frame
        counts that differ, or not checked). They are left out by default.
    """
    data_dir_path = Path(data_dir_path)
    output_dir_path = Path(output_dir_path)

    kwargs_per_session = get_session_to_nwb_kwargs_per_session(
        data_dir_path=data_dir_path,
        processed_dir_path=processed_dir_path,
        include_sessions_on_hold=include_sessions_on_hold,
    )

    if not kwargs_per_session:
        print(f"No sessions found under {data_dir_path}")
        return

    futures = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        for kwargs in kwargs_per_session:
            kwargs["output_dir_path"] = output_dir_path
            kwargs["stub_test"] = stub_test
            kwargs["verbose"] = verbose
            exception_file_path = (
                output_dir_path
                / f"ERROR_{Path(kwargs['session_dir_path']).parent.name}"
                  f"_{Path(kwargs['session_dir_path']).name}.txt"
            )
            futures.append(
                executor.submit(
                    safe_session_to_nwb,
                    session_to_nwb_kwargs=kwargs,
                    exception_file_path=exception_file_path,
                )
            )
        for _ in tqdm(as_completed(futures), total=len(futures), desc="Converting sessions"):
            pass


def safe_session_to_nwb(
    *,
    session_to_nwb_kwargs: dict,
    exception_file_path: Path | str,
) -> None:
    """Wrap ``session_to_nwb`` so that exceptions are written to a file."""
    exception_file_path = Path(exception_file_path)
    try:
        session_to_nwb(**session_to_nwb_kwargs)
    except Exception:
        exception_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(exception_file_path, "w") as f:
            f.write(f"session_to_nwb_kwargs:\n{pformat(session_to_nwb_kwargs)}\n\n")
            f.write(traceback.format_exc())


def get_session_to_nwb_kwargs_per_session(
    *,
    data_dir_path: Path | str,
    processed_dir_path: Path | str | None = None,
    include_sessions_on_hold: bool = False,
) -> list[dict]:
    """Discover all sessions and return per-session kwargs for ``session_to_nwb``.

    Expected directory structure::

        {data_dir_path}/{subject_id}/{YYYY_MM_DD}/

    A directory is recognised as a session if it contains ``Miniscope/`` or an
    Intan recording directory (``Intan/`` in the July sessions,
    ``{subject}_{YYMMDD}_{HHMMSS}`` afterwards).

    With ``processed_dir_path``, a session's published file is
    ``sub-{subject}/sub-{subject}_ses-{YYYYMMDD}T*_*.nwb`` with the session's date; a date with
    several published files raises, since the date alone cannot pick one.

    Sessions in ``SESSIONS_ON_HOLD`` are skipped unless ``include_sessions_on_hold`` is ``True``.

    Returns
    -------
    list[dict]
        Each dict has the key ``session_dir_path`` (and ``processed_nwbfile_path`` when a
        published file matches) and can be passed directly to ``session_to_nwb`` (after adding
        ``output_dir_path`` and ``stub_test``).
    """
    data_dir_path = Path(data_dir_path)
    kwargs_list = []

    for subject_dir in sorted(data_dir_path.iterdir()):
        if not subject_dir.is_dir() or subject_dir.name.startswith("."):
            continue
        for session_dir in sorted(subject_dir.iterdir()):
            if not session_dir.is_dir() or session_dir.name.startswith("."):
                continue
            if not _is_session_dir(session_dir):
                continue
            if not include_sessions_on_hold and (subject_dir.name, session_dir.name) in SESSIONS_ON_HOLD:
                continue
            kwargs = dict(session_dir_path=session_dir)
            if processed_dir_path is not None:
                date = session_dir.name.replace("_", "")
                published_dir = Path(processed_dir_path) / f"sub-{subject_dir.name}"
                matches = sorted(published_dir.glob(f"sub-{subject_dir.name}_ses-{date}T*_*.nwb"))
                if len(matches) > 1:
                    raise ValueError(f"Several published files match {session_dir}: {matches}")
                if matches:
                    kwargs["processed_nwbfile_path"] = matches[0]
            kwargs_list.append(kwargs)

    return kwargs_list


def _is_session_dir(path: Path) -> bool:
    """Return True if ``path`` looks like a session directory."""
    return (path / "Miniscope").is_dir() or _find_intan_dir(path) is not None


if __name__ == "__main__":
    dataset_to_nwb(
        data_dir_path=Path("~/source_data/peyrache-lab").expanduser(),
        output_dir_path=Path("~/nwb_output/peyrache").expanduser(),
        max_workers=1,
        stub_test=True,
        verbose=True,
    )
