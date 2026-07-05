use crate::credentials::resolve_credential;
use serde::Serialize;
use std::time::Duration;

#[derive(Debug, Serialize)]
#[serde(tag = "status")]
pub enum FetchOutcome {
    #[serde(rename = "ok")]
    Ok { code: u16, body: String },
    #[serde(rename = "error")]
    Error { message: String },
}

#[tauri::command]
pub async fn fetch_island(endpoint_base: String, credential_ref: String) -> FetchOutcome {
    let token = match resolve_credential(&credential_ref) {
        Ok(t) => t,
        Err(message) => return FetchOutcome::Error { message },
    };

    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
    {
        Ok(c) => c,
        Err(_) => {
            return FetchOutcome::Error {
                message: "failed to build http client".into(),
            }
        }
    };

    match client.get(&endpoint_base).bearer_auth(token).send().await {
        Ok(resp) => {
            let code = resp.status().as_u16();
            match resp.text().await {
                Ok(body) => FetchOutcome::Ok { code, body },
                Err(_) => FetchOutcome::Error {
                    message: "failed to read response body".into(),
                },
            }
        }
        Err(e) => {
            let message = if e.is_timeout() {
                "request timed out"
            } else if e.is_connect() {
                "could not connect to endpoint"
            } else {
                "request failed"
            };
            FetchOutcome::Error {
                message: message.into(),
            }
        }
    }
}
