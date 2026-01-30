//! Criterion benchmarks for comparing with TypeScript version
//!
//! Run with: cargo bench
//! Results are saved in target/criterion/ for comparison

use criterion::{black_box, criterion_group, criterion_main, Criterion};
use gitgrip::core::manifest::{Manifest, RepoConfig};
use gitgrip::core::repo::RepoInfo;
use gitgrip::core::state::StateFile;
use std::path::PathBuf;

/// Benchmark manifest YAML parsing
fn bench_manifest_parse(c: &mut Criterion) {
    let yaml = r#"
version: 1
manifest:
  url: git@github.com:user/manifest.git
  default_branch: main
repos:
  app:
    url: git@github.com:user/app.git
    path: app
    default_branch: main
    copyfile:
      - src: README.md
        dest: APP_README.md
    linkfile:
      - src: config.yaml
        dest: app-config.yaml
  lib:
    url: git@github.com:user/lib.git
    path: lib
    default_branch: main
  api:
    url: git@github.com:user/api.git
    path: api
    default_branch: main
settings:
  pr_prefix: "[multi-repo]"
  merge_strategy: all-or-nothing
workspace:
  env:
    NODE_ENV: development
  scripts:
    build:
      description: Build all packages
      command: npm run build
    test:
      description: Run tests
      steps:
        - name: lint
          command: npm run lint
        - name: test
          command: npm test
"#;

    c.bench_function("manifest_parse", |b| {
        b.iter(|| Manifest::parse(black_box(yaml)).unwrap())
    });
}

/// Benchmark state JSON parsing
fn bench_state_parse(c: &mut Criterion) {
    let json = r#"{
        "currentManifestPr": 42,
        "branchToPr": {
            "feat/new-feature": 42,
            "feat/another": 43,
            "fix/bug": 44
        },
        "prLinks": {
            "42": [
                {
                    "repoName": "app",
                    "owner": "user",
                    "repo": "app",
                    "number": 123,
                    "url": "https://github.com/user/app/pull/123",
                    "state": "open",
                    "approved": true,
                    "checksPass": true,
                    "mergeable": true
                },
                {
                    "repoName": "lib",
                    "owner": "user",
                    "repo": "lib",
                    "number": 456,
                    "url": "https://github.com/user/lib/pull/456",
                    "state": "open",
                    "approved": false,
                    "checksPass": true,
                    "mergeable": true
                }
            ],
            "43": [],
            "44": []
        }
    }"#;

    c.bench_function("state_parse", |b| {
        b.iter(|| StateFile::parse(black_box(json)).unwrap())
    });
}

/// Benchmark git URL parsing
fn bench_url_parse(c: &mut Criterion) {
    let config = RepoConfig {
        url: "git@github.com:organization/repository-name.git".to_string(),
        path: "packages/repository-name".to_string(),
        default_branch: "main".to_string(),
        copyfile: None,
        linkfile: None,
        platform: None,
    };
    let workspace = PathBuf::from("/home/user/workspace");

    c.bench_function("url_parse_github_ssh", |b| {
        b.iter(|| RepoInfo::from_config("repo", black_box(&config), black_box(&workspace)))
    });
}

/// Benchmark Azure DevOps URL parsing
fn bench_url_parse_azure(c: &mut Criterion) {
    let config = RepoConfig {
        url: "https://dev.azure.com/organization/project/_git/repository".to_string(),
        path: "repository".to_string(),
        default_branch: "main".to_string(),
        copyfile: None,
        linkfile: None,
        platform: None,
    };
    let workspace = PathBuf::from("/home/user/workspace");

    c.bench_function("url_parse_azure_https", |b| {
        b.iter(|| RepoInfo::from_config("repo", black_box(&config), black_box(&workspace)))
    });
}

/// Benchmark manifest validation
fn bench_manifest_validate(c: &mut Criterion) {
    let yaml = r#"
version: 1
repos:
  app:
    url: git@github.com:user/app.git
    path: app
    copyfile:
      - src: file1.txt
        dest: dest1.txt
      - src: file2.txt
        dest: dest2.txt
    linkfile:
      - src: link1
        dest: dest/link1
workspace:
  scripts:
    build:
      steps:
        - name: step1
          command: echo 1
        - name: step2
          command: echo 2
        - name: step3
          command: echo 3
"#;

    // Parse once, then benchmark validation
    let manifest: Manifest = serde_yaml::from_str(yaml).unwrap();

    c.bench_function("manifest_validate", |b| {
        b.iter(|| black_box(&manifest).validate().unwrap())
    });
}

criterion_group!(
    benches,
    bench_manifest_parse,
    bench_state_parse,
    bench_url_parse,
    bench_url_parse_azure,
    bench_manifest_validate,
);

criterion_main!(benches);
