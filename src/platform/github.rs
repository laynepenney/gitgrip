//! GitHub platform adapter

use async_trait::async_trait;
use octocrab::Octocrab;
use std::env;

use super::traits::{HostingPlatform, LinkedPRRef, PlatformError};
use super::types::*;
use crate::core::manifest::PlatformType;

#[cfg(feature = "telemetry")]
use crate::telemetry::metrics::GLOBAL_METRICS;
#[cfg(feature = "telemetry")]
use std::time::Instant;
#[cfg(feature = "telemetry")]
use tracing::debug;

/// GitHub API adapter
pub struct GitHubAdapter {
    base_url: Option<String>,
}

impl GitHubAdapter {
    /// Create a new GitHub adapter
    pub fn new(base_url: Option<&str>) -> Self {
        Self {
            base_url: base_url.map(|s| s.to_string()),
        }
    }

    /// Get configured Octocrab instance
    async fn get_client(&self) -> Result<Octocrab, PlatformError> {
        let token = self.get_token().await?;

        let mut builder = Octocrab::builder().personal_token(token);

        if let Some(ref base_url) = self.base_url {
            builder = builder
                .base_uri(base_url)
                .map_err(|e| PlatformError::ApiError(format!("Invalid base URL: {}", e)))?;
        }

        builder
            .build()
            .map_err(|e| PlatformError::ApiError(format!("Failed to create client: {}", e)))
    }
}

#[async_trait]
impl HostingPlatform for GitHubAdapter {
    fn platform_type(&self) -> PlatformType {
        PlatformType::GitHub
    }

    async fn get_token(&self) -> Result<String, PlatformError> {
        // Try environment variables first
        if let Ok(token) = env::var("GITHUB_TOKEN") {
            return Ok(token);
        }
        if let Ok(token) = env::var("GH_TOKEN") {
            return Ok(token);
        }

        // Try gh CLI auth
        let output = tokio::process::Command::new("gh")
            .args(["auth", "token"])
            .output()
            .await
            .map_err(|e| PlatformError::AuthError(format!("Failed to run gh auth: {}", e)))?;

        if output.status.success() {
            let token = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if !token.is_empty() {
                return Ok(token);
            }
        }

        Err(PlatformError::AuthError(
            "No GitHub token found. Set GITHUB_TOKEN or run 'gh auth login'".to_string(),
        ))
    }

    async fn create_pull_request(
        &self,
        owner: &str,
        repo: &str,
        head: &str,
        base: &str,
        title: &str,
        body: Option<&str>,
        draft: bool,
    ) -> Result<PRCreateResult, PlatformError> {
        #[cfg(feature = "telemetry")]
        let start = Instant::now();

        let client = self.get_client().await?;

        let result = client
            .pulls(owner, repo)
            .create(title, head, base)
            .body(body.unwrap_or(""))
            .draft(draft)
            .send()
            .await;

        #[cfg(feature = "telemetry")]
        {
            let duration = start.elapsed();
            let success = result.is_ok();
            GLOBAL_METRICS.record_platform("github", "create_pr", duration, success);
            debug!(
                owner,
                repo,
                head,
                base,
                draft,
                success,
                duration_ms = duration.as_millis() as u64,
                "GitHub create PR complete"
            );
        }

        let pr =
            result.map_err(|e| PlatformError::ApiError(format!("Failed to create PR: {}", e)))?;

        Ok(PRCreateResult {
            number: pr.number,
            url: pr.html_url.map(|u| u.to_string()).unwrap_or_default(),
        })
    }

