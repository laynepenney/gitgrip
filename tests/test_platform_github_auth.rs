//! Isolated auth error test for the GitHub platform adapter.
//!
//! This test manipulates GITHUB_TOKEN env var, so it must run in its own
//! binary to avoid interfering with other tests that depend on the token.

use gitgrip::platform::traits::HostingPlatform;

#[tokio::test]
async fn test_github_auth_error_no_token() {
    // Guard that restores GITHUB_TOKEN on drop (including panic).
    struct TokenGuard;
    impl Drop for TokenGuard {
        fn drop(&mut self) {
            unsafe {
                std::env::set_var("GITHUB_TOKEN", "mock-test-token");
            }
        }
    }

    let server = wiremock::MockServer::start().await;
    let _guard = TokenGuard;

    // Clear all token env vars
    unsafe {
        std::env::remove_var("GITHUB_TOKEN");
        std::env::remove_var("GH_TOKEN");
    }

    let adapter = gitgrip::platform::github::GitHubAdapter::new(Some(&server.uri()));
    let result = adapter.get_pull_request("owner", "repo", 42).await;

    assert!(result.is_err(), "should fail without token");
    let err = result.unwrap_err();
    let err_str = err.to_string();
    assert!(
        err_str.contains("Authentication")
            || err_str.contains("token")
            || err_str.contains("auth"),
        "error should mention auth: {}",
        err_str
    );
    // TokenGuard::drop restores GITHUB_TOKEN
}
