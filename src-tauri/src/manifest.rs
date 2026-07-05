use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Island {
    pub id: String,
    pub title: String,
    pub endpoint_base: String,
    pub credential_ref: String,
    /// Optional custom frontend component to render for this island (e.g.
    /// "tickets"). When absent, the generic fetch-and-display panel is used.
    #[serde(default)]
    pub component: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Manifest {
    pub device_name: String,
    pub islands: Vec<Island>,
}

fn manifest_path() -> Result<PathBuf, String> {
    let home = dirs::home_dir().ok_or("could not resolve home directory")?;
    Ok(home.join(".ordinem").join("manifest.json"))
}

#[tauri::command]
pub fn load_manifest() -> Result<Manifest, String> {
    let path = manifest_path()?;
    let contents = std::fs::read_to_string(&path)
        .map_err(|e| format!("could not read manifest at {}: {}", path.display(), e))?;
    serde_json::from_str(&contents).map_err(|e| format!("manifest is not valid JSON: {}", e))
}
