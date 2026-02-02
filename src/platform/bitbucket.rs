//! Bitbucket platform adapter (initial stub implementation)

use async_trait::async_trait;

use super::traits::{HostingPlatform, LinkedPRRef, PlatformError};
use super::types::*;
use crate::core::manifest::PlatformType;

/// Bitbucket API adapter
pub struct BitbucketAdapter {
    base_url: String,
}

impl BitbucketAdapter {
    pub fn new(base_url: Option<&str>) -> Self {
        Self {
            base_url: base_url
                .unwrap_or("https://api.bitbucket.org/2.0")
                .to_string(),
        }
    }
}

#[async_trait]
impl HostingPlatform for BitbucketAdapter {
    fn platform_type(&self) -> PlatformType {
        PlatformType::Bitbucket
    }

    async fn get_token(&self) -> Result<String, PlatformError> {
        std::env::var("BITBUCKET_TOKEN")
            .map_err(|_| PlatformError::AuthError("BITBUCKET_TOKEN not set".to_string()))
    }

    async fn create_pull_request(
        &self,
        _owner: &str,
        _repo: &str,
        _head: &str,
        _base: &str,
        _title: &str,
        _body: Option<&str>,
        _draft: bool,
    ) -> Result<PRCreateResult, PlatformError> {
        Err(PlatformError::ApiError(
            "Bitbucket PR create not yet implemented".to_string(),
        ))
    }

    async fn get_pull_request(
        &self,
        _owner: &str,
        _repo: &str,
        _pull_number: u64,
    ) -> Result<PullRequest, PlatformError> {
        Err(PlatformError::ApiError(
            "Bitbucket PR get not yet implemented".to_string(),
        ))
    }

    async fn update_pull_request_body(
        &self,
        _owner: &str,
        _repo: &str,
        _pull_number: u64,
        _body: &str,
    ) -> Result<(), PlatformError> {
        Err(PlatformError::ApiError(
            "Bitbucket PR update not yet implemented".to_string(),
        ))
    }

    async fn merge_pull_request(
        &self,
        _owner: &str,
        _repo: &str,
        _pull_number: u64,
        _method: Option<MergeMethod>,
        _delete_branch: bool,
    ) -> Result<bool, PlatformError> {
        Err(PlatformError::ApiError(
            "Bitbucket merge not yet implemented".to_string(),
        ))
    }

    async fn find_pr_by_branch(
        &self,
        _owner: &str,
        _repo: &str,
        _branch: &str,
    ) -> Result<Option<PRCreateResult>, PlatformError> {
        Ok(None)
    }

    async fn is_pull_request_approved(
        &self,
        _owner: &str,
        _repo: &str,
        _pull_number: u64,
    ) -> Result<bool, PlatformError> {
        Ok(true)
    }

    async fn get_pull_request_reviews(
        &self,
        _owner: &str,
        _repo: &str,
        _pull_number: u64,
    ) -> Result<Vec<PRReview>, PlatformError> {
        Ok(vec![])
    }

    async fn get_status_checks(
        &self,
        _owner: &str,
        _repo: &str,
        _branch: &str,
    ) -> Result<StatusCheckResult, PlatformError> {
        Ok(StatusCheckResult {
            state: CheckState::Pending,
            statuses: vec![],
        })
    }

    async fn get_allowed_merge_methods(
        &self,
        _owner: &str,
        _repo: &str,
    ) -> Result<AllowedMergeMethods, PlatformError> {
        Ok(AllowedMergeMethods {
            merge: true,
            squash: true,
            rebase: true,
        })
    }

    async fn get_pull_request_diff(
        &self,
        _owner: &str,
        _repo: &str,
        _pull_number: u64,
    ) -> Result<String, PlatformError> {
        Ok(String::new())
    }

    fn parse_repo_url(&self, _url: &str) -> Option<ParsedRepoInfo> {
        None // TODO: implement
    }

    fn matches_url(&self, url: &str) -> bool {
        url.contains("bitbucket.org") || url.contains("bitbucket.")
    }

    fn generate_linked_pr_comment(&self, links: &[LinkedPRRef]) -> String {
        let links_str: Vec<String> = links
            .iter()
            .map(|l| format!("{}#{}", l.repo_name, l.number))
            .collect();
        format!("Linked PRs: {}", links_str.join(", "))
    }

    fn parse_linked_pr_comment(&self, _body: &str) -> Vec<LinkedPRRef> {
        vec![]
    }
}
