mod credentials;
mod fetch;
mod manifest;

use fetch::{api_request, fetch_island};
use manifest::load_manifest;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            load_manifest,
            fetch_island,
            api_request
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
