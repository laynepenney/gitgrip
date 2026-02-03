//! Bitbucket platform adapter

use async_trait::async_trait;
use reqwest::Client;
use serde::Deserialize;
use std::env;
use std::time::Duration;

use super::traits::{HostingPlatform, LinkedPRRef, PlatformError};
use super::types::*;
use crate::core::manifest::PlatformType;

/// Default connection timeout in seconds
const CONNECT_TIMEOUT_SECS: u64 = 10;
/// Default request timeout in seconds
const REQUEST_TIMEOUT_SECS: u64 = 30;

/// Bitbucket API adapter
pub struct BitbucketAdapter {
    base_url: String,
}

#[allow(dead_code)]
impl BitbucketAdapter {
    pub fn new(base_url: Option<&str>) -> Self {
        Self {
            base_url: base_url
                .unwrap_or("https://api.bitbucket.org/2.0")
                .to_string(),
        }
    }

    fn api_base_url(&self, owner: &str, repo: &str) -> String {
        format!("{}/repositories/{}/{}", self.base_url, owner, repo)
    }

    /// Create a configured HTTP client with timeouts
    fn http_client() -> Client {
        Client::builder()
            .connect_timeout(Duration::from_secs(CONNECT_TIMEOUT_SECS))
            .timeout(Duration::from_secs(REQUEST_TIMEOUT_SECS))
            .build()
            .unwrap_or_else(|_| Client::new())
    }
}

// Bitbucket API response structures
#[derive(Debug, Deserialize)]
struct BitbucketPR {
    id: u64,
    title: String,
    description: Option<String>,
    state: String,
    source: branch::Source,
    destination: branch::Destination,
    links: Links,
}

#[derive(Debug, Deserialize)]
struct Links {
    #[serde(rename = "html")]
    html_link: HtmlLink,
}

#[derive(Debug, Deserialize)]
struct HtmlLink {
    href: String,
}

mod branch {
    use serde::Deserialize;

    #[derive(Debug, Deserialize)]
    pub struct Source {
        pub branch: Branch,
    }

    #[derive(Debug, Deserialize)]
    pub struct Destination {
        pub branch: Branch,
    }

    #[derive(Debug, Deserialize)]
    pub struct Branch {
        pub name: String,
        pub commit: Commit,
    }

    #[derive(Debug, Deserialize)]
    pub struct Commit {
        pub hash: String,
    }
}

#[derive(Debug, Deserialize)]
struct PagedList<T> {
    values: Vec<T>,
}

#[async_trait]
impl HostingPlatform for BitbucketAdapter {
    fn platform_type(&self) -> PlatformType {
        PlatformType::Bitbucket
    }

    async fn get_token(&self) -> Result<String, PlatformError> {
        env::var("BITBUCKET_TOKEN")
            .map_err(|_| PlatformError::AuthError("BITBUCKET_TOKEN not set".to_string()))
    }

    async fn create_pull_request(
        &self,
        owner: &str,
        repo: &str,
        head: &str,
        base: &str,
        title: &str,
        body: Option<&str>,
        _draft: bool,
    ) -> Result<PRCreateResult, PlatformError> {
        let client = Self::http_client();
        let token = self.get_token().await?;

        let url = format!("{}/pullrequests", self.api_base_url(owner, repo));

        let body_json = serde_json::json!({
            "title": title,
            "source": { "branch": { "name": head } },
            "destination": { "branch": { "name": base } },
            "description": body.unwrap_or(""),
            "close_source_branch": false
        });

        let response = client
            .post(&url)
            .header("Authorization", format!("Bearer {}", token))
            .header("Content-Type", "application/json")
            .json(&body_json)
            .send()
            .await
            .map_err(|e| PlatformError::NetworkError(e.to_string()))?;

        if !response.status().is_success() {
            let error = response.text().await.unwrap_or_default();
            return Err(PlatformError::ApiError(format!("Create PR failed: {}", error)));
        }

        let pr: BitbucketPR = response.json().await.map_err(|e| {
            PlatformError::ParseError(format!("Failed to parse PR response: {}", e))
        })?;

        Ok(PRCreateResult {
            number: pr.id,
            url: pr.links.html_link.href,
            state: PRState::Open,
        })
    }