    async fn get_pull_request(
        &self,
        owner: &str,
        repo: &str,
        pull_number: u64,
    ) -> Result<PullRequest, PlatformError> {
        let client = self.get_client().await?;

        let pr = client
            .pulls(owner, repo)
            .get(pull_number)
            .await
            .map_err(|e| {
                if e.to_string().contains("404") {
                    PlatformError::NotFound(format!("PR #{} not found", pull_number))
                } else {
                    PlatformError::ApiError(format!("Failed to get PR: {}", e))
                }
            })?;

        let state = if pr.merged_at.is_some() {
            PRState::Merged
        } else {
            match pr.state {
                Some(octocrab::models::IssueState::Open) => PRState::Open,
                Some(octocrab::models::IssueState::Closed) => PRState::Closed,
                _ => PRState::Open,
            }
        };

        Ok(PullRequest {
            number: pr.number,
            url: pr.html_url.map(|u| u.to_string()).unwrap_or_default(),
            title: pr.title.clone().unwrap_or_default(),
            body: pr.body.clone().unwrap_or_default(),
            state,
            merged: pr.merged_at.is_some(),
            mergeable: pr.mergeable,
            head: PRHead {
                ref_name: pr.head.ref_field.clone(),
                sha: pr.head.sha.clone(),
            },
            base: PRBase {
                ref_name: pr.base.ref_field.clone(),
            },
        })
    }

    async fn update_pull_request_body(
        &self,
        owner: &str,
        repo: &str,
        pull_number: u64,
        body: &str,
    ) -> Result<(), PlatformError> {
        let client = self.get_client().await?;

        client
            .pulls(owner, repo)
            .update(pull_number)
            .body(body)
            .send()
            .await
            .map_err(|e| PlatformError::ApiError(format!("Failed to update PR body: {}", e)))?;

        Ok(())
    }

    async fn merge_pull_request(
        &self,
        owner: &str,
        repo: &str,
        pull_number: u64,
        method: Option<MergeMethod>,
        _delete_branch: bool,
    ) -> Result<bool, PlatformError> {
        #[cfg(feature = "telemetry")]
        let start = Instant::now();

        let client = self.get_client().await?;

        let merge_method = match method.unwrap_or(MergeMethod::Merge) {
            MergeMethod::Merge => octocrab::params::pulls::MergeMethod::Merge,
            MergeMethod::Squash => octocrab::params::pulls::MergeMethod::Squash,
            MergeMethod::Rebase => octocrab::params::pulls::MergeMethod::Rebase,
        };

        let result = client
            .pulls(owner, repo)
            .merge(pull_number)
            .method(merge_method)
            .send()
            .await;

        #[cfg(feature = "telemetry")]
        {
            let duration = start.elapsed();
            let success = result.is_ok();
            GLOBAL_METRICS.record_platform("github", "merge_pr", duration, success);
            debug!(
                owner,
                repo,
                pull_number,
                success,
                duration_ms = duration.as_millis() as u64,
                "GitHub merge PR complete"
            );
        }

        match result {
            Ok(merge) => Ok(merge.merged),
            Err(e) => {
                let error_str = e.to_string();
                if error_str.contains("405") || error_str.contains("not mergeable") {
                    Ok(false)
                } else {
                    Err(PlatformError::ApiError(format!(
                        "Failed to merge PR: {}",
                        e
                    )))
                }
            }
        }
    }

    async fn find_pr_by_branch(
        &self,
        owner: &str,
        repo: &str,
        branch: &str,
    ) -> Result<Option<PRCreateResult>, PlatformError> {
        let client = self.get_client().await?;

        let prs = client
            .pulls(owner, repo)
            .list()
            .state(octocrab::params::State::Open)
            .head(format!("{}:{}", owner, branch))
            .send()
            .await
            .map_err(|e| PlatformError::ApiError(format!("Failed to find PR: {}", e)))?;

        if let Some(pr) = prs.items.first() {
            Ok(Some(PRCreateResult {
                number: pr.number,
                url: pr
                    .html_url
                    .as_ref()
                    .map(|u| u.to_string())
                    .unwrap_or_default(),
            }))
        } else {
            Ok(None)
        }
    }

    async fn is_pull_request_approved(
        &self,
        owner: &str,
        repo: &str,
        pull_number: u64,
    ) -> Result<bool, PlatformError> {
        let reviews = self
            .get_pull_request_reviews(owner, repo, pull_number)
            .await?;

        // Check for at least one approval and no changes requested
        let has_approval = reviews.iter().any(|r| r.state == "APPROVED");
        let has_changes_requested = reviews.iter().any(|r| r.state == "CHANGES_REQUESTED");

        Ok(has_approval && !has_changes_requested)
    }

