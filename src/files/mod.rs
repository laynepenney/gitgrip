//! File operations
//!
//! Handles copyfile, linkfile, and composefile operations.

use crate::core::manifest::ComposeFileConfig;
use std::path::Path;

fn is_windows_absolute(path: &str) -> bool {
    let bytes = path.as_bytes();
    (bytes.len() >= 2 && bytes[0].is_ascii_alphabetic() && bytes[1] == b':')
        || path.starts_with("\\\\")
}

fn validate_relative_source_path(path: &str, field: &str) -> Result<(), String> {
    if path.is_empty() {
        return Err(format!("Invalid {}: empty path", field));
    }

    let normalized = path.replace('\\', "/");
    if normalized.starts_with('/') || normalized.starts_with("//") || is_windows_absolute(path) {
        return Err(format!("Invalid {}: absolute path '{}'", field, path));
    }

    if normalized.split('/').any(|segment| segment == "..") {
        return Err(format!("Invalid {}: path traversal '{}'", field, path));
    }

    Ok(())
}

fn validate_gripspace_name(name: &str) -> Result<(), String> {
    if name.is_empty() || name == "." {
        return Err(format!("Invalid gripspace name: '{}'", name));
    }

    // Allowlist: alphanumeric, hyphens, underscores, dots
    if !name
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_' || c == '.')
    {
        return Err(format!("Invalid gripspace name: '{}'", name));
    }

    if name.contains("..") {
        return Err(format!("Invalid gripspace name: '{}'", name));
    }

    Ok(())
}

/// Repo name -> configured checkout path, for composefile `repo:` parts.
///
/// Built from the manifest the caller already resolved, so a `repo:` part
/// reads from the same checkout `gr sync` maintains rather than from a second
/// idea of where repos live.
pub fn repo_checkout_paths(
    manifest: &crate::core::manifest::Manifest,
) -> std::collections::HashMap<String, std::path::PathBuf> {
    manifest
        .repos
        .iter()
        .map(|(name, cfg)| (name.clone(), std::path::PathBuf::from(&cfg.path)))
        .collect()
}

/// Process composefile entries, writing composed files to the workspace root.
///
/// Each composefile concatenates parts in order. Parts can come from:
/// - A gripspace: reads from `.gitgrip/spaces/<name>/<src>`
/// - A repo (`repo: <name>`): reads from that repo's checkout path
/// - The local manifest: reads from the manifest content directory
pub fn process_composefiles(
    workspace_root: &Path,
    manifests_dir: &Path,
    spaces_dir: &Path,
    repo_paths: &std::collections::HashMap<String, std::path::PathBuf>,
    composefiles: &[ComposeFileConfig],
) -> anyhow::Result<()> {
    for compose in composefiles {
        validate_relative_source_path(&compose.dest, "composefile dest")
            .map_err(anyhow::Error::msg)?;

        let separator = compose.separator.as_deref().unwrap_or("\n\n");
        let mut parts_content: Vec<String> = Vec::new();

        for part in &compose.parts {
            // AMBIGUOUS PARTS ARE REFUSED, NOT RESOLVED. Naming two source
            // kinds does not mean "try both" or "prefer one"; it means the
            // manifest does not say where the content comes from, and quietly
            // picking would compose a file nobody asked for.
            if part.repo.is_some() && part.gripspace.is_some() {
                eprintln!(
                    "Warning: composefile '{}' part '{}' names both repo: and gripspace:; \
                     skipping (they are mutually exclusive)",
                    compose.dest, part.src
                );
                continue;
            }

            let source_path = if let Some(ref repo_name) = part.repo {
                if let Err(e) = validate_relative_source_path(&part.src, "composefile part src") {
                    eprintln!(
                        "Warning: composefile '{}' has invalid part src: {}",
                        compose.dest, e
                    );
                    continue;
                }
                match repo_paths.get(repo_name) {
                    Some(repo_path) => workspace_root.join(repo_path).join(&part.src),
                    None => {
                        // Consistent with every other unresolvable part: warn
                        // and skip. A repo that is not in the manifest must not
                        // take the whole sync down.
                        let mut known: Vec<&str> = repo_paths.keys().map(|k| k.as_str()).collect();
                        known.sort_unstable();
                        eprintln!(
                            "Warning: composefile '{}' part repo:{} names no repo; \
                             it must match a key under `repos:` (known: {})",
                            compose.dest,
                            repo_name,
                            if known.is_empty() {
                                "none".to_string()
                            } else {
                                known.join(", ")
                            }
                        );
                        continue;
                    }
                }
            } else if let Some(ref gs_name) = part.gripspace {
                if let Err(e) = validate_gripspace_name(gs_name) {
                    eprintln!(
                        "Warning: composefile '{}' has invalid gripspace name: {}",
                        compose.dest, e
                    );
                    continue;
                }
                if let Err(e) = validate_relative_source_path(&part.src, "composefile part src") {
                    eprintln!(
                        "Warning: composefile '{}' has invalid part src: {}",
                        compose.dest, e
                    );
                    continue;
                }
                // Source from gripspace
                spaces_dir.join(gs_name).join(&part.src)
            } else {
                if let Err(e) = validate_relative_source_path(&part.src, "composefile part src") {
                    eprintln!(
                        "Warning: composefile '{}' has invalid part src: {}",
                        compose.dest, e
                    );
                    continue;
                }
                // Source from local manifest repo
                manifests_dir.join(&part.src)
            };

            match std::fs::read_to_string(&source_path) {
                Ok(content) => {
                    parts_content.push(content);
                }
                Err(e) => {
                    let gs_label = part
                        .repo
                        .as_deref()
                        .map(|r| format!("repo:{}", r))
                        .or_else(|| {
                            part.gripspace
                                .as_deref()
                                .map(|g| format!("gripspace:{}", g))
                        })
                        .unwrap_or_else(|| "manifest".to_string());
                    eprintln!(
                        "Warning: composefile '{}' part {}:{} not found: {}",
                        compose.dest, gs_label, part.src, e
                    );
                }
            }
        }

        if parts_content.is_empty() {
            continue;
        }

        let composed = parts_content.join(separator);
        let dest_path = workspace_root.join(&compose.dest);

        // Create parent directories if needed
        if let Some(parent) = dest_path.parent() {
            std::fs::create_dir_all(parent)?;
        }

        std::fs::write(&dest_path, composed)?;
    }

    Ok(())
}

