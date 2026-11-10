"""Add HED annotations and ontology links to the sleep scoring of one DANDI:000939 session.

The session's published NWB file is downloaded from DANDI and read, the annotations are added in memory,
and the result is exported to a new file with the same name in the output directory. The new file gets:

- ``HedLabMetaData`` with the HED schema versions (ndx-hed),
- a ``MeaningsTable`` named ``state_meanings`` bound to the ``state`` column of
  ``/intervals/sleep_states``, with a written meaning and a ``HED`` annotation per state,
- HERD references (``/general/external_resources``) from each state to a Neuro Behavior Ontology term.

The ``sleep_states`` columns and rows and all other data are copied unchanged. The new file caches only the
schema versions of the installed PyNWB and ndx-hed. The downloaded file is only read.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from dandi.dandiapi import DandiAPIClient
from hdmf.common import HERD, MeaningsTable
from ndx_hed import HedLabMetaData, HedTags
from ndx_hed.utils.hed_nwb_validator import HedNWBValidator
from pynwb import NWBHDF5IO, NWBFile, get_type_map

METADATA_FILE_PATH = Path(__file__).parent / "metadata.yaml"

SLEEP_STATES_TABLE_NAME = "sleep_states"
SLEEP_STATE_COLUMN_NAME = "state"


def load_metadata() -> dict:
    """Read ``metadata.yaml``."""
    with open(METADATA_FILE_PATH) as file:
        return yaml.safe_load(file)


def download_session(asset_path: str, download_dir_path: str | Path, metadata: dict) -> Path:
    """Download one asset of the Dandiset version in ``metadata`` to ``{download_dir_path}/{asset_path}``.

    A file already at that path with the asset's size is reused.
    """
    file_path = Path(download_dir_path) / asset_path
    dandiset_metadata = metadata["Dandiset"]
    with DandiAPIClient() as client:
        dandiset = client.get_dandiset(dandiset_metadata["identifier"], dandiset_metadata["version"])
        asset = dandiset.get_asset_by_path(asset_path)
        if file_path.is_file() and file_path.stat().st_size == asset.size:
            return file_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        asset.download(file_path)
    return file_path


def add_sleep_state_meanings(nwbfile: NWBFile, metadata: dict, type_map=None) -> None:
    """Add HedLabMetaData, the ``state_meanings`` MeaningsTable and its HERD references to ``nwbfile``.

    ``type_map`` resolves the annotated objects for HERD. Pass the reading IO's ``io.manager.type_map``
    for a file read from disk; for an in-memory file it defaults to PyNWB's.
    """
    meanings_metadata = metadata["SleepStateMeanings"]
    states = meanings_metadata["states"]

    sleep_states = nwbfile.intervals[SLEEP_STATES_TABLE_NAME]
    state_column = sleep_states[SLEEP_STATE_COLUMN_NAME]
    values_in_file = set(state_column[:])
    if values_in_file != set(states):
        raise ValueError(
            f"The '{SLEEP_STATE_COLUMN_NAME}' column holds {sorted(values_in_file)}, "
            f"but the metadata defines {sorted(states)}."
        )
    if nwbfile.external_resources is not None:
        raise ValueError("The file already has external resources (HERD), which cannot be extended on disk.")

    hed_lab_metadata = HedLabMetaData(hed_schema_version=metadata["HedLabMetaData"]["hed_schema_version"])
    nwbfile.add_lab_meta_data(hed_lab_metadata)

    meanings = MeaningsTable(target=state_column, description=meanings_metadata["description"])
    meanings.add_column(name="HED", description=meanings_metadata["hed_description"], col_cls=HedTags)
    for value, state in states.items():
        meanings.add_row(value=value, meaning=state["meaning"], HED=state["HED"])
    sleep_states.add_meanings_table(meanings)

    issues = HedNWBValidator(hed_lab_metadata).validate_file(nwbfile)
    if issues:
        raise ValueError(f"HED validation found {len(issues)} issues: {issues}")

    herd = HERD(type_map=type_map if type_map is not None else get_type_map())
    for value, state in states.items():
        term = state["ontology_term"]
        herd.add_ref(container=meanings["value"], key=value, entity_id=term["id"], entity_uri=term["uri"])
    nwbfile.external_resources = herd


def export_with_sleep_state_meanings(source_file_path: str | Path, output_file_path: str | Path, metadata: dict) -> None:
    """Read ``source_file_path``, add the sleep state annotations and export the result to ``output_file_path``.

    The export copies all data (no links to the source file) and caches only the current schema versions.
    """
    with NWBHDF5IO(source_file_path, mode="r") as read_io:
        nwbfile = read_io.read()
        add_sleep_state_meanings(nwbfile, metadata, type_map=read_io.manager.type_map)
        with NWBHDF5IO(output_file_path, mode="w") as export_io:
            export_io.export(src_io=read_io, nwbfile=nwbfile, write_args={"link_data": False})


def session_to_nwb(
    asset_path: str,
    output_dir_path: str | Path,
    download_dir_path: str | Path,
    overwrite: bool = False,
    verbose: bool = True,
) -> Path:
    """Download one DANDI:000939 session and export it, with the sleep state annotations, to a new file.

    The export copies all data and caches only the current schema versions. Appending to the published file
    in place would cache them next to the file's older versions (core 2.9.0, hdmf-common 1.8.0), and tools
    that load the cached schemas then fail to read the file.

    Parameters
    ----------
    asset_path
        Path of the asset in the Dandiset, e.g. ``"sub-A1821/sub-A1821_ses-190910_behavior+ecephys+ogen.nwb"``.
    output_dir_path
        The annotated file is written to ``{output_dir_path}/{asset_path}``, the Dandiset layout.
    download_dir_path
        The published file is downloaded to ``{download_dir_path}/{asset_path}`` and only read.
    overwrite
        Replace an existing annotated file. Without it, an existing file raises ``FileExistsError``.

    Returns
    -------
    The path of the annotated file.
    """
    metadata = load_metadata()
    output_file_path = Path(output_dir_path) / asset_path
    if output_file_path.exists() and not overwrite:
        raise FileExistsError(f"{output_file_path} exists. Pass overwrite=True to replace it.")

    if verbose:
        print(f"Downloading {asset_path}")
    downloaded_file_path = download_session(asset_path, download_dir_path, metadata)

    output_file_path.parent.mkdir(parents=True, exist_ok=True)
    output_file_path.unlink(missing_ok=True)
    try:
        export_with_sleep_state_meanings(downloaded_file_path, output_file_path, metadata)
    except Exception:
        output_file_path.unlink(missing_ok=True)
        raise

    if verbose:
        print(f"Wrote {output_file_path}")
    return output_file_path


if __name__ == "__main__":
    session_to_nwb(
        asset_path="sub-A1821/sub-A1821_ses-190910_behavior+ecephys+ogen.nwb",
        output_dir_path=Path("~/nwb_output/dandi_000939").expanduser(),
        download_dir_path=Path("~/source_data/dandi/000939").expanduser(),
        overwrite=True,
    )
