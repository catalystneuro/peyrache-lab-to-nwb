"""Add the sleep state annotations to every session of DANDI:000939."""

from __future__ import annotations

import traceback
from pathlib import Path

from dandi.dandiapi import DandiAPIClient

from .convert_session import load_metadata, session_to_nwb


def get_asset_paths() -> list[str]:
    """Return the paths of the NWB assets in the Dandiset version named in ``metadata.yaml``."""
    dandiset_metadata = load_metadata()["Dandiset"]
    with DandiAPIClient() as client:
        dandiset = client.get_dandiset(dandiset_metadata["identifier"], dandiset_metadata["version"])
        return sorted(asset.path for asset in dandiset.get_assets() if asset.path.endswith(".nwb"))


def dataset_to_nwb(
    output_dir_path: str | Path,
    download_dir_path: str | Path,
    overwrite: bool = False,
    verbose: bool = True,
) -> None:
    """Run ``session_to_nwb`` on every session, one after another.

    A session that fails writes its traceback to ``{output_dir_path}/ERROR_{file name}.txt`` and the
    others continue. Sessions whose annotated file already exists are skipped unless ``overwrite``.
    """
    output_dir_path = Path(output_dir_path)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    asset_paths = get_asset_paths()
    for index, asset_path in enumerate(asset_paths, start=1):
        if verbose:
            print(f"[{index}/{len(asset_paths)}] {asset_path}")
        if (output_dir_path / asset_path).exists() and not overwrite:
            if verbose:
                print("  annotated file exists, skipping")
            continue
        exception_file_path = output_dir_path / f"ERROR_{Path(asset_path).stem}.txt"
        try:
            session_to_nwb(
                asset_path=asset_path,
                output_dir_path=output_dir_path,
                download_dir_path=download_dir_path,
                overwrite=overwrite,
                verbose=verbose,
            )
            exception_file_path.unlink(missing_ok=True)
        except Exception:
            exception_file_path.write_text(traceback.format_exc())
            if verbose:
                print(f"  failed, see {exception_file_path}")


if __name__ == "__main__":
    dataset_to_nwb(
        output_dir_path=Path("/Volumes/T9/nwb_output/dandi_000939"),
        download_dir_path=Path("/Volumes/T9/source_data/dandi/000939"),
    )
