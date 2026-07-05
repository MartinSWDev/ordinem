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

fn describe_error(e: &reqwest::Error) -> &'static str {
    if e.is_timeout() {
        "request timed out"
    } else if e.is_connect() {
        "could not connect to endpoint"
    } else {
        "request failed"
    }
}

/// General-purpose authenticated request, for custom islands that need more than
/// a single GET (list / sync / detail / process, etc). `credential_ref` may be
/// empty to skip auth (e.g. a local orchestrator with no token). `body` is an
/// optional JSON string sent for POST/PUT/PATCH.
#[tauri::command]
pub async fn api_request(
    method: String,
    url: String,
    credential_ref: Option<String>,
    body: Option<String>,
) -> FetchOutcome {
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(10))
        .build()
    {
        Ok(c) => c,
        Err(_) => {
            return FetchOutcome::Error {
                message: "failed to build http client".into(),
            }
        }
    };

    let verb = method.to_uppercase();
    let mut req = match verb.as_str() {
        "GET" => client.get(&url),
        "POST" => client.post(&url),
        "PUT" => client.put(&url),
        "PATCH" => client.patch(&url),
        "DELETE" => client.delete(&url),
        other => {
            return FetchOutcome::Error {
                message: format!("unsupported method: {other}"),
            }
        }
    };

    // Resolve + attach the credential only when a non-empty ref is given.
    if let Some(cref) = credential_ref.filter(|c| !c.is_empty()) {
        match resolve_credential(&cref) {
            Ok(token) => req = req.bearer_auth(token),
            Err(message) => return FetchOutcome::Error { message },
        }
    }

    if let Some(json) = body {
        req = req
            .header("content-type", "application/json")
            .body(json);
    }

    match req.send().await {
        Ok(resp) => {
            let code = resp.status().as_u16();
            match resp.text().await {
                Ok(body) => FetchOutcome::Ok { code, body },
                Err(_) => FetchOutcome::Error {
                    message: "failed to read response body".into(),
                },
            }
        }
        Err(e) => FetchOutcome::Error {
            message: describe_error(&e).into(),
        },
    }
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
        Err(e) => FetchOutcome::Error {
            message: describe_error(&e).into(),
        },
    }
}
