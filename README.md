# MATLAB to HDF5 Converter

Python utility for converting batches of MATLAB `.mat` waveform files into HDF5 files. This was built for continuous waveform data, such as partial discharge measurements, that are split across many MATLAB files.

## What It Does

- Converts one `.mat` file, a folder of `.mat` files, or nested folders of `.mat` files.
- Preserves each source file as its own HDF5 group when creating a combined output file.
- Supports numeric arrays, strings, nested MATLAB structs, object arrays, and MATLAB v7.3 files.
- Keeps generated waveform data out of git through `.gitignore`.

## Install

Use Python 3.10 or newer.

```powershell
pip install -r requirements.txt
```

Dependencies:

- `numpy`
- `scipy`
- `h5py`

## Convert All Files Into One HDF5 File

From the project folder:

```powershell
python convert_mat_to_hdf5.py "." "waveforms.h5" --recursive --overwrite
```

This creates:

```text
waveforms.h5
```

Inside the HDF5 file, each MATLAB file is stored under:

```text
/files/<mat_file_name>/
```

Example:

```text
/files/Aq_20260413_152904_5/
```

## Convert One MATLAB File

```powershell
python convert_mat_to_hdf5.py "path\to\input.mat" "path\to\output.h5" --overwrite
```

## Convert Folder Recursively

```powershell
python convert_mat_to_hdf5.py "path\to\mat_folder" "output.h5" --recursive --overwrite
```

## Convert Each `.mat` Into Its Own `.h5`

To create one `.h5` file beside every `.mat` file:

```powershell
python -c "from pathlib import Path; import convert_mat_to_hdf5 as c; mat_files = c.collect_mat_files(Path('.'), True); [c.convert_files([p], p.with_suffix('.h5'), None, set(), 'gzip') for p in mat_files]"
```

Example:

```text
Corona discharges\Aq_20260413_152904_5.mat
Corona discharges\Aq_20260413_152904_5.h5
```

## Useful Options

Include only specific MATLAB variables:

```powershell
python convert_mat_to_hdf5.py "." "waveforms.h5" --recursive --include waveform fs labels --overwrite
```

Exclude variables:

```powershell
python convert_mat_to_hdf5.py "." "waveforms.h5" --recursive --exclude debug_notes raw_metadata --overwrite
```

Change compression:

```powershell
python convert_mat_to_hdf5.py "." "waveforms.h5" --recursive --compression lzf --overwrite
```

Available compression options:

- `gzip`: smaller files, slower writes
- `lzf`: faster writes, moderate compression
- `none`: fastest writes, largest files

## Output Layout

Combined output:

```text
waveforms.h5
└── files
    ├── Aq_20260413_152904_1
    │   ├── <matlab_variable>
    │   └── ...
    └── Aq_20260413_152904_5
        ├── <matlab_variable>
        └── ...
```

Each file group includes metadata attributes:

- `source_path`
- `source_file`
- `variable_count`
- `matlab_version`

## Notes

Large waveform data files are intentionally ignored by git:

- `.mat`
- `.h5`
- `.hdf5`
- dataset log files

Keep the raw MATLAB data and generated HDF5 files locally, and commit only the converter code and documentation.
