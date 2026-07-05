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

Skip tracks that are already marked known-missing, even if the cache is expired:

```bash
lrcget /path/to/music --ignore-missing
```

Re-fetch known-missing tracks regardless of expiry:

```bash
lrcget /path/to/music --force-missing
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
