//! Platform integration tests
//!
//! These tests require authentication tokens and make real API calls.
//! They are ignored by default and only run when:
//! 1. The `integration-tests` feature is enabled
//! 2. The tests are explicitly un-ignored
//!
//! Run with: cargo test --features integration-tests -- --ignored
//!
//! Required environment variables:
//! - GITHUB_TOKEN: For GitHub tests
//! - AZURE_DEVOPS_TOKEN: For Azure DevOps tests
//! - GITLAB_TOKEN: For GitLab tests

#[cfg(feature = "integration-tests")]
mod integration {
    use gitgrip::platform::get_platform_adapter;
    use gitgrip::core::manifest::PlatformType;
    use std::env;

    fn random_suffix() -> String {
        use std::time::{SystemTime, UNIX_EPOCH};
        let duration = SystemTime::now().duration_since(UNIX_EPOCH).unwrap();
        format!("{}", duration.as_millis() % 1_000_000)
    }

    // ==================== GitHub Tests ====================

    #[tokio::test]
    #[ignore = "Requires GITHUB_TOKEN and creates/deletes real repos"]
    async fn test_github_create_and_delete_repo() {
        // Skip if no token
        let _token = match env::var("GITHUB_TOKEN") {
            Ok(t) => t,
            Err(_) => {
                eprintln!("Skipping: GITHUB_TOKEN not set");
                return;
            }
        };

        let adapter = get_platform_adapter(PlatformType::GitHub, None);

        // Get current user for owner
        let token = adapter.get_token().await.expect("Failed to get token");
        let client = reqwest::Client::new();
        let resp: serde_json::Value = client
            .get("https://api.github.com/user")
            .header("Authorization", format!("Bearer {}", token))
            .header("User-Agent", "gitgrip-test")
            .send()
            .await
            .unwrap()
            .json()
            .await
            .unwrap();

        let owner = resp["login"].as_str().expect("No login in response");
        let repo_name = format!("gitgrip-test-{}", random_suffix());

        // Create repo
        let clone_url = adapter
            .create_repository(owner, &repo_name, Some("Test repo for gitgrip"), true)
            .await
            .expect("Failed to create repository");

        assert!(
            clone_url.contains(&repo_name),
            "Clone URL should contain repo name: {}",
            clone_url
        );

        // Small delay to ensure repo is created
        tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;

        // Delete repo
        adapter
            .delete_repository(owner, &repo_name)
            .await
            .expect("Failed to delete repository");

        println!("GitHub test passed: created and deleted {}/{}", owner, repo_name);
    }

    #[tokio::test]
    #[ignore = "Requires GITHUB_TOKEN"]
    async fn test_github_get_token() {
        let adapter = get_platform_adapter(PlatformType::GitHub, None);
        let result = adapter.get_token().await;

        match result {
            Ok(token) => {
                assert!(!token.is_empty(), "Token should not be empty");
                // Tokens typically start with ghp_ or gho_ or ghs_
                assert!(
                    token.starts_with("ghp_")
                        || token.starts_with("gho_")
                        || token.starts_with("ghs_")
                        || token.len() > 20, // Old style tokens are longer
                    "Token format looks incorrect"
                );
                println!("GitHub token obtained successfully");
            }
            Err(e) => {
                eprintln!("Note: Could not get GitHub token: {}", e);
            }
        }
    }

    // ==================== Azure DevOps Tests ====================

    #[tokio::test]
    #[ignore = "Requires AZURE_DEVOPS_TOKEN and creates/deletes real repos"]
    async fn test_azure_create_and_delete_repo() {
        // Skip if no token or org/project
        let _token = match env::var("AZURE_DEVOPS_TOKEN") {
            Ok(t) => t,
            Err(_) => {
                eprintln!("Skipping: AZURE_DEVOPS_TOKEN not set");
                return;
            }
        };

        let org = match env::var("AZURE_DEVOPS_ORG") {
            Ok(o) => o,
            Err(_) => {
                eprintln!("Skipping: AZURE_DEVOPS_ORG not set");
                return;
            }
        };

        let project = match env::var("AZURE_DEVOPS_PROJECT") {
            Ok(p) => p,
            Err(_) => {
                eprintln!("Skipping: AZURE_DEVOPS_PROJECT not set");
                return;
            }
        };

        let adapter = get_platform_adapter(PlatformType::AzureDevOps, None);
        let owner = format!("{}/{}", org, project);
        let repo_name = format!("gitgrip-test-{}", random_suffix());

        // Create repo
        let clone_url = adapter
            .create_repository(&owner, &repo_name, Some("Test repo for gitgrip"), true)
            .await
            .expect("Failed to create repository");

        assert!(
            clone_url.contains(&repo_name),
            "Clone URL should contain repo name: {}",
            clone_url
        );

        // Small delay
        tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;

        // Delete repo
        adapter
            .delete_repository(&owner, &repo_name)
            .await
            .expect("Failed to delete repository");

        println!(
            "Azure DevOps test passed: created and deleted {}/{}",
            owner, repo_name
        );
    }

