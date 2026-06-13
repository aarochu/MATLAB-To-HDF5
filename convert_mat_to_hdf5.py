#!/usr/bin/env python3
"""Convert batches of MATLAB .mat waveform files into one HDF5 file.

The output layout is:

    /files/<mat_file_stem>/
        attrs: source_path, source_file
        <matlab_variable_name> -> HDF5 dataset or nested group

This keeps each source file separate, which is usually the safest first step
for continuous waveform data split across many MATLAB files.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import h5py
import numpy as np
from scipy.io import loadmat


MATLAB_METADATA_KEYS = {"__header__", "__version__", "__globals__"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert one or many MATLAB .mat files into a single HDF5 file."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="A .mat file or a directory containing .mat files.",
    )
    parser.add_argument(
        "output",
        type=Path,
        help="Destination .h5/.hdf5 file.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search input directories recursively.",
    )
    parser.add_argument(
        "--include",
        nargs="*",
        default=None,
        help="Optional MATLAB variable names to include. Defaults to all variables.",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        help="MATLAB variable names to skip.",
    )
    parser.add_argument(
        "--compression",
        default="gzip",
        choices=["gzip", "lzf", "none"],
        help="HDF5 dataset compression. Use 'none' for fastest writes.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )
    return parser.parse_args()


def collect_mat_files(input_path: Path, recursive: bool) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() != ".mat":
            raise ValueError(f"Input file is not a .mat file: {input_path}")
        return [input_path]

    if not input_path.is_dir():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")

    pattern = "**/*.mat" if recursive else "*.mat"
    files = sorted(input_path.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No .mat files found in {input_path}")
    return files


def safe_hdf5_name(name: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_.-]+", "_", name.strip())
    return cleaned or "unnamed"


def unique_group_name(parent: h5py.Group, desired: str) -> str:
    base = safe_hdf5_name(desired)
    if base not in parent:
        return base

    index = 2
    while f"{base}_{index}" in parent:
        index += 1
    return f"{base}_{index}"


def should_write_variable(name: str, include: set[str] | None, exclude: set[str]) -> bool:
    if name in MATLAB_METADATA_KEYS or name.startswith("__"):
        return False
    if include is not None and name not in include:
        return False
    return name not in exclude


def dataset_kwargs(array: np.ndarray, compression: str) -> dict[str, Any]:
    if compression == "none" or array.shape == ():
        return {}
    return {"compression": compression, "shuffle": True}


def write_value(
    h5_group: h5py.Group,
    name: str,
    value: Any,
    compression: str,
) -> None:
    """Write MATLAB values recursively into HDF5 datasets/groups."""
    h5_name = safe_hdf5_name(name)

    if hasattr(value, "_fieldnames"):
        subgroup = h5_group.create_group(h5_name)
        for field_name in value._fieldnames:
            write_value(subgroup, field_name, getattr(value, field_name), compression)
        return

    if isinstance(value, dict):
        subgroup = h5_group.create_group(h5_name)
        for child_name, child_value in value.items():
            if child_name.startswith("__"):
                continue
            write_value(subgroup, str(child_name), child_value, compression)
        return

    if isinstance(value, np.void) and value.dtype.names:
        subgroup = h5_group.create_group(h5_name)
        for field_name in value.dtype.names:
            write_value(subgroup, field_name, value[field_name], compression)
        return

    if isinstance(value, np.ndarray) and value.dtype.names:
        subgroup = h5_group.create_group(h5_name)
        if value.shape:
            subgroup.attrs["matlab_shape"] = value.shape
        for field_name in value.dtype.names:
            write_value(subgroup, field_name, value[field_name], compression)
        return

    if isinstance(value, np.ndarray) and value.dtype == object:
        subgroup = h5_group.create_group(h5_name)
        subgroup.attrs["matlab_shape"] = value.shape
        for index, item in np.ndenumerate(value):
            child_name = "item_" + "_".join(str(i) for i in index)
            write_value(subgroup, child_name, item, compression)
        return

    array = np.asarray(value)
    if array.dtype.kind in {"U", "O"}:
        if array.shape == ():
            string_value = str(array.item())
        else:
            string_value = np.vectorize(str, otypes=[object])(array)
        h5_group.create_dataset(h5_name, data=string_value, dtype=h5py.string_dtype())
        return

    h5_group.create_dataset(
        h5_name,
        data=array,
        **dataset_kwargs(array, compression),
    )


def load_mat_file(path: Path) -> dict[str, Any]:
    return loadmat(path, squeeze_me=True, struct_as_record=False)


def copy_hdf5_item(
    source_item: h5py.Dataset | h5py.Group,
    target_group: h5py.Group,
    name: str,
    include: set[str] | None,
    exclude: set[str],
) -> int:
    if not should_write_variable(name, include, exclude):
        return 0

    h5_name = safe_hdf5_name(name)
    source_item.file.copy(source_item.name, target_group, name=h5_name)
    return 1


def copy_v73_mat_file(
    mat_path: Path,
    file_group: h5py.Group,
    include: set[str] | None,
    exclude: set[str],
) -> int:
    copied_variables = 0
    file_group.attrs["matlab_version"] = "7.3"

    with h5py.File(mat_path, "r") as source_h5:
        for variable_name, source_item in source_h5.items():
            copied_variables += copy_hdf5_item(
                source_item=source_item,
                target_group=file_group,
                name=variable_name,
                include=include,
                exclude=exclude,
            )

    return copied_variables


def convert_files(
    mat_files: Iterable[Path],
    output_path: Path,
    include: set[str] | None,
    exclude: set[str],
    compression: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    h5_compression = "none" if compression == "none" else compression

    with h5py.File(output_path, "w") as h5:
        h5.attrs["format"] = "MATLAB waveform batch conversion"
        h5.attrs["source_file_count"] = 0

        files_group = h5.create_group("files")
        written_files = 0

        for mat_path in mat_files:
            print(f"Converting {mat_path}")
            file_group_name = unique_group_name(files_group, mat_path.stem)
            file_group = files_group.create_group(file_group_name)
            file_group.attrs["source_path"] = str(mat_path.resolve())
            file_group.attrs["source_file"] = mat_path.name

            try:
                mat_data = load_mat_file(mat_path)
                file_group.attrs["matlab_version"] = "pre-7.3"
                written_variables = 0
                for variable_name, value in mat_data.items():
                    if not should_write_variable(variable_name, include, exclude):
                        continue
                    write_value(file_group, variable_name, value, h5_compression)
                    written_variables += 1
            except NotImplementedError:
                written_variables = copy_v73_mat_file(
                    mat_path=mat_path,
                    file_group=file_group,
                    include=include,
                    exclude=exclude,
                )

            file_group.attrs["variable_count"] = written_variables
            written_files += 1

        h5.attrs["source_file_count"] = written_files


def main() -> int:
    args = parse_args()
    output_path = args.output

    if output_path.exists() and not args.overwrite:
        print(
            f"Output already exists: {output_path}. Use --overwrite to replace it.",
            file=sys.stderr,
        )
        return 2

    include = set(args.include) if args.include else None
    exclude = set(args.exclude)

    try:
        mat_files = collect_mat_files(args.input, args.recursive)
        convert_files(
            mat_files=mat_files,
            output_path=output_path,
            include=include,
            exclude=exclude,
            compression=args.compression,
        )
    except Exception as exc:
        print(f"Conversion failed: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {len(mat_files)} MATLAB file(s) to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
