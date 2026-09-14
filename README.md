# Subverse Signal and Mix Measurement API

Local, minimal audio measurement service.

## Web interface

The FastAPI service serves the dependency-free Mix Check interface at `/`.
It uses the same origin as the measurement API, so it needs no separate
frontend server, build process or runtime storage service. The primary flow is
track upload, Mix/Master stage and optional genre. Reference upload remains
under the optional advanced section. All user-facing interface copy is English;
standard audio terms and SubverseLab product names are kept in their native
technical form.

The result view is a measurement console rather than a score dashboard. It
shows the decoded waveform first, followed by direct signal measurements,
one-third-octave spectrum, Mono Fold-down data, and evidence-backed
interpretation. Profile proximity, comparison policy, limitations, and raw JSON
remain available as secondary disclosures.

### Waveform visualization contract

Mix analysis includes a separately versioned waveform visualization payload.
It is derived from the exact decoded signal used by the measurement engine:

- Up to 1,200 uniform time bins
- Raw per-bin sample minimum and maximum for every channel
- No peak normalization, smoothing, or visual gain
- Linear sample amplitude preserved

The full sample stream is never serialized. The envelope preserves transient
extent while keeping the response bounded, and it does not change any retained
measurement or Genre Profile contract.

## Measurement contract

The service returns one canonical value for each retained measurement:

- File duration, sample rate and channel count
- Sample peak in dBFS
- RMS level in dBFS
- Crest factor in dB
- ITU-R BS.1770 gated integrated loudness through `pyloudnorm`
- Per-channel sample peak, RMS and arithmetic DC offset

Sample peak, RMS, crest factor and DC offset are direct signal calculations.
Integrated loudness is delegated to `pyloudnorm`; the service does not maintain
a second loudness implementation.

Zero amplitude has no finite dBFS representation, so silent level fields are
returned as `null` rather than being replaced with an artificial dB floor.
Integrated loudness is also `null` when the signal is silent, shorter than one
400 ms loudness block, or has more channels than `pyloudnorm` supports.

## Deliberately excluded

The service does not return custom or insufficiently verified mix metrics:

- Estimated true peak or clipping guesses
- Momentary/short-term timelines or a custom Loudness Range implementation
- Universal tonal-balance scores or resonance opinions
- Stereo correlation, Mid/Side ratios or mono compatibility scores
- Silence ratios, quality grades, genre targets or delivery profiles
- BPM, key, producer recommendations or AI-generated findings

These measurements can be added only when they have a clear definition,
independent validation and a distinct contribution to the report.

## Stage-aware mix and master analysis

`POST /analyze/track` accepts:

- `file` — required WAV or MP3 track
- `analysis_stage` — `mix` or `master`; defaults to `mix`
- `genre` — optional measured genre-profile id
- `use_closest_profile` — optional boolean; enables nearest-profile guidance
  when neither a genre nor reference is supplied
- `reference` — optional WAV or MP3 reference track
- `reference_stage` — required as `mix` or `master` with a reference

`POST /analyze/mix` remains as a compatibility alias. The primary UI can keep
the stage and genre selectors visible while treating reference upload as an
optional advanced control.

The service never guesses whether a file is a mix or master. The user-declared
state is returned as `analysis_stage` and `reference_stage`. A submitted
reference is the recommendation basis; a selected genre remains response
context but does not override it. Without a reference, a selected genre profile
is used. When neither is supplied, API callers may explicitly enable
`use_closest_profile`; the web interface enables it by default. The nearest
stored profile is used as optional guidance **only when it is clearly
nearest**: every response carries `genre_affinity`, ranked by technical
distance in dB, and `closest_profile_status` (`clear`, `ambiguous`,
`unavailable` or `not_requested`). The nearest profile must lead the runner-up
by at least 1.0 dB (`separation_db`); otherwise the ranking is still shown and
the track is compared with the pooled profile instead (`mode: pooled`,
`recommendation_basis: pooled_profile`): "Released masters (all genres)",
built from every reference master of every genre profile (`role: pooled`, never
part of the genre ranking). Without a pooled profile in the catalog the result
stays descriptive. This
is not genre classification or a quality verdict. If closest-profile guidance
is disabled, the result remains descriptive; a directly measured mono-loss
finding may still be reported.

