//! File operations
//!
//! Handles copyfile, linkfile, and composefile operations.

use crate::core::manifest::ComposeFileConfig;
use std::path::Path;

/// Process composefile entries, writing composed files to the workspace root.
///
/// Each composefile concatenates parts in order. Parts can come from:
/// - A gripspace: reads from `.gitgrip/gripspaces/<name>/<src>`
/// - The local manifest: reads from `.gitgrip/manifests/<src>`
pub fn process_composefiles(
    workspace_root: &Path,
    manifests_dir: &Path,
    gripspaces_dir: &Path,
    composefiles: &[ComposeFileConfig],
) -> anyhow::Result<()> {
    for compose in composefiles {
        // Validate dest doesn't escape workspace
        if compose.dest.contains("..") || compose.dest.starts_with('/') {
            anyhow::bail!(
                "Composefile dest escapes workspace boundary: {}",
                compose.dest
            );
        }

        let separator = compose.separator.as_deref().unwrap_or("\n\n");
        let mut parts_content: Vec<String> = Vec::new();

        for part in &compose.parts {
            let source_path = if let Some(ref gs_name) = part.gripspace {
                // Validate gripspace name doesn't contain traversal
                if gs_name.contains("..")
                    || gs_name.contains('/')
                    || gs_name.contains('\\')
                    || gs_name.is_empty()
                {
                    eprintln!(
                        "Warning: composefile '{}' has invalid gripspace name: '{}'",
                        compose.dest, gs_name
                    );
                    continue;
                }
                if part.src.contains("..") || part.src.starts_with('/') {
                    eprintln!(
                        "Warning: composefile '{}' has invalid part src: '{}'",
                        compose.dest, part.src
                    );
                    continue;
                }
                // Source from gripspace
                gripspaces_dir.join(gs_name).join(&part.src)
            } else {
                if part.src.contains("..") || part.src.starts_with('/') {
                    eprintln!(
                        "Warning: composefile '{}' has invalid part src: '{}'",
                        compose.dest, part.src
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
                        .gripspace
                        .as_deref()
                        .map(|g| format!("gripspace:{}", g))
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
/// This function resolves those to their actual filesystem path.
///
/// Returns `Err` if the gripspace name or path contains path traversal components.
pub fn resolve_file_source(
    src: &str,
    repo_path: &Path,
    gripspaces_dir: &Path,
) -> Result<std::path::PathBuf, String> {
    if let Some(rest) = src.strip_prefix("gripspace:") {
        // Format: gripspace:<name>:<path>
        if let Some(colon_pos) = rest.find(':') {
            let name = &rest[..colon_pos];
            let path = &rest[colon_pos + 1..];

            // Validate gripspace name and path don't contain traversal
            if name.contains("..") || name.contains('/') || name.contains('\\') || name.is_empty()
            {
                return Err(format!("Invalid gripspace name: '{}'", name));
            }
            if path.contains("..") || path.starts_with('/') || path.starts_with('\\') {
                return Err(format!(
                    "Invalid gripspace path: '{}' (path traversal)",
                    path
                ));
            }

            return Ok(gripspaces_dir.join(name).join(path));
        }
    }
    Ok(repo_path.join(src))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::manifest::{ComposeFileConfig, ComposeFilePart};
    use tempfile::TempDir;

    #[test]
    fn test_process_composefiles_basic() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let gripspaces_dir = workspace.join(".gitgrip").join("gripspaces");

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
                    gripspace: Some("base-space".to_string()),
                    src: "BASE.md".to_string(),
                },
                ComposeFilePart {
                    gripspace: None,
                    src: "LOCAL.md".to_string(),
                },
            ],
            separator: None,
        }];

        let result =
            process_composefiles(workspace, &manifests_dir, &gripspaces_dir, &composefiles);
        assert!(result.is_ok());

        let content = std::fs::read_to_string(workspace.join("COMPOSED.md")).unwrap();
        assert_eq!(content, "# Base Content\n\n# Local Content");
    }

    #[test]
    fn test_process_composefiles_custom_separator() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let gripspaces_dir = workspace.join(".gitgrip").join("gripspaces");

        std::fs::create_dir_all(&manifests_dir).unwrap();
        std::fs::create_dir_all(&gripspaces_dir).unwrap();

        std::fs::write(manifests_dir.join("PART1.md"), "Part 1").unwrap();
        std::fs::write(manifests_dir.join("PART2.md"), "Part 2").unwrap();

        let composefiles = vec![ComposeFileConfig {
            dest: "OUTPUT.md".to_string(),
            parts: vec![
                ComposeFilePart {
                    gripspace: None,
                    src: "PART1.md".to_string(),
                },
                ComposeFilePart {
                    gripspace: None,
                    src: "PART2.md".to_string(),
                },
            ],
            separator: Some("\n\n---\n\n".to_string()),
        }];

        let result =
            process_composefiles(workspace, &manifests_dir, &gripspaces_dir, &composefiles);
        assert!(result.is_ok());

        let content = std::fs::read_to_string(workspace.join("OUTPUT.md")).unwrap();
        assert_eq!(content, "Part 1\n\n---\n\nPart 2");
    }

    #[test]
    fn test_process_composefiles_missing_part() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let gripspaces_dir = workspace.join(".gitgrip").join("gripspaces");

        std::fs::create_dir_all(&manifests_dir).unwrap();
        std::fs::create_dir_all(&gripspaces_dir).unwrap();

        std::fs::write(manifests_dir.join("EXISTS.md"), "I exist").unwrap();

        let composefiles = vec![ComposeFileConfig {
            dest: "OUTPUT.md".to_string(),
            parts: vec![
                ComposeFilePart {
                    gripspace: Some("nonexistent".to_string()),
                    src: "MISSING.md".to_string(),
                },
                ComposeFilePart {
                    gripspace: None,
                    src: "EXISTS.md".to_string(),
                },
            ],
            separator: None,
        }];

        let result =
            process_composefiles(workspace, &manifests_dir, &gripspaces_dir, &composefiles);
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
        let gripspaces_dir = workspace.join(".gitgrip").join("gripspaces");

        std::fs::create_dir_all(&manifests_dir).unwrap();
        std::fs::create_dir_all(&gripspaces_dir).unwrap();

        std::fs::write(manifests_dir.join("content.txt"), "hello").unwrap();

        let composefiles = vec![ComposeFileConfig {
            dest: "nested/dir/output.txt".to_string(),
            parts: vec![ComposeFilePart {
                gripspace: None,
                src: "content.txt".to_string(),
            }],
            separator: None,
        }];

        let result =
            process_composefiles(workspace, &manifests_dir, &gripspaces_dir, &composefiles);
        assert!(result.is_ok());
        assert!(workspace.join("nested/dir/output.txt").exists());
    }

    #[test]
    fn test_resolve_file_source_local() {
        let repo_path = Path::new("/workspace/repo");
        let gripspaces_dir = Path::new("/workspace/.gitgrip/gripspaces");
        let result = resolve_file_source("README.md", repo_path, gripspaces_dir).unwrap();
        assert_eq!(result, Path::new("/workspace/repo/README.md"));
    }

    #[test]
    fn test_resolve_file_source_gripspace() {
        let repo_path = Path::new("/workspace/.gitgrip/manifests");
        let gripspaces_dir = Path::new("/workspace/.gitgrip/gripspaces");
        let result =
            resolve_file_source("gripspace:base:CLAUDE.md", repo_path, gripspaces_dir).unwrap();
        assert_eq!(
            result,
            Path::new("/workspace/.gitgrip/gripspaces/base/CLAUDE.md")
        );
    }

    #[test]
    fn test_resolve_file_source_path_traversal_name() {
        let repo_path = Path::new("/workspace/repo");
        let gripspaces_dir = Path::new("/workspace/.gitgrip/gripspaces");
        let result =
            resolve_file_source("gripspace:../../../etc:passwd", repo_path, gripspaces_dir);
        assert!(result.is_err());
    }

    #[test]
    fn test_resolve_file_source_path_traversal_path() {
        let repo_path = Path::new("/workspace/repo");
        let gripspaces_dir = Path::new("/workspace/.gitgrip/gripspaces");
        let result =
            resolve_file_source("gripspace:valid:../../etc/passwd", repo_path, gripspaces_dir);
        assert!(result.is_err());
    }

    #[test]
    fn test_resolve_file_source_empty_name() {
        let repo_path = Path::new("/workspace/repo");
        let gripspaces_dir = Path::new("/workspace/.gitgrip/gripspaces");
        let result = resolve_file_source("gripspace::file.md", repo_path, gripspaces_dir);
        assert!(result.is_err());
    }

    #[test]
    fn test_process_composefiles_dest_path_traversal() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let gripspaces_dir = workspace.join(".gitgrip").join("gripspaces");

        std::fs::create_dir_all(&manifests_dir).unwrap();
        std::fs::create_dir_all(&gripspaces_dir).unwrap();
        std::fs::write(manifests_dir.join("file.md"), "content").unwrap();

        let composefiles = vec![ComposeFileConfig {
            dest: "../escaped.md".to_string(),
            parts: vec![ComposeFilePart {
                gripspace: None,
                src: "file.md".to_string(),
            }],
            separator: None,
        }];

        let result =
            process_composefiles(workspace, &manifests_dir, &gripspaces_dir, &composefiles);
        assert!(result.is_err());
    }

    #[test]
    fn test_process_composefiles_invalid_gripspace_name() {
        let temp = TempDir::new().unwrap();
        let workspace = temp.path();
        let manifests_dir = workspace.join(".gitgrip").join("manifests");
        let gripspaces_dir = workspace.join(".gitgrip").join("gripspaces");

        std::fs::create_dir_all(&manifests_dir).unwrap();
        std::fs::create_dir_all(&gripspaces_dir).unwrap();
        std::fs::write(manifests_dir.join("fallback.md"), "ok").unwrap();

        // A composefile part with invalid gripspace name should be skipped
        let composefiles = vec![ComposeFileConfig {
            dest: "output.md".to_string(),
            parts: vec![
                ComposeFilePart {
                    gripspace: Some("../evil".to_string()),
                    src: "file.md".to_string(),
                },
                ComposeFilePart {
                    gripspace: None,
                    src: "fallback.md".to_string(),
                },
            ],
            separator: None,
        }];

        let result =
            process_composefiles(workspace, &manifests_dir, &gripspaces_dir, &composefiles);
        assert!(result.is_ok());

        // Only the valid part should be written
        let content = std::fs::read_to_string(workspace.join("output.md")).unwrap();
        assert_eq!(content, "ok");
    }
}
