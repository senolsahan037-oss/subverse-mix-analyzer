# Subverse Mix Analyzer

Local AI-assisted mix/mastering analyzer.

## MVP
- Upload WAV/MP3
- Analyze LUFS, peak, RMS, crest factor
- Frequency band balance
- Stereo correlation
- Return JSON report
- Simple web UI

## Run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Docker
```bash
docker compose up --build
```

Frontend:

```text
http://localhost:5500
```

Backend docs:

```text
http://localhost:8000/docs
```

For LAN access from another device on the same network, open:

```text
http://<your-host-lan-ip>:5500
```

Notes:
- The frontend serves the static UI on port `5500`.
- The frontend proxies `/analyze` to the backend service over Docker networking.
- The backend is also published on port `8000` for direct API access if needed.
- No frontend host IP or `127.0.0.1` backend address is hardcoded.
- Upload and analyze requests go through the frontend on port `5500`, so LAN clients work without changing the browser-side API URL.

## Test
```bash
pytest
```
