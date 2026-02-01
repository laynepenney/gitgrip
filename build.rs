fn main() {
    // Link Windows system libraries required by libgit2-sys
    // These provide security (GetNamedSecurityInfoW) and registry
    // (RegOpenKeyExW, RegQueryValueExW, RegCloseKey) functions
    //
    // Note: Using CARGO_CFG_TARGET_OS because #[cfg()] attributes in build.rs
    // check the HOST platform, not the target platform
    let target_os = std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    if target_os == "windows" {
        println!("cargo:rustc-link-lib=advapi32");
    }
}