/// Resolve a linkfile/copyfile source path that may reference a gripspace.
///
/// Gripspace-sourced files have src prefixed with `gripspace:<name>:<path>`.
/// This function resolves those to their actual filesystem path under `.gitgrip/spaces/`.
///
/// Returns `Err` if the gripspace name or path contains path traversal components.
pub fn resolve_file_source(
    src: &str,
    repo_path: &Path,
    spaces_dir: &Path,
) -> Result<std::path::PathBuf, String> {
    if let Some(rest) = src.strip_prefix("gripspace:") {
        // Format: gripspace:<name>:<path>
        if let Some(colon_pos) = rest.find(':') {
            let name = &rest[..colon_pos];
            let path = &rest[colon_pos + 1..];

            validate_gripspace_name(name)?;
            validate_relative_source_path(path, "gripspace path")?;

            return Ok(spaces_dir.join(name).join(path));
        }
        // Has "gripspace:" prefix but no second colon — malformed
        return Err(format!(
            "Malformed gripspace source '{}': expected format 'gripspace:<name>:<path>'",
            src
        ));
    }
    validate_relative_source_path(src, "manifest path")?;
    Ok(repo_path.join(src))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::manifest::{ComposeFileConfig, ComposeFilePart};
    use std::collections::HashMap;
    use std::path::PathBuf;
    use tempfile::TempDir;

    // ── GAP 1: a part sourced from a repo CHECKOUT ──────────────────────────
    //
    // A composefile could source from a gripspace or from the manifest repo,
    // and from nothing else -- so a repo the gripspace actually manages could
    // not contribute to a composed file. Sourcing `standards/CONVENTIONS.md`
    // with `standards` checked out at ./standards resolved MANIFEST-relative
    // and warned `manifest:standards/CONVENTIONS.md not found`.

    fn repo_paths(pairs: &[(&str, &str)]) -> HashMap<String, PathBuf> {
        pairs
            .iter()
            .map(|(name, path)| (name.to_string(), PathBuf::from(path)))
            .collect()
    }

    #[test]
    fn test_composefile_part_sources_from_a_repo_checkout() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let spaces_dir = workspace.join(".gitgrip").join("spaces");
        std::fs::create_dir_all(&manifests_dir).unwrap();
        std::fs::create_dir_all(workspace.join("standards")).unwrap();
        std::fs::write(
            workspace.join("standards").join("CONVENTIONS.md"),
            "# Conventions",
        )
        .unwrap();

        let composefiles = vec![ComposeFileConfig {
            dest: "CLAUDE.md".to_string(),
            parts: vec![ComposeFilePart {
                repo: Some("standards".to_string()),
                gripspace: None,
                src: "CONVENTIONS.md".to_string(),
            }],
            separator: None,
        }];

        process_composefiles(
            workspace,
            &manifests_dir,
            &spaces_dir,
            &repo_paths(&[("standards", "./standards")]),
            &composefiles,
        )
        .unwrap();

        assert_eq!(
            std::fs::read_to_string(workspace.join("CLAUDE.md")).unwrap(),
            "# Conventions"
        );
    }

    #[test]
    fn test_composefile_repo_part_is_not_resolved_manifest_relative() {
        // THE ACTUAL BUG, pinned. Before `repo:` existed the same file was
        // looked for under the manifest dir. A same-named decoy there would
        // make a naive fix pass while still reading the wrong file.
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let spaces_dir = workspace.join(".gitgrip").join("spaces");
        std::fs::create_dir_all(manifests_dir.join("standards")).unwrap();
        std::fs::create_dir_all(workspace.join("standards")).unwrap();
        std::fs::write(
            manifests_dir.join("standards").join("CONVENTIONS.md"),
            "DECOY FROM MANIFEST",
        )
        .unwrap();
        std::fs::write(
            workspace.join("standards").join("CONVENTIONS.md"),
            "REAL FROM REPO",
        )
        .unwrap();

        let composefiles = vec![ComposeFileConfig {
            dest: "OUT.md".to_string(),
            parts: vec![ComposeFilePart {
                repo: Some("standards".to_string()),
                gripspace: None,
                src: "CONVENTIONS.md".to_string(),
            }],
            separator: None,
        }];

        process_composefiles(
            workspace,
            &manifests_dir,
            &spaces_dir,
            &repo_paths(&[("standards", "./standards")]),
            &composefiles,
        )
        .unwrap();

        assert_eq!(
            std::fs::read_to_string(workspace.join("OUT.md")).unwrap(),
            "REAL FROM REPO"
        );
    }

    #[test]
    fn test_composefile_unknown_repo_warns_and_skips() {
        // Consistent with every other unresolvable part: warn, skip, do not
        // fail the sync. A missing repo must not take the workspace down.
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let spaces_dir = workspace.join(".gitgrip").join("spaces");
        std::fs::create_dir_all(&manifests_dir).unwrap();
        std::fs::write(manifests_dir.join("LOCAL.md"), "# Local").unwrap();

        let composefiles = vec![ComposeFileConfig {
            dest: "OUT.md".to_string(),
            parts: vec![
                ComposeFilePart {
                    repo: Some("nope".to_string()),
                    gripspace: None,
                    src: "X.md".to_string(),
                },
                ComposeFilePart {
                    repo: None,
                    gripspace: None,
                    src: "LOCAL.md".to_string(),
                },
            ],
            separator: None,
        }];

        process_composefiles(
            workspace,
            &manifests_dir,
            &spaces_dir,
            &repo_paths(&[]),
            &composefiles,
        )
        .unwrap();

        // The resolvable part still composes; the unknown one is skipped.
        assert_eq!(
            std::fs::read_to_string(workspace.join("OUT.md")).unwrap(),
            "# Local"
        );
    }

    #[test]
    fn test_composefile_repo_part_rejects_path_traversal() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let spaces_dir = workspace.join(".gitgrip").join("spaces");
        std::fs::create_dir_all(&manifests_dir).unwrap();
        std::fs::create_dir_all(workspace.join("standards")).unwrap();
        std::fs::write(workspace.join("SECRET.md"), "secret").unwrap();

        let composefiles = vec![ComposeFileConfig {
            dest: "OUT.md".to_string(),
            parts: vec![ComposeFilePart {
                repo: Some("standards".to_string()),
                gripspace: None,
                src: "../SECRET.md".to_string(),
            }],
            separator: None,
        }];

        process_composefiles(
            workspace,
            &manifests_dir,
            &spaces_dir,
            &repo_paths(&[("standards", "./standards")]),
            &composefiles,
        )
        .unwrap();

        assert!(
            !workspace.join("OUT.md").exists(),
            "path traversal out of a repo checkout was composed"
        );
    }

    #[test]
    fn test_composefile_repo_and_gripspace_together_is_rejected() {
        // Two source kinds on one part is ambiguous. Refuse rather than pick.
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let spaces_dir = workspace.join(".gitgrip").join("spaces");
        std::fs::create_dir_all(&manifests_dir).unwrap();
        std::fs::create_dir_all(spaces_dir.join("base")).unwrap();
        std::fs::create_dir_all(workspace.join("standards")).unwrap();
        std::fs::write(spaces_dir.join("base").join("A.md"), "from gripspace").unwrap();
        std::fs::write(workspace.join("standards").join("A.md"), "from repo").unwrap();

        let composefiles = vec![ComposeFileConfig {
            dest: "OUT.md".to_string(),
            parts: vec![ComposeFilePart {
                repo: Some("standards".to_string()),
                gripspace: Some("base".to_string()),
                src: "A.md".to_string(),
            }],
            separator: None,
        }];

        process_composefiles(
            workspace,
            &manifests_dir,
            &spaces_dir,
            &repo_paths(&[("standards", "./standards")]),
            &composefiles,
        )
        .unwrap();

        assert!(
            !workspace.join("OUT.md").exists(),
            "an ambiguous part with both repo: and gripspace: was composed anyway"
        );
    }

    #[test]
    fn test_process_composefiles_basic() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let gripspaces_dir = workspace.join(".gitgrip").join("spaces");

        std::fs::create_dir_all(&manifests_dir).unwrap();
        std::fs::create_dir_all(gripspaces_dir.join("base-space")).unwrap();

        // Create source files
        std::fs::write(
            gripspaces_dir.join("base-space").join("BASE.md"),
            "# Base Content",
        )
        .unwrap();
        std::fs::write(manifests_dir.join("LOCAL.md"), "# Local Content").unwrap();

        let composefiles = vec![ComposeFileConfig {
            dest: "COMPOSED.md".to_string(),
            parts: vec![
                ComposeFilePart {
                    repo: None,
                    gripspace: Some("base-space".to_string()),
                    src: "BASE.md".to_string(),
                },
                ComposeFilePart {
                    repo: None,
                    gripspace: None,
                    src: "LOCAL.md".to_string(),
                },
            ],
            separator: None,
        }];

        let result = process_composefiles(
            workspace,
            &manifests_dir,
            &gripspaces_dir,
            &HashMap::new(),
            &composefiles,
        );
        assert!(result.is_ok());

        let content = std::fs::read_to_string(workspace.join("COMPOSED.md")).unwrap();
        assert_eq!(content, "# Base Content\n\n# Local Content");
    }

    #[test]
    fn test_process_composefiles_custom_separator() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let gripspaces_dir = workspace.join(".gitgrip").join("spaces");

        std::fs::create_dir_all(&manifests_dir).unwrap();
        std::fs::create_dir_all(&gripspaces_dir).unwrap();

        std::fs::write(manifests_dir.join("PART1.md"), "Part 1").unwrap();
        std::fs::write(manifests_dir.join("PART2.md"), "Part 2").unwrap();

        let composefiles = vec![ComposeFileConfig {
            dest: "OUTPUT.md".to_string(),
            parts: vec![
                ComposeFilePart {
                    repo: None,
                    gripspace: None,
                    src: "PART1.md".to_string(),
                },
                ComposeFilePart {
                    repo: None,
                    gripspace: None,
                    src: "PART2.md".to_string(),
                },
            ],
            separator: Some("\n\n---\n\n".to_string()),
        }];

        let result = process_composefiles(
            workspace,
            &manifests_dir,
            &gripspaces_dir,
            &HashMap::new(),
            &composefiles,
        );
        assert!(result.is_ok());

        let content = std::fs::read_to_string(workspace.join("OUTPUT.md")).unwrap();
        assert_eq!(content, "Part 1\n\n---\n\nPart 2");
    }

    #[test]
    fn test_process_composefiles_missing_part() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let gripspaces_dir = workspace.join(".gitgrip").join("spaces");

        std::fs::create_dir_all(&manifests_dir).unwrap();
        std::fs::create_dir_all(&gripspaces_dir).unwrap();

        std::fs::write(manifests_dir.join("EXISTS.md"), "I exist").unwrap();

        let composefiles = vec![ComposeFileConfig {
            dest: "OUTPUT.md".to_string(),
            parts: vec![
                ComposeFilePart {
                    repo: None,
                    gripspace: Some("nonexistent".to_string()),
                    src: "MISSING.md".to_string(),
                },
                ComposeFilePart {
                    repo: None,
                    gripspace: None,
                    src: "EXISTS.md".to_string(),
                },
            ],
            separator: None,
        }];

        let result = process_composefiles(
            workspace,
            &manifests_dir,
            &gripspaces_dir,
            &HashMap::new(),
            &composefiles,
        );
        assert!(result.is_ok());

        // Should still write the available part
        let content = std::fs::read_to_string(workspace.join("OUTPUT.md")).unwrap();
        assert_eq!(content, "I exist");
    }

    #[test]
    fn test_process_composefiles_creates_parent_dirs() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let gripspaces_dir = workspace.join(".gitgrip").join("spaces");

        std::fs::create_dir_all(&manifests_dir).unwrap();
        std::fs::create_dir_all(&gripspaces_dir).unwrap();

        std::fs::write(manifests_dir.join("content.txt"), "hello").unwrap();

        let composefiles = vec![ComposeFileConfig {
            dest: "nested/dir/output.txt".to_string(),
            parts: vec![ComposeFilePart {
                repo: None,
                gripspace: None,
                src: "content.txt".to_string(),
            }],
            separator: None,
        }];

        let result = process_composefiles(
            workspace,
            &manifests_dir,
            &gripspaces_dir,
            &HashMap::new(),
            &composefiles,
        );
        assert!(result.is_ok());
        assert!(workspace.join("nested/dir/output.txt").exists());
    }

    #[test]
    fn test_resolve_file_source_local() {
        let repo_path = Path::new("/workspace/repo");
        let gripspaces_dir = Path::new("/workspace/.gitgrip/spaces");
        let result = resolve_file_source("README.md", repo_path, gripspaces_dir).unwrap();
        assert_eq!(result, Path::new("/workspace/repo/README.md"));
    }

    #[test]
    fn test_resolve_file_source_gripspace() {
        let repo_path = Path::new("/workspace/.gitgrip/manifests");
        let gripspaces_dir = Path::new("/workspace/.gitgrip/spaces");
        let result =
            resolve_file_source("gripspace:base:CLAUDE.md", repo_path, gripspaces_dir).unwrap();
        assert_eq!(
            result,
            Path::new("/workspace/.gitgrip/spaces/base/CLAUDE.md")
        );
    }

    #[test]
    fn test_resolve_file_source_path_traversal_name() {
        let repo_path = Path::new("/workspace/repo");
        let gripspaces_dir = Path::new("/workspace/.gitgrip/spaces");
        let result =
            resolve_file_source("gripspace:../../../etc:passwd", repo_path, gripspaces_dir);
        assert!(result.is_err());
    }

    #[test]
    fn test_resolve_file_source_path_traversal_path() {
        let repo_path = Path::new("/workspace/repo");
        let gripspaces_dir = Path::new("/workspace/.gitgrip/spaces");
        let result = resolve_file_source(
            "gripspace:valid:../../etc/passwd",
            repo_path,
            gripspaces_dir,
        );
        assert!(result.is_err());
    }

    #[test]
    fn test_resolve_file_source_empty_name() {
        let repo_path = Path::new("/workspace/repo");
        let gripspaces_dir = Path::new("/workspace/.gitgrip/spaces");
        let result = resolve_file_source("gripspace::file.md", repo_path, gripspaces_dir);
        assert!(result.is_err());
    }

    #[test]
    fn test_resolve_file_source_local_path_traversal() {
        let repo_path = Path::new("/workspace/repo");
        let gripspaces_dir = Path::new("/workspace/.gitgrip/spaces");
        let result = resolve_file_source("../outside.txt", repo_path, gripspaces_dir);
        assert!(result.is_err());
    }

    #[test]
    fn test_resolve_file_source_local_windows_absolute_path() {
        let repo_path = Path::new("/workspace/repo");
        let gripspaces_dir = Path::new("/workspace/.gitgrip/spaces");
        let result = resolve_file_source("C:\\Windows\\System32\\etc", repo_path, gripspaces_dir);
        assert!(result.is_err());
    }

    #[test]
    fn test_process_composefiles_dest_path_traversal() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let gripspaces_dir = workspace.join(".gitgrip").join("spaces");

        std::fs::create_dir_all(&manifests_dir).unwrap();
        std::fs::create_dir_all(&gripspaces_dir).unwrap();
        std::fs::write(manifests_dir.join("file.md"), "content").unwrap();

        let composefiles = vec![ComposeFileConfig {
            dest: "../escaped.md".to_string(),
            parts: vec![ComposeFilePart {
                repo: None,
                gripspace: None,
                src: "file.md".to_string(),
            }],
            separator: None,
        }];

        let result = process_composefiles(
            workspace,
            &manifests_dir,
            &gripspaces_dir,
            &HashMap::new(),
            &composefiles,
        );
        assert!(result.is_err());
    }

    #[test]
    fn test_process_composefiles_dest_windows_absolute_path() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let gripspaces_dir = workspace.join(".gitgrip").join("spaces");

        std::fs::create_dir_all(&manifests_dir).unwrap();
        std::fs::create_dir_all(&gripspaces_dir).unwrap();
        std::fs::write(manifests_dir.join("file.md"), "content").unwrap();

        let composefiles = vec![ComposeFileConfig {
            dest: "C:\\temp\\escaped.md".to_string(),
            parts: vec![ComposeFilePart {
                repo: None,
                gripspace: None,
                src: "file.md".to_string(),
            }],
            separator: None,
        }];

        let result = process_composefiles(
            workspace,
            &manifests_dir,
            &gripspaces_dir,
            &HashMap::new(),
            &composefiles,
        );
        assert!(result.is_err());
    }

    #[test]
    fn test_process_composefiles_invalid_gripspace_name() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let gripspaces_dir = workspace.join(".gitgrip").join("spaces");

        std::fs::create_dir_all(&manifests_dir).unwrap();
        std::fs::create_dir_all(&gripspaces_dir).unwrap();
        std::fs::write(manifests_dir.join("fallback.md"), "ok").unwrap();

        // A composefile part with invalid gripspace name should be skipped
        let composefiles = vec![ComposeFileConfig {
            dest: "output.md".to_string(),
            parts: vec![
                ComposeFilePart {
                    repo: None,
                    gripspace: Some("../evil".to_string()),
                    src: "file.md".to_string(),
                },
                ComposeFilePart {
                    repo: None,
                    gripspace: None,
                    src: "fallback.md".to_string(),
                },
            ],
            separator: None,
        }];

        let result = process_composefiles(
            workspace,
            &manifests_dir,
            &gripspaces_dir,
            &HashMap::new(),
            &composefiles,
        );
        assert!(result.is_ok());

        // Only the valid part should be written
        let content = std::fs::read_to_string(workspace.join("output.md")).unwrap();
        assert_eq!(content, "ok");
    }

    #[test]
    fn test_resolve_file_source_malformed_gripspace_no_second_colon() {
        let repo_path = Path::new("/workspace/repo");
        let gripspaces_dir = Path::new("/workspace/.gitgrip/spaces");
        let result = resolve_file_source("gripspace:only-name", repo_path, gripspaces_dir);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("Malformed gripspace source"));
    }

    #[test]
    fn test_resolve_file_source_backslash_path() {
        let repo_path = Path::new("/workspace/repo");
        let gripspaces_dir = Path::new("/workspace/.gitgrip/spaces");
        let result =
            resolve_file_source("gripspace:valid:\\etc\\passwd", repo_path, gripspaces_dir);
        assert!(result.is_err());
    }

    #[test]
    fn test_process_composefiles_dest_backslash_rejected() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let gripspaces_dir = workspace.join(".gitgrip").join("spaces");

        std::fs::create_dir_all(&manifests_dir).unwrap();
        std::fs::create_dir_all(&gripspaces_dir).unwrap();
        std::fs::write(manifests_dir.join("file.md"), "content").unwrap();

        let composefiles = vec![ComposeFileConfig {
            dest: "\\escaped.md".to_string(),
            parts: vec![ComposeFilePart {
                repo: None,
                gripspace: None,
                src: "file.md".to_string(),
            }],
            separator: None,
        }];

        let result = process_composefiles(
            workspace,
            &manifests_dir,
            &gripspaces_dir,
            &HashMap::new(),
            &composefiles,
        );
        assert!(result.is_err());
    }
}
