# Subverse Mix Analyzer

Local, rule-based mix/mastering analyzer.

## MVP
- Upload WAV/MP3
- Analyze BS.1770 integrated LUFS, sample/true peak, RMS, crest factor and dynamic-range spread
- Frequency band balance
- Stereo correlation
- Mono fold-down loss and stereo mid/side measurements
- Return JSON report
- Simple web UI

The current report is rule-based. There is no external AI model call in this version.

True peak is measured with 4× sample-rate oversampling. `dynamic_range_db` is the 95th–10th percentile spread of audible one-second RMS windows, so it is a repeatable mix-dynamics measurement rather than an EBU LRA value. Stereo analysis reports mid/side energy and the level loss created by an L/R mono fold-down.

## Analysis states

- `ok`: the file was analyzed normally.
- `silent`: the file contains no measurable audio; level and tonal metrics are returned for transparency but are not meaningful for mix decisions.
- `too_short`: the file is shorter than the configured minimum analysis duration; the returned mix metrics are not reliable.

## Configuration

These backend environment variables are optional:

- `MAX_UPLOAD_BYTES` — maximum accepted upload size; default `104857600` (100 MiB).
- `MAX_ANALYSIS_SECONDS` — maximum decoded audio duration; default `1800` seconds.
- `UPLOAD_CHUNK_BYTES` — upload read chunk size; default `1048576` bytes.
- `MIN_ANALYSIS_SECONDS` — duration below which the response is marked `too_short`; default `0.5` seconds.

## Run
```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m uvicorn backend.app.main:app --reload
```

Open `http://127.0.0.1:8000`.

Backend docs:

```text
http://localhost:8000/docs
```

## Test
```bash
pytest -q
```
