fn main() {
    // Note: Using CARGO_CFG_TARGET_OS because #[cfg()] attributes in build.rs
    // check the HOST platform, not the target platform
    let target_os = std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    if target_os == "windows" {
        // Link Windows system libraries required by libgit2-sys
        // These provide security (GetNamedSecurityInfoW) and registry
        // (RegOpenKeyExW, RegQueryValueExW, RegCloseKey) functions
        println!("cargo:rustc-link-lib=advapi32");

        // Increase default stack size from 1 MB to 8 MB on Windows.
        // The large clap Commands enum (~25 variants with nested subcommands)
        // causes a stack overflow during parsing in debug builds.
        // Linux/macOS default to 8 MB; this makes Windows match.
        let target_env = std::env::var("CARGO_CFG_TARGET_ENV").unwrap_or_default();
        if target_env == "msvc" {
            println!("cargo:rustc-link-arg=/STACK:8388608");
        } else {
            // MinGW / GNU toolchain
            println!("cargo:rustc-link-arg=-Wl,--stack-reserve=8388608");
        }
    }
}
