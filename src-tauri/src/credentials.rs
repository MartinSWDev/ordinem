use keyring::Entry;

const SERVICE: &str = "ordinem";

/// Resolves a `credential_ref` to its secret via the OS keychain.
/// The returned value must never be logged or surfaced to the frontend directly.
pub fn resolve_credential(credential_ref: &str) -> Result<String, String> {
    let entry =
        Entry::new(SERVICE, credential_ref).map_err(|e| format!("could not access keychain: {}", e))?;
    entry
        .get_password()
        .map_err(|_| format!("no credential found for '{}'", credential_ref))
}
