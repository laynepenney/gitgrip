//! Git status cache
//!
//! Caches git status calls to avoid redundant operations within a single command execution.

use once_cell::sync::Lazy;
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use super::status::RepoStatusInfo;

#[cfg(feature = "telemetry")]
use crate::telemetry::metrics::GLOBAL_METRICS;
#[cfg(feature = "telemetry")]
use tracing::trace;

/// Cache entry with status and timestamp
struct CacheEntry {
    status: RepoStatusInfo,
    timestamp: Instant,
}

/// Git status cache with TTL
pub struct GitStatusCache {
    cache: Mutex<HashMap<PathBuf, CacheEntry>>,
    ttl: Duration,
}

impl GitStatusCache {
    /// Create a new cache with the given TTL
    pub fn new(ttl: Duration) -> Self {
        Self {
            cache: Mutex::new(HashMap::new()),
            ttl,
        }
    }

    /// Check if an entry is expired
    fn is_expired(&self, entry: &CacheEntry) -> bool {
        entry.timestamp.elapsed() > self.ttl
    }

    /// Get cached status or None if not cached/expired
    pub fn get(&self, repo_path: &PathBuf) -> Option<RepoStatusInfo> {
        let cache = self.cache.lock().expect("mutex poisoned");
        if let Some(entry) = cache.get(repo_path) {
            if !self.is_expired(entry) {
                #[cfg(feature = "telemetry")]
                {
                    GLOBAL_METRICS.record_cache(true);
                    trace!(path = %repo_path.display(), "Cache hit");
                }
                return Some(entry.status.clone());
            }
        }
        #[cfg(feature = "telemetry")]
        {
            GLOBAL_METRICS.record_cache(false);
            trace!(path = %repo_path.display(), "Cache miss");
        }
        None
    }

    /// Set status in cache
    pub fn set(&self, repo_path: PathBuf, status: RepoStatusInfo) {
        let mut cache = self.cache.lock().expect("mutex poisoned");
        cache.insert(
            repo_path,
            CacheEntry {
                status,
                timestamp: Instant::now(),
            },
        );
    }

    /// Invalidate cache for a specific repo
    pub fn invalidate(&self, repo_path: &PathBuf) {
        let mut cache = self.cache.lock().expect("mutex poisoned");
        cache.remove(repo_path);
    }

    /// Clear the entire cache
    pub fn clear(&self) {
        let mut cache = self.cache.lock().expect("mutex poisoned");
        cache.clear();
    }
}

impl Default for GitStatusCache {
    fn default() -> Self {
        Self::new(Duration::from_millis(5000))
    }
}

/// Global singleton cache instance
pub static STATUS_CACHE: Lazy<GitStatusCache> = Lazy::new(GitStatusCache::default);

/// Invalidate cached status for a repository (call after git add, commit, etc.)
pub fn invalidate_status_cache(repo_path: &PathBuf) {
    STATUS_CACHE.invalidate(repo_path);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cache_set_get() {
        let cache = GitStatusCache::new(Duration::from_secs(60));
        let path = PathBuf::from("/test/repo");
        let status = RepoStatusInfo {
            current_branch: "main".to_string(),
            is_clean: true,
            staged: vec![],
            modified: vec![],
            untracked: vec![],
            ahead: 0,
            behind: 0,
        };

        cache.set(path.clone(), status.clone());
        let cached = cache.get(&path).unwrap();
        assert_eq!(cached.current_branch, "main");
        assert!(cached.is_clean);
    }

    #[test]
    fn test_cache_invalidate() {
        let cache = GitStatusCache::new(Duration::from_secs(60));
        let path = PathBuf::from("/test/repo");
        let status = RepoStatusInfo {
            current_branch: "main".to_string(),
            is_clean: true,
            staged: vec![],
            modified: vec![],
            untracked: vec![],
            ahead: 0,
            behind: 0,
        };

        cache.set(path.clone(), status);
        assert!(cache.get(&path).is_some());

        cache.invalidate(&path);
        assert!(cache.get(&path).is_none());
    }

    #[test]
    fn test_cache_expiry() {
        let cache = GitStatusCache::new(Duration::from_millis(10));
        let path = PathBuf::from("/test/repo");
        let status = RepoStatusInfo {
            current_branch: "main".to_string(),
            is_clean: true,
            staged: vec![],
            modified: vec![],
            untracked: vec![],
            ahead: 0,
            behind: 0,
        };

        cache.set(path.clone(), status);
        assert!(cache.get(&path).is_some());

        std::thread::sleep(Duration::from_millis(20));
        assert!(cache.get(&path).is_none());
    }
}
