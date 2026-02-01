fn main() {
    // Link Windows system libraries required by libgit2-sys
    // These provide security (GetNamedSecurityInfoW) and registry
    // (RegOpenKeyExW, RegQueryValueExW, RegCloseKey) functions
    #[cfg(target_os = "windows")]
    {
        println!("cargo:rustc-link-lib=advapi32");
    }
}