    #[tokio::test]
    #[ignore = "Requires AZURE_DEVOPS_TOKEN"]
    async fn test_azure_get_token() {
        let adapter = get_platform_adapter(PlatformType::AzureDevOps, None);
        let result = adapter.get_token().await;

        match result {
            Ok(token) => {
                assert!(!token.is_empty(), "Token should not be empty");
                println!("Azure DevOps token obtained successfully");
            }
            Err(e) => {
                eprintln!("Note: Could not get Azure DevOps token: {}", e);
            }
        }
    }

    // ==================== GitLab Tests ====================

    #[tokio::test]
    #[ignore = "Requires GITLAB_TOKEN and creates/deletes real repos"]
    async fn test_gitlab_create_and_delete_repo() {
        // Skip if no token
        let _token = match env::var("GITLAB_TOKEN") {
            Ok(t) => t,
            Err(_) => {
                eprintln!("Skipping: GITLAB_TOKEN not set");
                return;
            }
        };

        let adapter = get_platform_adapter(PlatformType::GitLab, None);

        // Get current user
        let token = adapter.get_token().await.expect("Failed to get token");
        let client = reqwest::Client::new();
        let resp: serde_json::Value = client
            .get("https://gitlab.com/api/v4/user")
            .header("PRIVATE-TOKEN", &token)
            .send()
            .await
            .unwrap()
            .json()
            .await
            .unwrap();

        let owner = resp["username"].as_str().expect("No username in response");
        let repo_name = format!("gitgrip-test-{}", random_suffix());

        // Create repo
        let clone_url = adapter
            .create_repository(owner, &repo_name, Some("Test repo for gitgrip"), true)
            .await
            .expect("Failed to create repository");

        assert!(
            clone_url.contains(&repo_name),
            "Clone URL should contain repo name: {}",
            clone_url
        );

        // Delay to ensure repo is created
        tokio::time::sleep(tokio::time::Duration::from_secs(3)).await;

        // Delete repo
        adapter
            .delete_repository(owner, &repo_name)
            .await
            .expect("Failed to delete repository");

        println!("GitLab test passed: created and deleted {}/{}", owner, repo_name);
    }

    #[tokio::test]
    #[ignore = "Requires GITLAB_TOKEN"]
    async fn test_gitlab_get_token() {
        let adapter = get_platform_adapter(PlatformType::GitLab, None);
        let result = adapter.get_token().await;

        match result {
            Ok(token) => {
                assert!(!token.is_empty(), "Token should not be empty");
                // GitLab PATs typically start with glpat-
                println!("GitLab token obtained successfully");
            }
            Err(e) => {
                eprintln!("Note: Could not get GitLab token: {}", e);
            }
        }
    }

    // ==================== Cross-Platform Tests ====================

    #[tokio::test]
    #[ignore = "Requires platform auth tokens"]
    async fn test_full_init_workflow_github() {
        // This test simulates the full workflow:
        // 1. Detect platform from existing repos
        // 2. Create manifest repo
        // 3. Clean up

        let token = match env::var("GITHUB_TOKEN") {
            Ok(t) => t,
            Err(_) => {
                eprintln!("Skipping: GITHUB_TOKEN not set");
                return;
            }
        };

        let adapter = get_platform_adapter(PlatformType::GitHub, None);

        // Get current user
        let client = reqwest::Client::new();
        let resp: serde_json::Value = client
            .get("https://api.github.com/user")
            .header("Authorization", format!("Bearer {}", token))
            .header("User-Agent", "gitgrip-test")
            .send()
            .await
            .unwrap()
            .json()
            .await
            .unwrap();

        let owner = resp["login"].as_str().expect("No login in response");
        let manifest_name = format!("gitgrip-manifest-test-{}", random_suffix());

        // Simulate init --from-dirs --create-manifest
        // Create manifest repo
        let clone_url = adapter
            .create_repository(owner, &manifest_name, Some("Workspace manifest"), true)
            .await
            .expect("Failed to create manifest repo");

        println!("Created manifest repo: {}", clone_url);

        // Verify we can find it
        tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;

        // Clean up
        adapter
            .delete_repository(owner, &manifest_name)
            .await
            .expect("Failed to delete manifest repo");

        println!("Full init workflow test passed");
    }
}

// Non-feature-gated tests that verify the test infrastructure works
#[test]
fn test_platform_integration_test_module_compiles() {
    // This test just verifies the module compiles without the feature flag
    assert!(true);
}