    async fn get_pull_request_reviews(
        &self,
        owner: &str,
        repo: &str,
        pull_number: u64,
    ) -> Result<Vec<PRReview>, PlatformError> {
        let client = self.get_client().await?;

        let reviews = client
            .pulls(owner, repo)
            .list_reviews(pull_number)
            .send()
            .await
            .map_err(|e| PlatformError::ApiError(format!("Failed to get reviews: {}", e)))?;

        Ok(reviews
            .items
            .iter()
            .map(|r| PRReview {
                state: r.state.map(|s| format!("{:?}", s)).unwrap_or_default(),
                user: r.user.as_ref().map(|u| u.login.clone()).unwrap_or_default(),
            })
            .collect())
    }

    async fn get_status_checks(
        &self,
        owner: &str,
        repo: &str,
        ref_name: &str,
    ) -> Result<StatusCheckResult, PlatformError> {
        // Get combined status using raw API call
        let token = self.get_token().await?;
        let base_url = self.base_url.as_deref().unwrap_or("https://api.github.com");
        let url = format!(
            "{}/repos/{}/{}/commits/{}/status",
            base_url, owner, repo, ref_name
        );

        let http_client = reqwest::Client::new();
        let response = http_client
            .get(&url)
            .header("Authorization", format!("Bearer {}", token))
            .header("Accept", "application/vnd.github.v3+json")
            .header("User-Agent", "gitgrip")
            .send()
            .await
            .map_err(|e| PlatformError::NetworkError(e.to_string()))?;

        if !response.status().is_success() {
            return Err(PlatformError::ApiError(format!(
                "Failed to get status: {}",
                response.status()
            )));
        }

        #[derive(serde::Deserialize)]
        struct CombinedStatus {
            state: String,
            statuses: Vec<StatusEntry>,
        }

        #[derive(serde::Deserialize)]
        struct StatusEntry {
            context: Option<String>,
            state: String,
        }

        let status: CombinedStatus = response
            .json()
            .await
            .map_err(|e| PlatformError::ParseError(e.to_string()))?;

        let state = match status.state.as_str() {
            "success" => CheckState::Success,
            "failure" | "error" => CheckState::Failure,
            _ => CheckState::Pending,
        };

        let statuses = status
            .statuses
            .iter()
            .map(|s| StatusCheck {
                context: s.context.clone().unwrap_or_default(),
                state: s.state.clone(),
            })
            .collect();

        Ok(StatusCheckResult { state, statuses })
    }

    async fn get_allowed_merge_methods(
        &self,
        owner: &str,
        repo: &str,
    ) -> Result<AllowedMergeMethods, PlatformError> {
        let client = self.get_client().await?;

        let repo_info = client
            .repos(owner, repo)
            .get()
            .await
            .map_err(|e| PlatformError::ApiError(format!("Failed to get repo: {}", e)))?;

        Ok(AllowedMergeMethods {
            merge: repo_info.allow_merge_commit.unwrap_or(true),
            squash: repo_info.allow_squash_merge.unwrap_or(true),
            rebase: repo_info.allow_rebase_merge.unwrap_or(true),
        })
    }

    async fn get_pull_request_diff(
        &self,
        owner: &str,
        repo: &str,
        pull_number: u64,
    ) -> Result<String, PlatformError> {
        let token = self.get_token().await?;
        let base_url = self.base_url.as_deref().unwrap_or("https://api.github.com");

        let url = format!(
            "{}/repos/{}/{}/pulls/{}",
            base_url, owner, repo, pull_number
        );

        let client = reqwest::Client::new();
        let response = client
            .get(&url)
            .header("Authorization", format!("Bearer {}", token))
            .header("Accept", "application/vnd.github.v3.diff")
            .header("User-Agent", "gitgrip")
            .send()
            .await
            .map_err(|e| PlatformError::NetworkError(e.to_string()))?;

        if !response.status().is_success() {
            return Err(PlatformError::ApiError(format!(
                "Failed to get diff: {}",
                response.status()
            )));
        }

        response
            .text()
            .await
            .map_err(|e| PlatformError::NetworkError(e.to_string()))
    }

