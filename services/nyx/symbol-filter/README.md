# Symbol Filter

A tool for filtering symbol files based on source file patterns. This tool is designed to work with Mozilla Firefox symbol files, filtering them based on configurable include/exclude patterns stored in FuzzManager.

## Features

- Filter symbols by source file path patterns
- Support for wildcard patterns (`**` for multiple path segments, `*` for single segment)
- Integration with FuzzManager for remote filter configuration
- Automatic path resolution for both direct source paths and dist/include paths
- Last-match-wins semantics for include/exclude patterns

## Installation

```bash
uv sync
```

## Usage

```bash
usage: symbol-filter [-h] [--output OUTPUT] symbol_path filter_id

Filter symbols based on source file patterns

positional arguments:
  symbol_path                 Path to symbol file
  filter_id                   Fuzzmanager coverage report configuration ID

options:
  -h, --help                  show this help message and exit
  --output OUTPUT, -o OUTPUT  Output path
```

