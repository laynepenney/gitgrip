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

/// Process composefile entries, writing composed files to the workspace root.
///
/// Each composefile concatenates parts in order. Parts can come from:
/// - A gripspace: reads from `.gitgrip/spaces/<name>/<src>`
/// - The local manifest: reads from the manifest content directory
pub fn process_composefiles(
    workspace_root: &Path,
    manifests_dir: &Path,
    spaces_dir: &Path,
    composefiles: &[ComposeFileConfig],
) -> anyhow::Result<()> {
    for compose in composefiles {
        validate_relative_source_path(&compose.dest, "composefile dest")
            .map_err(anyhow::Error::msg)?;

        let separator = compose.separator.as_deref().unwrap_or("\n\n");
        let mut parts_content: Vec<String> = Vec::new();

        for part in &compose.parts {
            let source_path = if let Some(ref gs_name) = part.gripspace {
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
    use tempfile::TempDir;

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
        let gripspaces_dir = workspace.join(".gitgrip").join("spaces");

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
        let gripspaces_dir = workspace.join(".gitgrip").join("spaces");

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
        let gripspaces_dir = workspace.join(".gitgrip").join("spaces");

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
        let result =
            resolve_file_source("gripspace:valid:../../etc/passwd", repo_path, gripspaces_dir);
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
        let gripspaces_dir = workspace.join(".gitgrip").join("spaces");

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
                gripspace: None,
                src: "file.md".to_string(),
            }],
            separator: None,
        }];

        let result =
            process_composefiles(workspace, &manifests_dir, &gripspaces_dir, &composefiles);
        assert!(result.is_err());
    }
}