    fn parse_repo_url(&self, url: &str) -> Option<ParsedRepoInfo> {
        // SSH format: git@github.com:owner/repo.git
        if url.starts_with("git@github.com:") {
            let path = url.trim_start_matches("git@github.com:");
            let path = path.trim_end_matches(".git");
            let parts: Vec<&str> = path.split('/').collect();
            if parts.len() >= 2 {
                return Some(ParsedRepoInfo {
                    owner: parts[0].to_string(),
                    repo: parts[parts.len() - 1].to_string(),
                    project: None,
                    platform: Some(PlatformType::GitHub),
                });
            }
        }

        // HTTPS format: https://github.com/owner/repo.git
        if url.contains("github.com") {
            let url = url.trim_end_matches(".git");
            let parts: Vec<&str> = url.split('/').collect();
            if parts.len() >= 2 {
                let owner_idx = parts.iter().position(|&p| p == "github.com")? + 1;
                if owner_idx + 1 < parts.len() {
                    return Some(ParsedRepoInfo {
                        owner: parts[owner_idx].to_string(),
                        repo: parts[owner_idx + 1].to_string(),
                        project: None,
                        platform: Some(PlatformType::GitHub),
                    });
                }
            }
        }

        None
    }

    fn matches_url(&self, url: &str) -> bool {
        url.contains("github.com")
    }

    async fn create_repository(
        &self,
        owner: &str,
        name: &str,
        description: Option<&str>,
        private: bool,
    ) -> Result<String, PlatformError> {
        let token = self.get_token().await?;
        let base_url = self.base_url.as_deref().unwrap_or("https://api.github.com");

        // Check if owner is the authenticated user or an org
        // First, get the authenticated user
        let http_client = reqwest::Client::new();

        let user_response = http_client
            .get(format!("{}/user", base_url))
            .header("Authorization", format!("Bearer {}", token))
            .header("Accept", "application/vnd.github.v3+json")
            .header("User-Agent", "gitgrip")
            .send()
            .await
            .map_err(|e| PlatformError::NetworkError(e.to_string()))?;

        #[derive(serde::Deserialize)]
        struct User {
            login: String,
        }

        let current_user: User = user_response
            .json()
            .await
            .map_err(|e| PlatformError::ParseError(e.to_string()))?;

        // Determine the API endpoint based on whether owner is the user or an org
        let url = if owner.eq_ignore_ascii_case(&current_user.login) {
            format!("{}/user/repos", base_url)
        } else {
            format!("{}/orgs/{}/repos", base_url, owner)
        };

        #[derive(serde::Serialize)]
        struct CreateRepoRequest {
            name: String,
            #[serde(skip_serializing_if = "Option::is_none")]
            description: Option<String>,
            private: bool,
            auto_init: bool,
        }

        let response = http_client
            .post(&url)
            .header("Authorization", format!("Bearer {}", token))
            .header("Accept", "application/vnd.github.v3+json")
            .header("User-Agent", "gitgrip")
            .json(&CreateRepoRequest {
                name: name.to_string(),
                description: description.map(|s| s.to_string()),
                private,
                auto_init: true, // Initialize with a README so there's a default branch
            })
            .send()
            .await
            .map_err(|e| PlatformError::NetworkError(e.to_string()))?;

        if !response.status().is_success() {
            let status = response.status();
            let error_text = response.text().await.unwrap_or_default();
            return Err(PlatformError::ApiError(format!(
                "Failed to create repository ({}): {}",
                status, error_text
            )));
        }

        #[derive(serde::Deserialize)]
        struct RepoResponse {
            ssh_url: String,
        }

        let repo: RepoResponse = response
            .json()
            .await
            .map_err(|e| PlatformError::ParseError(e.to_string()))?;

        Ok(repo.ssh_url)
    }