    async fn get_pull_request(
        &self,
        owner: &str,
        repo: &str,
        pull_number: u64,
    ) -> Result<PullRequest, PlatformError> {
        let client = Self::http_client();
        let token = self.get_token().await?;

        let url = format!(
            "{}/pullrequests/{}",
            self.api_base_url(owner, repo),
            pull_number
        );

        let response = client
            .get(&url)
            .header("Authorization", format!("Bearer {}", token))
            .send()
            .await
            .map_err(|e| PlatformError::NetworkError(e.to_string()))?;

        if !response.status().is_success() {
            return Err(PlatformError::NotFound(format!(
                "PR #{} not found in {}/{}",
                pull_number, owner, repo
            )));
        }

        let pr: BitbucketPR = response.json().await.map_err(|e| {
            PlatformError::ParseError(format!("Failed to parse PR response: {}", e))
        })?;

        let state = match pr.state.as_str() {
            "OPEN" => PRState::Open,
            "MERGED" => PRState::Merged,
            "DECLINED" | "SUPERSEDED" => PRState::Closed,
            _ => PRState::Open,
        };

        Ok(PullRequest {
            number: pr.id,
            title: pr.title,
            body: pr.description.unwrap_or_default(),
            state,
            head: PRHead {
                refname: pr.source.branch.name.clone(),
                oid: pr.source.branch.commit.hash,
            },
            base: PRBase {
                refname: pr.destination.branch.name.clone(),
                oid: pr.destination.branch.commit.hash,
            },
            url: pr.links.html_link.href,
            merged_at: if state == PRState::Merged { Some(chrono::Utc::now()) } else { None },
        })
    }

    async fn update_pull_request_body(
        &self,
        owner: &str,
        repo: &str,
        pull_number: u64,
        body: &str,
    ) -> Result<(), PlatformError> {
        let client = Self::http_client();
        let token = self.get_token().await?;

        let url = format!(
            "{}/pullrequests/{}",
            self.api_base_url(owner, repo),
            pull_number
        );

        let body_json = serde_json::json!({ "description": body });

        let response = client
            .put(&url)
            .header("Authorization", format!("Bearer {}", token))
            .header("Content-Type", "application/json")
            .json(&body_json)
            .send()
            .await
            .map_err(|e| PlatformError::NetworkError(e.to_string()))?;

        if !response.status().is_success() {
            let error = response.text().await.unwrap_or_default();
            return Err(PlatformError::ApiError(format!("Update PR failed: {}", error)));
        }

        Ok(())
    }

    async fn merge_pull_request(
        &self,
        owner: &str,
        repo: &str,
        pull_number: u64,
        method: Option<MergeMethod>,
        delete_branch: bool,
    ) -> Result<bool, PlatformError> {
        let client = Self::http_client();
        let token = self.get_token().await?;

        let url = format!(
            "{}/pullrequests/{}/merge",
            self.api_base_url(owner, repo),
            pull_number
        );

        // Bitbucket supports merge (default) and squash
        let message = match method {
            Some(MergeMethod::Squash) => Some("merged with squash".to_string()),
            Some(MergeMethod::Rebase) => None, // Bitbucket doesn't support rebase
            _ => None,
        };

        let mut body_json = serde_json::json!({ "close_source_branch": delete_branch });
        if let Some(msg) = message {
            body_json["message"] = serde_json::Value::String(msg);
        }

        let response = client
            .post(&url)
            .header("Authorization", format!("Bearer {}", token))
            .header("Content-Type", "application/json")
            .json(&body_json)
            .send()
            .await
            .map_err(|e| PlatformError::NetworkError(e.to_string()))?;

        if !response.status().is_success() {
            let error = response.text().await.unwrap_or_default();
            return Err(PlatformError::ApiError(format!("Merge failed: {}", error)));
        }

        Ok(true)
    }

    async fn find_pr_by_branch(
        &self,
        owner: &str,
        repo: &str,
        branch: &str,
    ) -> Result<Option<PRCreateResult>, PlatformError> {
        let client = Self::http_client();
        let token = self.get_token().await?;

        let url = format!(
            "{}/pullrequests?state=OPEN&source.branch.name={}",
            self.api_base_url(owner, repo),
            urlencoding::encode(branch)
        );

        let response = client
            .get(&url)
            .header("Authorization", format!("Bearer {}", token))
            .send()
            .await
            .map_err(|e| PlatformError::NetworkError(e.to_string()))?;

        if !response.status().is_success() {
            return Ok(None);
        }

        let result: PagedList<BitbucketPR> = response.json().await.map_err(|e| {
            PlatformError::ParseError(format!("Failed to parse PR search response: {}", e))
        })?;

        if let Some(pr) = result.values.first() {
            return Ok(Some(PRCreateResult {
                number: pr.id,
                url: pr.links.html_link.href.clone(),
                state: PRState::Open,
            }));
        }

        Ok(None)
    }

