# Gripspace Layout Plan

## Status

- Implemented in codebase now:
  - Canonical workspace file path: `.gitgrip/spaces/main/gripspace.yml`
  - Legacy fallback reads:
    - `.gitgrip/manifests/manifest.yaml`
    - `.gitgrip/manifests/manifest.yml`
  - Command path resolution now prefers canonical layout and falls back to legacy.
- Not yet implemented:
  - Loading and merging `.gitgrip/spaces/local/gripspace.yml`
  - `include:` expansion across gripspace files

## Goals

1. Make `gripspace.yml` the default, explicit workspace format.
2. Separate shareable workspace config (`main`) from user/local overrides (`local`).
3. Support reusable composition with `include:` while keeping deterministic behavior.
4. Preserve backward compatibility for existing workspaces during migration.

## Canonical Layout

```text
.gitgrip/
  spaces/
    main/
      gripspace.yml        # tracked/shared workspace definition
    local/
      gripspace.yml        # optional local overrides (not shared by default)
```

Legacy compatibility during migration:

```text
.gitgrip/manifests/manifest.yaml
.gitgrip/manifests/manifest.yml
```

## Merge Model (Main + Local)

Load order (lowest to highest precedence):

1. `spaces/main/gripspace.yml`
2. `spaces/local/gripspace.yml` (if present)

Proposed merge rules:

- Scalars (`version`, `settings.*`): local overrides main.
- Maps (`repos`, `workspace.env`, `workspace.scripts`, `workspace.ci.pipelines`): deep-merge by key, local key wins on conflict.
- Arrays:
  - `groups`: union with stable order (main first, then new local entries).
  - `copyfile` / `linkfile`: concatenate with de-dup by `(src,dest)`, local wins on duplicate.

## `include:` Design

Proposed schema extension (top-level):

```yaml
include:
  - ../shared/base.gripspace.yml
  - ./team/mobile.gripspace.yml
```

Rules:

- Includes are resolved relative to the file that declares them.
- Includes are processed depth-first, then merged in declaration order.
- Current file overrides included content.
- Cycles are rejected with a clear error chain.
- Missing include file is a hard error by default.

## Validation and Guardrails

- Enforce workspace-bound paths after normalization.
- Reject path traversal (`..`) and absolute include paths by default.
- Error messages should include:
  - failing file path
  - include parent path
  - merge key conflict context where possible

## Migration Plan

1. **Read compatibility** (done): prefer canonical, fallback to legacy.
2. **Write default** (done): new workspaces write `spaces/main/gripspace.yml`.
3. **Optional migration command** (planned):
   - `gr manifest migrate-layout`
   - Moves/copies legacy manifest to canonical layout.
   - Optionally leaves a compatibility mirror.
4. **Deprecation window**:
   - keep legacy reads for N minor versions
   - emit warnings when legacy path is the active source

## Testing Plan

- Unit tests:
  - path resolution preference/fallback
  - include cycle detection
  - merge conflict behavior
- Integration tests:
  - commands run from canonical layout only
  - commands run with legacy-only layout
  - main+local overlay behavior
  - include chains and error paths
- Regression tests:
  - griptree add/remove/return with manifest worktree at `spaces/main`
  - sync/rebase/status behavior unchanged for non-manifest repos
