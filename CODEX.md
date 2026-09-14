# Mix Check — Codex Handoff

## Current lock

**Reference state:** 2026-08-24 · cockpit UI + measurement upgrade core

This state is temporarily locked for review. Do not add new measurement behavior, change comparison thresholds, regenerate profiles, or alter the brand palette without recording the change below and updating the regression tests.

## Implemented baseline

- Website-owned membership handoff; no tool-local sign-in screen.
- Cockpit UI and SubverseLab brand palette.
- Brand-aligned waveform channels: L gold, R mint.
- RMS-referenced spectral shape comparison; LUFS is not mixed into PSD dBFS math.
- Adaptive spectral activity floor for sparse and narrow-band material.
- `active_common` / `inactive` comparison status in spectral deltas.
- 12 pitch-class tonal energy map with dominant tonal lead and confidence.
- Reference and gain-invariance regression coverage.
- Current verification: 61 tests passing.

## Known nuances to resolve next

1. Tonal map is descriptive pitch-class energy, not key/chord detection. Validate against minor keys, modal material, vocals, bass-only tracks, and per-section tonal changes.
2. Adaptive gating needs a calibrated noise-floor model for mastered silence, fades, intros, and intentionally sparse arrangements.
3. Existing genre profiles may have been generated under the older spectral reference behavior. Rebuild and version them before using genre affinity as a stable comparison.
4. A single track-level RMS reference can still hide transient-heavy or section-specific spectral differences. Add section-aware aggregation with minimum-duration and confidence rules.
5. `comparison_status` is now exposed in the backend schema; the UI should explain inactive bands instead of silently omitting them.
6. Add golden audio fixtures for: gain-only change, bass-heavy, bright, mid-forward, sparse/ambient, full-range, mono-safe, antiphase, and tonal modulation cases.
7. Keep the tool dependent on the website auth handoff. Do not reintroduce Firebase sign-in controls inside the tool.

## Next upgrade gate

Unlock only after the above fixtures and profile rebuild pass. The next package is:

- calibrated noise-floor and confidence bands;
- section-aware spectral and tonal aggregation;
- versioned reference/profile rebuild;
- scenario presets with explicit analysis scope;
- UI disclosure for inactive, low-confidence, and unsupported measurements.

## Change log

- 2026-08-24: Locked the current cockpit and measurement-upgrade baseline for review.
- 2026-08-25: Added measured noise-floor metadata and four coarse section summaries with per-section tonal leads. Genre profile rebuild remains blocked until the original source tracks are supplied.
- 2026-08-25: Tonal output now includes major/minor key and triad candidates with confidence context; these remain listening leads, not authoritative key/chord labels.
- 2026-08-25: Access contract aligned with Launchpad: website-owned member identity, one completed analysis per IP per UTC day for members, and no product quota for server-verified admins. Local development remains quota-free only when `AUTH_REQUIRED=false`.
- 2026-08-25: Replaced the legacy cover with a dark ink/teal/gold evidence-first signal visual and added a native SVG favicon. Production sync remains gated on Launchpad certification and post-deploy verification.
- 2026-09-13: Measured on the user's own masters: the nearest-profile guidance was wrong info. Cause 1: affinity distance was divided by each profile's IQR width, so the most heterogeneous profile (Metal: an audiobook, solo piano, sludge rips) was "nearest" to every track. Cause 2: the Internet Archive catalog is contaminated (LibriVox audiobooks in Jazz/Metal, 15 items shared across genres). Fix: distance is now RMS dB from the profile median; a profile is used as a correction target only when it leads by ≥ 1.0 dB (`closest_profile_status`), otherwise the result stays descriptive. Jazz and Metal removed from the catalog. `finding_policy_version` → `2026-09-13.findings.3`. On the user's six masters every case is now `ambiguous` with the current catalog, which is the honest answer; a curated profile rebuild is required before reference-free guidance returns.
- 2026-09-14: Catalog rebuilt from well-known released masters (engine `subverse_mix.reference_profiles`, list in `data/reference_tracks.json`): Hip-Hop 18, Trap 19, Electronic 19, Pop 20, Rock 19 sources, resolved to artist/label YouTube uploads, measured, audio deleted; plus the pooled "Released masters (all genres)" profile (`role: pooled`). Measured on the user's six masters: genre profiles sit 1.5–5.8 dB apart from each other, but the user's tracks are 4–7 dB from all of them, so nearest-genre stays `ambiguous`; the engine now falls back to the pooled profile (`mode: pooled`) instead of going silent. Explicitly selected Hip-Hop/Trap comparisons now produce concrete findings (e.g. Trap Glissando: −16.8 LUFS vs −9.6 median, crest 20.8 vs 11.1, sub −9 dB, highs +8 dB).