    async fn is_pull_request_approved(&self, owner: &str, repo: &str, pull_number: u64) -> Result<bool, PlatformError> {
        let client = Self::http_client();
        let token = self.get_token().await?;

        let url = format!(
            "{}/pullrequests/{}/default-reviewers",
            self.api_base_url(owner, repo),
            pull_number
        );

        let response = client
            .get(&url)
            .header("Authorization", format!("Bearer {}", token))
            .send()
            .await
            .map_err(|e| PlatformError::NetworkError(e.to_string()))?;

        if !response.status().is_success() {
            return Ok(false);
        }

        #[derive(Deserialize)]
        struct Reviewer {
            approved: bool,
        }

        #[derive(Deserialize)]
        struct Reviewers {
            values: Vec<Reviewer>,
        }

        let reviewers: Reviewers = response.json().await.map_err(|e| {
            PlatformError::ParseError(format!("Failed to parse reviewers: {}", e))
        })?;

        Ok(reviewers.values.iter().all(|r| r.approved) && !reviewers.values.is_empty())
    }

    async fn get_pull_request_reviews(&self, _owner: &str, _repo: &str, _pull_number: u64) -> Result<Vec<PRReview>, PlatformError> {
        Ok(vec![])
    }

    async fn get_status_checks(&self, owner: &str, repo: &str, branch: &str) -> Result<StatusCheckResult, PlatformError> {
        let client = Self::http_client();
        let token = self.get_token().await?;

        let url = format!(
            "{}/commits/{}/statuses",
            self.api_base_url(owner, repo),
            urlencoding::encode(branch)
        );

        let response = client
            .get(&url)
            .header("Authorization", format!("Bearer {}", token))
            .send()
            .await
            .map_err(|e| PlatformError::NetworkError(e.to_string()))?;

        if !response.status().is_success() {
            return Ok(StatusCheckResult {
                state: CheckState::Pending,
                statuses: vec![],
            });
        }

        #[derive(Deserialize)]
        struct BuildStatus {
            key: String,
            state: String,
            url: Option<String>,
        }

        #[derive(Deserialize)]
        struct Statuses {
            values: Vec<BuildStatus>,
        }

        let statuses: Statuses = response.json().await.map_err(|e| {
            PlatformError::ParseError(format!("Failed to parse statuses: {}", e))
        })?;

        let checks: Vec<StatusCheck> = statuses
            .values
            .into_iter()
            .map(|s| {
                let state = match s.state.as_str() {
                    "SUCCESSFUL" => CheckState::Success,
                    "FAILED" | "STOPPED" => CheckState::Failure,
                    "INPROGRESS" => CheckState::Pending,
                    _ => CheckState::Pending,
                };

                StatusCheck {
                    name: s.key,
                    state,
                    url: s.url,
                }
            })
            .collect();

        let overall_state = if checks.is_empty() {
            CheckState::Pending
        } else if checks.iter().all(|c| matches!(c.state, CheckState::Success)) {
            CheckState::Success
        } else {
            CheckState::Failure
        };

        Ok(StatusCheckResult {
            state: overall_state,
            statuses: checks,
        })
    }

    async fn get_allowed_merge_methods(&self, _owner: &str, _repo: &str, _pull_number: u64) -> Result<AllowedMergeMethods, PlatformError> {
        Ok(AllowedMergeMethods {
            merge: true,
            squash: true,
            rebase: false,
        })
    }

    async fn get_pull_request_diff(&self, _owner: &str, _repo: &str, _pull_number: u64) -> Result<String, PlatformError> {
        Ok(String::new())
    }

    fn parse_repo_url(&self, url: &str) -> Option<ParsedRepoInfo> {
        let re = regex::Regex::new(r"(?:bitbucket\.org|bitbucket\.([^/]+))/([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)").ok()?;
        let caps = re.captures(url)?;

        let host = caps.get(1).map(|m| m.as_str()).unwrap_or("org");
        Some(ParsedRepoInfo {
            owner: caps.get(2)?.as_str().to_string(),
            repo: caps.get(3)?.as_str().to_string(),
            host: Some(format!("bitbucket.{}", host)),
        })
    }

    fn matches_url(&self, url: &str) -> bool {
        url.contains("bitbucket.org") || url.contains("bitbucket.")
    }

    fn generate_linked_pr_comment(&self, links: &[LinkedPRRef]) -> String {
        let links_str: Vec<String> = links.iter().map(|l| format!("{}#{}", l.repo_name, l.number)).collect();
        format!("Linked PRs: {}", links_str.join(", "))
    }

    fn parse_linked_pr_comment(&self, body: &str) -> Vec<LinkedPRRef> {
        let re = regex::Regex::new(r"([a-zA-Z0-9_-]+)#(\d+)").ok()?;
        re.captures_iter(body)
            .filter_map(|caps| Some(LinkedPRRef {
                repo_name: caps.get(1)?.as_str().to_string(),
                number: caps.get(2)?.as_str().parse().ok()?,
            }))
            .collect()
    }
}