The affinity distance is the RMS difference in dB between the track's
loudness-relative one-third-octave bands and the profile medians (plus, for
masters, the mean absolute difference of the released-master metrics). It is
deliberately **not** divided by the profile's interquartile width: a profile
built from heterogeneous sources has a wide spread, and a spread-normalised
distance made such a profile look nearest to every track. The share of bands
that fall inside the profile's p25–p75 range is reported separately as
`bands_within_range_share`.

| Policy | Compared metrics |
| --- | --- |
| mix → mix | Loudness-relative spectrum, crest factor, channel balance |
| mix → master | Loudness-relative spectrum |
| master → mix | Loudness-relative spectrum |
| master → master | Spectrum, integrated LUFS, sample peak, crest factor, channel balance |
| mix → genre | Loudness-relative spectrum |
| master → genre | The full master metric set above |

Every response exposes `comparison_policy`, `compared_metrics` and
`excluded_metrics`. Each exclusion contains its reason. Genre numeric
comparisons expose the subject value, genre median, 25th/75th percentiles and
whether the subject lies outside the interquartile range. The interquartile
range is context, not a fault boundary. A numeric Master finding is generated
only beyond the conservative outer fence `p25 - 1.5 × IQR` to
`p75 + 1.5 × IQR`; a zero-width distribution produces no numeric advice.
Recommendation behavior is versioned separately as `finding_policy_version`,
so policy changes do not invalidate the retained measurement profile contract.

Track analysis uses per-channel mean Welch power spectral density on fixed
one-third-octave center bands. Band levels are expressed relative to each
track's integrated loudness before comparison, so level differences do not
masquerade as tonal differences.

The response separates:

- Direct measurements
- Loudness-relative spectral deltas
- Evidence-backed observations
- Possible meaning
- A listening verification step
- A small, reversible experiment
- Explicit limitations

The L/R long-term RMS difference is returned only as a direct measurement. It
is not labeled safe, faulty or balanced: the value cannot describe instrument
balance inside a DAW, stereo width, pan movement, phase behavior or mono
compatibility.

Mono translation is measured separately by creating `M = (L + R) / 2` and
comparing its power with the mean L/R channel power in one-third-octave bands.
A loss region is reported only when at least two adjacent active bands lose
4 dB or more; bands more than 40 dB below the strongest band are ignored. This
can locate L/R cancellation or strong decorrelation by frequency, but cannot
identify an instrument or prove masking. A clean result means no material
fold-down loss was detected by this measurement; it is not a universal mix
quality score.

The measurement math is identical in Mix and Master modes, while the
verification path is stage-aware. Mix findings point to source/bus phase and
stereo processing. Master findings ask for a loudness-matched premaster
comparison and master-chain M/S or width bypass checks; if the loss is already
present in the premaster, the tool recommends considering a mix revision
instead of forcing a heavy mastering repair.

Comparative recommendations require a reference or measured genre profile and
a measured difference that crosses the documented finding criteria. A direct
mono-loss finding can still provide a listening check and reversible experiment
without either comparison source. Mix findings lead with source/arrangement
checks; master findings use small, reversible experiments. The service never
claims that an absolute spectral shape is good or bad, and it never attributes
a stereo-file difference to a specific instrument.

Reference comparisons summarize each full track; they do not align song
sections. References should use the same arrangement or a closely matching
section where possible, otherwise arrangement differences can dominate the
reported spectral delta.

`GET /mix/genres` returns the genre profiles available to a frontend selector.
The bundled catalog contains Hip-Hop, Trap, Electronic, Pop and Rock profiles,
each built from 20 of the most widely known released masters of the genre, plus
the pooled "Released masters (all genres)" profile over all of them (see
"Building genre profiles"; `--pooled` builds the pooled one). The previous Internet Archive catalog was
withdrawn on 2026-09-13 after its "Jazz" and "Metal" profiles turned out to
contain LibriVox audiobooks and poetry readings.

### Building genre profiles

The shipped catalog is built by the shared engine from a hand-picked list of
the most widely known released masters per genre
(`subverse_mix/data/reference_tracks.json` in Loom/MixAnalyzer: 20 tracks each
for Hip-Hop, Trap, Electronic, Pop and Rock). The builder searches YouTube with
yt-dlp, accepts only the artist's own channel or the label's auto-generated
"Topic" upload (never a lyric video, remix, live take or re-upload), measures
the audio locally and deletes it. The catalog keeps only the aggregate
distributions and the provenance list (artist, title, year, video id, channel,
match kind):

```bash
python3 -m subverse_mix.reference_profiles \
  --catalog subverse_mix/data/genre_profiles.json \
  --genres hiphop trap electronic pop rock \
  --work-dir /tmp/reference-profiles
```

