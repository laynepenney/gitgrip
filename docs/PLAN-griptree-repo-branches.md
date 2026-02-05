
---

## ⚠️ CRITICAL WARNING: NEVER DELETE ACTIVE GRIPSPACES

### Error Made (Feb 2, 2026)

During testing, accidentally deleted the active `codi-dev` gripspace by running:
```bash
gr tree remove --force codi-dev
```

This deleted the production worktree, losing all uncommitted work.

### Rule

**NEVER delete gripspaces that are currently active for development.**

### Safe Deletion Criteria

Before running `gr tree remove`, verify:
1. ✅ Is this a stale/test gripspace?
2. ✅ Has all work been merged or transferred?
3. ✅ Is the branch already deleted/merged in main workspace?
4. ✅ Is this explicitly marked for cleanup in documentation?

### Testing Guidelines

When testing griptree features:
1. **Use unique test names**: `test-feature-$(date +%s)`
2. **Never use production branch names** (e.g., `codi-dev`, `main`)
3. **Clean up test gripspaces promptly** after testing
4. **Verify with `gr tree list`** before running `tree remove`

### Safe Test Command Pattern

```bash
# ✅ GOOD: Unique test name
BRANCH="test-$(date +%s)"
gr tree add "$BRANCH"
# ... test ...
gr tree remove --force "$BRANCH"

# ❌ BAD: Using branch names that might be in use
gr tree remove --force codi-dev  # DELETES ACTIVE WORKSPACE
```

### Current Active Gripspace

- **codi-dev**: Active, DO NOT DELETE
  - Location: `/Users/layne/Development/codi-dev`

---

*Remember: Always check `gr tree list` before running `gr tree remove`*
