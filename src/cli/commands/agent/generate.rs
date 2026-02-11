//! Agent context generation — generate context files for multiple AI tools from a single source.

use std::path::{Path, PathBuf};

use crate::cli::output::Output;
use crate::core::manifest::{AgentContextTarget, Manifest};
use crate::core::manifest_paths;
use crate::core::repo::filter_repos;
use crate::files::resolve_file_source;

/// Run the agent generate-context command.
///
/// Reads `workspace.agent.context_source`, applies format adapters,
/// and writes to each configured target destination.
pub fn run_agent_generate_context(
    workspace_root: &Path,
    manifest: &Manifest,
    dry_run: bool,
    quiet: bool,
) -> anyhow::Result<()> {
    let agent_config = manifest.workspace.as_ref().and_then(|w| w.agent.as_ref());

    let targets = match agent_config.and_then(|a| a.targets.as_ref()) {
        Some(targets) if !targets.is_empty() => targets,
        _ => {
            if !quiet {
                Output::info("No agent context targets configured");
            }
            return Ok(());
        }
    };

    // Read context source content (if configured)
    let source_content = if let Some(source) = agent_config.and_then(|a| a.context_source.as_ref())
    {
        let manifests_dir = manifest_paths::resolve_manifest_content_dir(workspace_root);
        let spaces_dir = manifest_paths::spaces_dir(workspace_root);
        let source_path = resolve_file_source(source, &manifests_dir, &spaces_dir)
            .map_err(|e| anyhow::anyhow!("Failed to resolve context_source '{}': {}", source, e))?;

        Some(std::fs::read_to_string(&source_path).map_err(|e| {
            anyhow::anyhow!(
                "Failed to read context_source '{}': {}",
                source_path.display(),
                e
            )
        })?)
    } else {
        None
    };

    let mut generated = 0;

    for target in targets {
        if target.dest.contains("{repo}") {
            generated +=
                generate_per_repo(workspace_root, manifest, target, &source_content, dry_run)?;
        } else {
            generated += generate_workspace_level(
                workspace_root,
                manifest,
                target,
                &source_content,
                dry_run,
            )?;
        }
    }

    if !quiet {
        if dry_run {
            Output::info(&format!(
                "Dry run: {} file(s) would be generated",
                generated
            ));
        } else {
            Output::success(&format!("Generated {} context file(s)", generated));
        }
    }

    Ok(())
}

/// Generate a single workspace-level context file (no {repo} placeholder).
fn generate_workspace_level(
    workspace_root: &Path,
    manifest: &Manifest,
    target: &AgentContextTarget,
    source_content: &Option<String>,
    dry_run: bool,
) -> anyhow::Result<usize> {
    let content = match source_content {
        Some(src) => src.clone(),
        None => {
            // No context_source — skip workspace-level targets that need content
            return Ok(0);
        }
    };

    // Apply compose_with: append additional files
    let content = apply_compose_with(workspace_root, manifest, &content, target)?;

    // Apply format adapter
    let formatted = apply_format(&target.format, &content, None);

    let dest_path = workspace_root.join(&target.dest);

    if dry_run {
        Output::info(&format!(
            "  {} -> {} ({} bytes)",
            target.format,
            target.dest,
            formatted.len()
        ));
    } else {
        if let Some(parent) = dest_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(&dest_path, &formatted)?;
    }

    Ok(1)
}

/// Generate per-repo context files ({repo} placeholder in dest).
fn generate_per_repo(
    workspace_root: &Path,
    manifest: &Manifest,
    target: &AgentContextTarget,
    source_content: &Option<String>,
    dry_run: bool,
) -> anyhow::Result<usize> {
    let workspace_root_buf = workspace_root.to_path_buf();
    let repos = filter_repos(manifest, &workspace_root_buf, None, None, false);
    let mut count = 0;

    for repo in &repos {
        let agent = match &repo.agent {
            Some(a) => a,
            None => continue,
        };

        let dest = target.dest.replace("{repo}", &repo.name);
        let dest_path = workspace_root.join(&dest);

        // Build per-repo content from agent metadata
        let repo_content = build_repo_skill_content(&repo.name, agent, source_content);

        // Apply format adapter
        let formatted = apply_format(&target.format, &repo_content, Some(&repo.name));

        if dry_run {
            Output::info(&format!(
                "  {} -> {} ({} bytes)",
                target.format,
                dest,
                formatted.len()
            ));
        } else {
            if let Some(parent) = dest_path.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::write(&dest_path, &formatted)?;
        }

        count += 1;
    }

    Ok(count)
}

/// Build skill content for a single repository from its agent config.
fn build_repo_skill_content(
    repo_name: &str,
    agent: &crate::core::manifest::RepoAgentConfig,
    _source_content: &Option<String>,
) -> String {
    let mut content = String::new();

    content.push_str(&format!("# {}\n\n", repo_name));

    if let Some(desc) = &agent.description {
        content.push_str(&format!("{}\n\n", desc));
    }

    let mut fields = Vec::new();
    if let Some(lang) = &agent.language {
        fields.push(format!("Language: {}", lang));
    }
    if let Some(build) = &agent.build {
        fields.push(format!("Build: `{}`", build));
    }
    if let Some(test) = &agent.test {
        fields.push(format!("Test: `{}`", test));
    }
    if let Some(lint) = &agent.lint {
        fields.push(format!("Lint: `{}`", lint));
    }
    if let Some(fmt) = &agent.format {
        fields.push(format!("Format: `{}`", fmt));
    }

    if !fields.is_empty() {
        for field in &fields {
            content.push_str(&format!("{}\n", field));
        }
    }

    content
}

