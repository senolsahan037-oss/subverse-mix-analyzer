from __future__ import annotations

import json
import shutil
import sys
import tempfile
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from subverse.archive_profiles import _download_source  # noqa: E402
from subverse.mix_analyzer import extract_mix_features  # noqa: E402
from subverse.analyzer import AudioDecodeError  # noqa: E402


def main() -> None:
    target = 100
    catalog = json.loads((ROOT / "subverse/data/genre_profiles.json").read_text())
    sources = []
    for profile in catalog["profiles"]:
        for source in profile.get("provenance", {}).get("sources", []):
            sources.append({**source, "genre": profile["name"]})
            if len(sources) >= target:
                break
        if len(sources) >= target:
            break

    report = {"requested": target, "selected": len(sources), "results": [], "errors": []}
    temp = Path(tempfile.mkdtemp(prefix="subverse-archive-batch-"))
    try:
        for index, source in enumerate(sources, 1):
            path = temp / f"{index}{Path(source['file_name']).suffix.lower()}"
            analysis_path = temp / f"{index}-analysis.wav"
            try:
                _download_source(source, path)
                trim = subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-i", str(path), "-t", "360", "-ar", "44100", "-ac", "2", str(analysis_path)],
                    check=False, capture_output=True, text=True, timeout=45,
                )
                if trim.returncode != 0:
                    raise RuntimeError(f"ffmpeg normalize failed: {trim.stderr[-300:]}")
                result = extract_mix_features(analysis_path, analysis_path.name)
                report["results"].append({
                    "index": index, "genre": source["genre"],
                    "identifier": source["identifier"],
                    "duration": result.get("duration_seconds"),
                    "state": result.get("state"),
                    "integrated_lufs": result.get("integrated_lufs"),
                    "true_peak_dbfs": result.get("true_peak_dbfs"),
                    "noise_floor_dbfs": result.get("noise_floor_dbfs"),
                    "tonal_map": result.get("tonal_map"),
                    "comparison_status": result.get("comparison_status"),
                })
            except AudioDecodeError as exc:
                report["errors"].append({"index": index, "id": source["identifier"], "type": "decode", "error": str(exc)})
            except Exception as exc:  # batch must continue and classify failures
                report["errors"].append({"index": index, "id": source["identifier"], "type": type(exc).__name__, "error": str(exc)})
            finally:
                path.unlink(missing_ok=True)
                analysis_path.unlink(missing_ok=True)
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    out = ROOT / "artifacts" / "archive_batch_test_100.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"report": str(out), "requested": target, "selected": len(sources), "analyzed": len(report["results"]), "errors": len(report["errors"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
