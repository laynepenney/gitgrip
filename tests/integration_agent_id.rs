//! Integration test: agent registry → spawn → SYNAPT_AGENT_ID pipeline.
//!
//! Verifies that gr spawn creates registry entries in team.db and
//! that the generated agent_id follows the name-NNN format.
//! The full end-to-end (Rust → Python channel) is covered by the
//! migration test in CI.

use std::fs;
use tempfile::TempDir;

// Re-export the registry functions we're testing
use gitgrip::core::agent_registry::{
    get_agent, get_agent_by_name, list_agents, register_agent, rename_agent,
};

/// Integration test: register a four-agent synthetic team,
/// verify all get unique stable IDs, then simulate a restart
/// (re-lookup) and confirm IDs are preserved.
#[test]
fn test_full_agent_lifecycle() {
    let tmp = TempDir::new().unwrap();
    let org_dir = tmp.path().join("example-team");
    fs::create_dir_all(&org_dir).unwrap();

    let org_id = "example-team";

    // Phase 1: Register 4 agents (simulates gr spawn up)
    let alpha_id = register_agent(&org_dir, org_id, "alpha", Some("team lead")).unwrap();
    let beta_id = register_agent(&org_dir, org_id, "beta", Some("implementation")).unwrap();
    let gamma_id = register_agent(&org_dir, org_id, "gamma", Some("design")).unwrap();
    let delta_id = register_agent(&org_dir, org_id, "delta", Some("architecture")).unwrap();

    // Verify format: name-NNN
    assert_eq!(alpha_id, "alpha-001");
    assert_eq!(beta_id, "beta-001");
    assert_eq!(gamma_id, "gamma-001");
    assert_eq!(delta_id, "delta-001");

    // Phase 2: Simulate restart — lookup by name (same as spawn up does)
    let alpha_lookup = get_agent_by_name(&org_dir, org_id, "alpha")
        .unwrap()
        .unwrap();
    assert_eq!(alpha_lookup.agent_id, "alpha-001");
    assert_eq!(alpha_lookup.role, Some("team lead".to_string()));

    // Phase 3: List all agents
    let all = list_agents(&org_dir, org_id).unwrap();
    assert_eq!(all.len(), 4);

    // Phase 4: Rename doesn't change ID
    rename_agent(&org_dir, "beta-001", "Beta Prime").unwrap();
    let renamed = get_agent(&org_dir, "beta-001").unwrap().unwrap();
    assert_eq!(renamed.agent_id, "beta-001"); // ID unchanged
    assert_eq!(renamed.display_name, "Beta Prime"); // Name updated

    // Phase 5: Duplicate registration fails
    let dup = register_agent(&org_dir, org_id, "alpha", None);
    assert!(dup.is_err(), "Duplicate display_name should be rejected");

    // Phase 6: IDs are unique
    let ids: Vec<String> = all.iter().map(|a| a.agent_id.clone()).collect();
    let unique: std::collections::HashSet<_> = ids.iter().collect();
    assert_eq!(ids.len(), unique.len(), "All IDs must be unique");
}

/// Integration test: cross-org isolation — same name in different orgs
/// gets separate IDs with no collision.
#[test]
fn test_cross_org_isolation() {
    let tmp = TempDir::new().unwrap();
    let org_a_dir = tmp.path().join("org-a");
    let org_b_dir = tmp.path().join("org-b");
    fs::create_dir_all(&org_a_dir).unwrap();
    fs::create_dir_all(&org_b_dir).unwrap();

    // Same display name, different orgs
    let org_a_casey = register_agent(&org_a_dir, "org-a", "Casey", Some("research")).unwrap();
    let org_b_casey = register_agent(&org_b_dir, "org-b", "Casey", Some("design")).unwrap();

    // Both succeed — no cross-org collision
    assert_eq!(org_a_casey, "casey-001");
    assert_eq!(org_b_casey, "casey-001");

    // Each org has only 1 agent
    assert_eq!(list_agents(&org_a_dir, "org-a").unwrap().len(), 1);
    assert_eq!(list_agents(&org_b_dir, "org-b").unwrap().len(), 1);

    // Roles are org-specific
    let a = get_agent(&org_a_dir, "casey-001").unwrap().unwrap();
    let b = get_agent(&org_b_dir, "casey-001").unwrap().unwrap();
    assert_eq!(a.role, Some("research".to_string()));
    assert_eq!(b.role, Some("design".to_string()));
}
