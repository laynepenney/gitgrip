# Phase 6: git-repo Coexistence, Workspace CI/CD, AI-Workspace Optimizations

## Status: In Progress

## Overview

Three major feature tracks:
1. **git-repo coexistence** — gitgrip config lives inside `.repo/manifests/`, reads the XML manifest, adds PR tooling for **non-Gerrit repos only** (Gerrit repos stay managed by `repo upload`)
2. **Workspace CI/CD** — cross-repo integration pipelines in the manifest
3. **AI-workspace optimizations** — token-efficient output, `--json` for agents

## Tracks

### Track 1: Bitbucket Platform Support
- Add `PlatformType::Bitbucket` to enum
- Register in `platform/mod.rs`
- Fix adapter type mismatches
- Add detection logic

### Track 2: git-repo XML Manifest Parser
- Parse `default.xml` → intermediate `XmlManifest` → gitgrip `Manifest`
- Skip Gerrit remotes (those with `review` attribute)
- Resolve includes, remove-project, extend-project

### Track 3: `.repo/` Coexistence
- `gr init --from-repo` — generates manifest.yaml inside `.repo/manifests/`
- `load_workspace()` detects `.repo/manifests/manifest.yaml`
- `gr manifest import` / `gr manifest sync`

### Track 4: Workspace CI/CD Pipelines
- CI types in manifest (CiStep, CiPipeline, CiConfig)
- `gr ci run/list/status` commands
- Results saved to `.gitgrip/ci-results/`

### Track 5: AI-Workspace Optimizations
- `--json` on `gr status`, `gr diff`, `gr branch` (list)
- Machine-readable summary in `--quiet` mode

## Implementation Order

Track 1 → Track 2 → Track 3 → Track 4 (independent) → Track 5 (independent)
