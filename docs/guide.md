# Subverse Mix Check - User Guide

## Overview
Mix Check is an evidence-first audio measurement console. It reports what the uploaded signal actually measures and compares it only against a supplied reference or measured genre profile. It does not produce a quality score or pretend to replace listening.

## Purpose
The goal is to give producers a reproducible measurement surface: decoded waveform, direct loudness and level readings, spectral deltas, and mono fold-down loss. The result is evidence for a decision, not an automated verdict.

## Features
- **Direct measurements:** Integrated LUFS, sample peak, RMS, crest factor, channel balance, and DC offset.
- **Spectral comparison:** One-third-octave measurements with loudness-relative deltas.
- **Reference matching:** Compares against an uploaded WAV or MP3 reference when supplied.
- **Genre profiles:** Five profiles (Hip-Hop, Trap, Electronic, Pop, Rock), each measured from 20 of the most widely known released masters of the genre; the catalog keeps only aggregate distributions and the track list. Used as comparison context, never as a classifier. With no genre selected, the nearest profile is used as a target only when it is clearly nearest (at least 1 dB ahead of the runner-up); otherwise the ranking is shown and the track is compared with the pooled "Released masters (all genres)" profile instead.
- **Mono fold-down:** Reports material adjacent-band loss only when the signal supports it.
- **Mix and Master stages:** Applies the documented comparison policy for the selected stage.

## Supported File Formats
- **Formats:** `.wav`, `.mp3`
- **Max File Size:** 100 MB
- **Max Duration:** 6 Minutes (360 seconds)
- **Max Sample Rate:** 192 kHz
- **Max Channels:** 8

## Inputs
- **mix_object:** The main track to be analyzed.
- **reference_object (Optional):** A commercial reference track for direct comparison.
- **genre (Optional):** Target genre profile.
- **analysis_stage:** "mix" or "master" (determines threshold rigor).

## Outputs
- **Loudness and level metrics:** Integrated LUFS, sample peak, RMS, crest factor, and channel readings.
- **Spectrum:** One-third-octave band values and supported comparison deltas.
- **Mono loss:** Band-level fold-down evidence when material loss is detected.
- **Visual data:** Raw waveform envelope and spectrum data for the cockpit UI.

## Access and daily quota
The tool receives membership identity from the SubverseLab website and does not
show a separate login screen.

- Members receive one completed analysis per IP address per UTC calendar day.
- Server-verified admins have no product usage quota.
- Failed or undecodable analyses release their reservation and do not consume the allowance.

## Error Behavior
- **429 Too Many Requests:** "Today's free analysis has already been used for this network. Please return tomorrow."
- **422 Unprocessable Entity:** Returned if audio cannot be decoded, is corrupted, or exceeds duration/size limits.

## Version Information
- **App Version:** 3.3.0
- **Guide Version:** 1.1.0
- **Last Updated:** 2026-08-25
