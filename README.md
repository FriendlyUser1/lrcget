# lrcget

Fetch synced lyrics from LRCLIB and write `.lrc` files next to your local audio files.

## Install

### With uv (recommended)

```bash
uv sync
```

### With pip

```bash
python -m pip install .
```

## Usage

After installation, run the console command:

```bash
lrcget /path/to/music
```

Enable verbose logs:

```bash
lrcget /path/to/music --verbose
```

You can also run it as a module:

```bash
python -m lrcget /path/to/music
```

## Supported audio files

- `.mp3`
- `.opus`
- `.flac`
- `.ogg`
- `.wav`
