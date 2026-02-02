//! Rate limiting detection and handling for platform APIs

use crate::cli::output::Output;
use chrono::{DateTime, Utc};
use reqwest::header::HeaderMap;
use std::time::Duration;

/// Rate limit information parsed from API response headers
#[derive(Debug, Clone)]
pub struct RateLimitInfo {
    /// Remaining requests in current window
    pub remaining: Option<u32>,
    /// Reset time when the rate limit window resets
    pub reset_time: Option<DateTime<Utc>>,
    /// Limit of requests per window
    pub limit: Option<u32>,
}

impl RateLimitInfo {
    /// Check if rate limited (no remaining requests)
    pub fn is_rate_limited(&self) -> bool {
        match self.remaining {
            Some(0) => true,
            _ => false,
        }
    }

    /// Check if approaching rate limit (less than 10% remaining)
    pub fn is_approaching_limit(&self) -> bool {
        match (self.remaining, self.limit) {
            (Some(remaining), Some(limit)) => remaining < (limit / 10),
            _ => false,
        }
    }

    /// Get wait time until复位 (in seconds)
    pub fn wait_seconds(&self) -> Option<u64> {
        self.reset_time.map(|reset| {
            let now = Utc::now();
            let duration = reset.signed_duration_since(now);
            duration.num_seconds().max(1) as u64
        })
    }
}

/// Parse GitHub rate limit headers
pub fn parse_github_rate_limits(headers: &HeaderMap) -> RateLimitInfo {
    RateLimitInfo {
        limit: headers
            .get("x-ratelimit-limit")
            .and_then(|v| v.to_str().ok())
            .and_then(|s| s.parse().ok()),
        remaining: headers
            .get("x-ratelimit-remaining")
            .and_then(|v| v.to_str().ok())
            .and_then(|s| s.parse().ok()),
        reset_time: headers
            .get("x-ratelimit-reset")
            .and_then(|v| v.to_str().ok())
            .and_then(|s| s.parse().ok())
            .map(|ts: u64| DateTime::from_timestamp(ts as i64, 0).unwrap_or_default()),
    }
}

/// Parse GitLab rate limit headers
pub fn parse_gitlab_rate_limits(headers: &HeaderMap) -> RateLimitInfo {
    RateLimitInfo {
        limit: headers
            .get("ratelimit-limit")
            .and_then(|v| v.to_str().ok())
            .and_then(|s| s.parse().ok()),
        remaining: headers
            .get("ratelimit-remaining")
            .and_then(|v| v.to_str().ok())
            .and_then(|s| s.parse().ok()),
        reset_time: headers
            .get("ratelimit-reset")
            .and_then(|v| v.to_str().ok())
            .and_then(|s| s.parse().ok())
            .map(|ts: u64| DateTime::from_timestamp(ts as i64, 0).unwrap_or_default()),
    }
}

/// Parse Azure DevOps rate limit headers
pub fn parse_azure_rate_limits(headers: &HeaderMap) -> RateLimitInfo {
    RateLimitInfo {
        limit: headers
            .get("x-ratelimit-limit")
            .and_then(|v| v.to_str().ok())
            .and_then(|s| s.parse().ok()),
        remaining: headers
            .get("x-ratelimit-remaining")
            .and_then(|v| v.to_str().ok())
            .and_then(|s| s.parse().ok()),
        reset_time: headers
            .get("x-ratelimit-reset")
            .and_then(|v| v.to_str().ok())
            .and_then(|s| s.parse().ok())
            .map(|ts: u64| DateTime::from_timestamp(ts as i64, 0).unwrap_or_default()),
    }
}

/// Display rate limit warning if approaching limit
pub fn check_rate_limit_warning(info: &RateLimitInfo, platform_name: &str) {
    if info.is_rate_limited() {
        if let Some(wait_seconds) = info.wait_seconds() {
            let wait_str = if wait_seconds < 60 {
                format!("{} seconds", wait_seconds)
            } else {
                format!("{} minutes", wait_seconds / 60)
            };
            Output::warning(&format!(
                "{} API rate limit reached. Waiting {} for reset...",
                platform_name, wait_str
            ));
        }
    } else if info.is_approaching_limit() {
        if let Some(remaining) = info.remaining {
            if let Some(limit) = info.limit {
                Output::info(&format!(
                    "{} API rate limit: {} of {} remaining",
                    platform_name, remaining, limit
                ));
            }
        }
    }
}

/// Sleep for rate limit wait time
pub async fn wait_for_rate_limit(info: &RateLimitInfo) -> Option<Duration> {
    if let Some(wait_seconds) = info.wait_seconds() {
        let duration = Duration::from_secs(wait_seconds);
        tokio::time::sleep(duration).await;
        return Some(duration);
    }
    None
}
