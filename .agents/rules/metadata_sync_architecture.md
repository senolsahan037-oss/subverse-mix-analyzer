# AI Tool Metadata Sync Architecture (Final Version)

## Purpose

This architecture defines the official workflow for synchronizing AI Tool documentation with the SubverseLab website.

The objective is to eliminate AI hallucinations by making every tool describe itself once, inside its own repository, before deployment.

The website never analyzes source code, guesses features from the interface, or generates documentation from the tool name.

The tool itself is always the single source of truth.

---

# Architecture Overview

Each AI Tool is developed as an independent project and deployed independently to Google Cloud Run.

Every tool repository contains its own documentation and public assets.

When an administrator registers a new tool inside the SubverseLab Admin Panel, the website automatically imports the official metadata from the deployed tool.

The imported information is then synchronized into Firebase and becomes the website's product page and User Guide.

---

# Repository Structure

Every AI Tool repository must contain the following files.

```text
tool-project/
│
├── app/
├── assets/
│   └── cover.jpg
│
├── docs/
│   └── guide.md
│
├── README.md
│
└── ...
```

---

# Required Public Endpoints

Every deployed AI Tool must expose the following endpoints.

## Manifest

```
GET /api/manifest
```

Example response:

```json
{
  "name": "Subverse Mix Analyzer",
  "slug": "subverse-mix-analyzer",
  "version": "1.0.0",
  "guide_version": "1.0.0",
  "updated_at": "2026-08-07T00:00:00Z",
  "cover_url": "https://tool.run.app/assets/cover.jpg",
  "guide_url": "https://tool.run.app/docs/guide.md"
}
```

---

## Guide

```
GET /docs/guide.md
```

Returns the complete User Guide written by the tool developer.

---

## Cover

```
GET /assets/cover.jpg
```

Returns the official product cover.

---

# README.md

Every repository must include a README.md.

README is intended for developers and contributors.

It explains:

- project purpose
- architecture
- installation
- development
- deployment
- build process
- contribution guide

README is **not** used for website documentation.

---

# guide.md

guide.md is the official product documentation.

It is written once by the developer before deployment.

It becomes the public documentation shown on the website.

The guide should include:

- Tool overview
- Purpose
- Features
- Supported file formats
- Inputs
- Outputs
- Step-by-step usage
- Daily quota
- Requirements
- Limitations
- Error behavior
- Version information
- Changelog (optional)

Everything visible on the website originates from this document.

---

# Admin Panel Workflow

The Product Form contains:

```
Tool URL
```

and

```
Sync Tool Metadata
```

button.

When pressed:

1. Validate the URL.
2. Request `/api/manifest`.
3. Validate the manifest.
4. Download `guide.md`.
5. Download `cover.jpg`.
6. Synchronize Firebase.
7. Update the product.
8. Update the User Guide.
9. Store the current synced version.
10. Report success or errors.

---

# Synchronization Rules

Synchronization updates:

- Product title
- Product image
- User Guide
- Tool version
- Guide version
- Last synchronized time

Existing products are updated.

Duplicate products must never be created.

Synchronization must be idempotent.

Running Sync multiple times must always produce the same result.

---

# Firebase Responsibilities

Firebase stores:

- Product information
- User Guide content
- Product image reference
- Version
- Guide version
- Last synchronized date

The website never depends on Cloud Run at page rendering time.

Cloud Run is only the source of synchronization.

After synchronization, the website serves its own stored data.

---

# Image Handling

The official cover image is downloaded during synchronization.

It is copied into the website storage.

The website never hotlinks images from Cloud Run.

This guarantees:

- faster loading
- independent hosting
- no broken images after redeployment

---

# User Guide Handling

guide.md is downloaded during synchronization.

The Markdown is stored in Firebase.

The website renders its local copy.

The guide is not fetched from Cloud Run during normal page views.

---

# Security Rules

The synchronization service must:

- allow HTTPS only
- validate the manifest structure
- reject malformed metadata
- sanitize Markdown before storing
- reject unsupported file types

Only administrators may perform synchronization.

---

# Hallucination Prevention Policy

The website must never:

- inspect source code
- infer capabilities
- guess features
- generate technical documentation
- invent supported formats
- create usage instructions automatically

Only information explicitly written by the tool developer inside guide.md may appear on the website.

---

# Versioning

Every deployment increments:

- version
- guide_version
- updated_at

The website compares versions before updating.

If no changes exist, synchronization finishes without modifying Firebase.

---

# Deployment Checklist

Before deployment every tool must have:

- guide.md
- cover.jpg
- README.md
- /api/manifest
- valid version
- valid guide version
- Cloud Run deployment

Only after all checks succeed may the tool be synchronized into SubverseLab.

---

# Single Source of Truth

The authoritative ownership of information is:

Developer
↓

guide.md
↓

Cloud Run Manifest
↓

Metadata Synchronization
↓

Firebase
↓

SubverseLab Website

No other source may define product documentation.
