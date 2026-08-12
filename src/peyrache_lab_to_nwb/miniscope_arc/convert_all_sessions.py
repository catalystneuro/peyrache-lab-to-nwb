"""Batch conversion of all Peyrache Lab miniscope_arc sessions."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from pprint import pformat
from typing import Optional
import traceback

from tqdm import tqdm

from .convert_session import session_to_nwb


def dataset_to_nwb(
    *,
    data_dir_path: str | Path,
    output_dir_path: str | Path,
    max_workers: int = 1,
    stub_test: bool = False,
    verbose: bool = False,
) -> None:
    """Convert all sessions in the dataset to NWB.

    Discovers sessions by iterating over the directory tree::

        {data_dir_path}/
        └── {subject_id}/
            └── {YYYY_MM_DD}/    ← session directory

    A directory is treated as a session if it contains a ``Miniscope`` or
    ``Intan`` sub-directory.

    Parameters
    ----------
    data_dir_path
        Root of the source data (e.g. ``~/source_data/peyrache-lab/``).
    output_dir_path
        Root directory for output NWB files.
    max_workers
        Number of parallel workers (default 1 = sequential).
    stub_test
        If ``True``, write short stub files only.
    verbose
        If ``True``, print per-session progress.
    """
    data_dir_path = Path(data_dir_path)
    output_dir_path = Path(output_dir_path)

    kwargs_per_session = get_session_to_nwb_kwargs_per_session(data_dir_path=data_dir_path)

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
) -> list[dict]:
    """Discover all sessions and return per-session kwargs for ``session_to_nwb``.

    Expected directory structure::

        {data_dir_path}/{subject_id}/{YYYY_MM_DD}/

    A directory is recognised as a session if it contains ``Miniscope/`` or
    ``Intan/``.

    Returns
    -------
    list[dict]
        Each dict has the key ``session_dir_path`` and can be passed directly
        to ``session_to_nwb`` (after adding ``output_dir_path`` and ``stub_test``).
    """
    data_dir_path = Path(data_dir_path)
    kwargs_list = []

    for subject_dir in sorted(data_dir_path.iterdir()):
        if not subject_dir.is_dir() or subject_dir.name.startswith("."):
            continue
        for session_dir in sorted(subject_dir.iterdir()):
            if not session_dir.is_dir() or session_dir.name.startswith("."):
                continue
            if _is_session_dir(session_dir):
                kwargs_list.append(dict(session_dir_path=session_dir))

    return kwargs_list


def _is_session_dir(path: Path) -> bool:
    """Return True if ``path`` looks like a session directory."""
    return (path / "Miniscope").is_dir() or (path / "Intan").is_dir()


if __name__ == "__main__":
    dataset_to_nwb(
        data_dir_path=Path("~/source_data/peyrache-lab").expanduser(),
        output_dir_path=Path("~/nwb_output/peyrache").expanduser(),
        max_workers=1,
        stub_test=True,
        verbose=True,
    )