`--inspect` resolves the uploads without downloading. A profile still needs
at least three sources; the builder refuses to write one with fewer than
`--min-sources` (default 12). Spectral bands and released-master metrics are
stored as median plus 25th/75th percentiles; the median is context, not a
target. `GENRE_PROFILES_PATH` can point the API at a catalog outside the
package.

The earlier builders are still in the tree but are no longer used for the
shipped catalog: the Internet Archive subject search
(`subverse.archive_profiles`) had pulled LibriVox audiobooks and poetry
readings into "Jazz" and "Metal", and FMA (`subverse.fma_profiles`) and
Jamendo (`subverse.jamendo_profiles`) collect amateur Creative Commons material
that does not represent released masters. Any catalog built with them must be
listened to before it is exposed.

## Analysis states

- `ok`: the file was analyzed normally.
- `silent`: the file contains no non-zero sample.
- `too_short`: the file is shorter than the configured minimum analysis
  duration.

## Supported uploads

The API accepts WAV and MP3 files.

`POST /analyze` returns a synchronous result. `POST /analyze/jobs` creates an
in-memory background job and `GET /analyze/jobs/{job_id}` returns its status.

## Configuration

- `MAX_UPLOAD_BYTES` — default `104857600` (100 MiB)
- `MAX_ANALYSIS_SECONDS` — default `360` seconds (6 minutes)
- `MAX_SAMPLE_RATE` — resource-safety ceiling, default `192000` Hz
- `MAX_AUDIO_CHANNELS` — resource-safety ceiling, default `8`
- `UPLOAD_CHUNK_BYTES` — default `1048576` bytes
- `MIN_ANALYSIS_SECONDS` — default `0.5` seconds
- `ANALYSIS_WORKERS` — default `2`
- `ANALYSIS_JOB_TTL_SECONDS` — completed job retention, default `3600`
- `ANALYSIS_JOB_MAX_RECORDS` — maximum retained jobs, default `1000`
- `GENRE_PROFILES_PATH` — optional measured genre-profile catalog path
- `AUTH_REQUIRED` — require a verified Firebase ID token on analysis routes
- `QUOTA_ENABLED` — enforce one successful analysis per account and IP/day
- `FIREBASE_PROJECT_ID` — Firebase/Google Cloud project used by Admin SDK
- `FIREBASE_WEB_CONFIG` — public Firebase Web configuration JSON returned to the UI
- `UPLOAD_BUCKET` — temporary Cloud Storage bucket used for direct browser uploads
- `IP_HASH_SECRET` — secret HMAC key; raw IP addresses are not stored in Firestore
- `QUOTA_TIMEZONE` — daily quota boundary, default `UTC`
- `QUOTA_RESERVATION_MINUTES` — stale in-progress quota timeout, default `20`

## Production access and file lifecycle

Production enables Firebase Google sign-in without a separate registration form.
Every protected request carries a Firebase ID token and the API verifies it server-side.
Firestore stores a small membership record plus two daily quota documents: one for the
account and one for a keyed, day-specific IP hash. A failed analysis releases its quota
reservation; a successful analysis consumes the daily allowance.

The browser creates a resumable Cloud Storage upload session and sends audio directly to
the temporary bucket. This avoids the Cloud Run request-size limit for six-minute WAV
files. The service verifies object ownership, downloads to an ephemeral local file,
analyzes it, and deletes both copies in `finally` cleanup. A one-day bucket lifecycle rule
is required as a backstop for uploads abandoned before analysis. The UI also exposes the
machine-readable result as a JSON download.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e '.[test]'
python3 -m uvicorn subverse.main:app --reload
```

API documentation:

```text
http://127.0.0.1:8000/docs
```

## Test

The audit suite compares the retained integrated loudness measurement with
FFmpeg's EBU R128 filter when FFmpeg is available.

```bash
pytest -q
```

## Tonal activity comparison

Spectral comparison ignores bands below the absolute `-70 dBFS` activity gate;
relative-to-LUFS values alone are not treated as evidence in near-silent bands.
The reference builder now defaults to 24 source tracks per genre instead of a
flat ten-track sample. Each built profile records observed major/minor
key-mode buckets and their counts. The acquisition is considered incomplete
until the coverage report is inspected and missing tonal buckets are filled
with additional licensed full-length sources; the count alone is not a
coverage guarantee. Add sources spanning dark/low-heavy, mid-forward,
bright/high-heavy, sparse/ambient and full-range material.