/// Apply compose_with files — read additional files and append to content.
fn apply_compose_with(
    workspace_root: &Path,
    manifest: &Manifest,
    base_content: &str,
    target: &AgentContextTarget,
) -> anyhow::Result<String> {
    let compose_files = match &target.compose_with {
        Some(files) if !files.is_empty() => files,
        _ => return Ok(base_content.to_string()),
    };

    let manifests_dir = manifest_paths::resolve_manifest_content_dir(workspace_root);
    let spaces_dir = manifest_paths::spaces_dir(workspace_root);

    let mut result = base_content.to_string();

    for src in compose_files {
        // Try workspace-relative first (most common for compose_with),
        // then gripspace resolution, then manifest-relative
        let workspace_relative = workspace_root.join(src);
        let file_path = if workspace_relative.exists() {
            workspace_relative
        } else {
            match resolve_file_source(src, &manifests_dir, &spaces_dir) {
                Ok(p) => p,
                Err(_) => workspace_relative,
            }
        };

        match std::fs::read_to_string(&file_path) {
            Ok(content) => {
                result.push_str("\n\n");
                result.push_str(&content);
            }
            Err(e) => {
                Output::warning(&format!("compose_with '{}' not found: {}", src, e));
            }
        }
    }

    // Ensure unused variable warning doesn't fire
    let _ = manifest;

    Ok(result)
}

/// Apply format adapter to transform content for the target AI tool.
fn apply_format(format: &str, content: &str, repo_name: Option<&str>) -> String {
    match format {
        "raw" => content.to_string(),
        "claude" => format_claude(content, repo_name),
        "opencode" | "codex" => format_opencode(content, repo_name),
        "cursor" => format_cursor(content),
        _ => content.to_string(),
    }
}

/// Claude format: add YAML frontmatter for per-repo, pass through for workspace.
fn format_claude(content: &str, repo_name: Option<&str>) -> String {
    match repo_name {
        Some(name) => {
            let mut out = String::new();
            out.push_str("---\n");
            out.push_str(&format!("name: {}\n", name));
            out.push_str("---\n\n");
            out.push_str(content);
            out
        }
        None => content.to_string(),
    }
}

/// OpenCode/Codex format: add simple frontmatter for per-repo.
fn format_opencode(content: &str, repo_name: Option<&str>) -> String {
    match repo_name {
        Some(name) => {
            let mut out = String::new();
            out.push_str("---\n");
            out.push_str(&format!("name: {}\n", name));
            out.push_str("---\n\n");
            out.push_str(content);
            out
        }
        None => content.to_string(),
    }
}

/// Cursor format: strip markdown heading markers for .cursorrules format.
fn format_cursor(content: &str) -> String {
    let mut out = String::new();
    for line in content.lines() {
        if line.starts_with('#') {
            // Strip heading markers, keep the text
            let stripped = line.trim_start_matches('#').trim();
            out.push_str(stripped);
        } else {
            out.push_str(line);
        }
        out.push('\n');
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_apply_format_raw() {
        let content = "# Hello\nWorld";
        assert_eq!(apply_format("raw", content, None), content);
    }

    #[test]
    fn test_apply_format_claude_workspace() {
        let content = "# Workspace Context\nRules here";
        let result = apply_format("claude", content, None);
        assert_eq!(result, content);
    }

    #[test]
    fn test_apply_format_claude_per_repo() {
        let content = "# myrepo\nDescription";
        let result = apply_format("claude", content, Some("myrepo"));
        assert!(result.starts_with("---\n"));
        assert!(result.contains("name: myrepo"));
        assert!(result.contains("# myrepo\nDescription"));
    }

    #[test]
    fn test_apply_format_opencode_per_repo() {
        let content = "# lib\nA library";
        let result = apply_format("opencode", content, Some("lib"));
        assert!(result.starts_with("---\n"));
        assert!(result.contains("name: lib"));
    }

    #[test]
    fn test_apply_format_codex_per_repo() {
        let result = apply_format("codex", "content", Some("app"));
        assert!(result.contains("name: app"));
    }

    #[test]
    fn test_apply_format_cursor() {
        let content = "# Title\n## Subtitle\nBody text";
        let result = apply_format("cursor", content, None);
        assert!(result.contains("Title\n"));
        assert!(result.contains("Subtitle\n"));
        assert!(result.contains("Body text\n"));
        assert!(!result.contains("# "));
    }

    #[test]
    fn test_apply_format_unknown_passthrough() {
        let content = "some content";
        assert_eq!(apply_format("unknown", content, None), content);
    }

    #[test]
    fn test_build_repo_skill_content() {
        let agent = crate::core::manifest::RepoAgentConfig {
            description: Some("Test app".to_string()),
            language: Some("Rust".to_string()),
            build: Some("cargo build".to_string()),
            test: Some("cargo test".to_string()),
            lint: None,
            format: None,
        };

        let content = build_repo_skill_content("myapp", &agent, &None);
        assert!(content.contains("# myapp"));
        assert!(content.contains("Test app"));
        assert!(content.contains("Language: Rust"));
        assert!(content.contains("Build: `cargo build`"));
        assert!(content.contains("Test: `cargo test`"));
    }
}
