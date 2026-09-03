"""Mix analysis, provided by the shared `subverse_mix` engine (Loom/MixAnalyzer)."""
from subverse_mix import mix_analyzer as _engine
from subverse_mix.mix_analyzer import *  # noqa: F401,F403

# Private helpers the service's tests and profile builders reach into.
_master_genre_numeric_findings = _engine._master_genre_numeric_findings
_waveform_envelope = _engine._waveform_envelope
_spectral_bands = _engine._spectral_bands
_mono_compatibility = _engine._mono_compatibility
_genre_affinity = _engine._genre_affinity
_findings = _engine._findings
MIX_CONTRACT_VERSION = _engine.MIX_CONTRACT_VERSION
FINDING_POLICY_VERSION = _engine.FINDING_POLICY_VERSION
WAVEFORM_CONTRACT_VERSION = _engine.WAVEFORM_CONTRACT_VERSION
WAVEFORM_MAX_BINS = _engine.WAVEFORM_MAX_BINS
MONO_LOSS_DETECTION_THRESHOLD_DB = _engine.MONO_LOSS_DETECTION_THRESHOLD_DB
COMPARISON_METRICS = _engine.COMPARISON_METRICS
analyze_mix = _engine.analyze_mix
extract_mix_features = _engine.extract_mix_features