    async fn delete_repository(&self, owner: &str, name: &str) -> Result<(), PlatformError> {
        let token = self.get_token().await?;
        let base_url = self.base_url.as_deref().unwrap_or("https://api.github.com");

        let http_client = reqwest::Client::new();
        let url = format!("{}/repos/{}/{}", base_url, owner, name);

        let response = http_client
            .delete(&url)
            .header("Authorization", format!("Bearer {}", token))
            .header("Accept", "application/vnd.github.v3+json")
            .header("User-Agent", "gitgrip")
            .send()
            .await
            .map_err(|e| PlatformError::NetworkError(e.to_string()))?;

        if response.status() == 404 {
            return Err(PlatformError::NotFound(format!(
                "Repository {}/{} not found",
                owner, name
            )));
        }

        if !response.status().is_success() {
            let status = response.status();
            let error_text = response.text().await.unwrap_or_default();
            return Err(PlatformError::ApiError(format!(
                "Failed to delete repository ({}): {}",
                status, error_text
            )));
        }

        Ok(())
    }

    fn generate_linked_pr_comment(&self, links: &[LinkedPRRef]) -> String {
        if links.is_empty() {
            return String::new();
        }

        let mut comment = String::from("<!-- gitgrip-linked-prs\n");
        for link in links {
            comment.push_str(&format!("{}:{}\n", link.repo_name, link.number));
        }
        comment.push_str("-->");
        comment
    }

    fn parse_linked_pr_comment(&self, body: &str) -> Vec<LinkedPRRef> {
        let start_marker = "<!-- gitgrip-linked-prs";
        let end_marker = "-->";

        let Some(start) = body.find(start_marker) else {
            return Vec::new();
        };

        let content_start = start + start_marker.len();
        let Some(end) = body[content_start..].find(end_marker) else {
            return Vec::new();
        };

        let content = &body[content_start..content_start + end];

        content
            .lines()
            .filter_map(|line| {
                let line = line.trim();
                if line.is_empty() {
                    return None;
                }

                let parts: Vec<&str> = line.splitn(2, ':').collect();
                if parts.len() != 2 {
                    return None;
                }

                let number = parts[1].parse().ok()?;
                Some(LinkedPRRef {
                    repo_name: parts[0].to_string(),
                    number,
                })
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_github_ssh_url() {
        let adapter = GitHubAdapter::new(None);

        let result = adapter.parse_repo_url("git@github.com:user/repo.git");
        assert!(result.is_some());
        let info = result.unwrap();
        assert_eq!(info.owner, "user");
        assert_eq!(info.repo, "repo");
    }

    #[test]
    fn test_parse_github_https_url() {
        let adapter = GitHubAdapter::new(None);

        let result = adapter.parse_repo_url("https://github.com/user/repo.git");
        assert!(result.is_some());
        let info = result.unwrap();
        assert_eq!(info.owner, "user");
        assert_eq!(info.repo, "repo");
    }

    #[test]
    fn test_matches_url() {
        let adapter = GitHubAdapter::new(None);

        assert!(adapter.matches_url("git@github.com:user/repo.git"));
        assert!(adapter.matches_url("https://github.com/user/repo.git"));
        assert!(!adapter.matches_url("git@gitlab.com:user/repo.git"));
    }

    #[test]
    fn test_linked_pr_comment_roundtrip() {
        let adapter = GitHubAdapter::new(None);

        let links = vec![
            LinkedPRRef {
                repo_name: "frontend".to_string(),
                number: 42,
            },
            LinkedPRRef {
                repo_name: "backend".to_string(),
                number: 123,
            },
        ];

        let comment = adapter.generate_linked_pr_comment(&links);
        let parsed = adapter.parse_linked_pr_comment(&comment);

        assert_eq!(parsed.len(), 2);
        assert_eq!(parsed[0].repo_name, "frontend");
        assert_eq!(parsed[0].number, 42);
        assert_eq!(parsed[1].repo_name, "backend");
        assert_eq!(parsed[1].number, 123);
    }
}
