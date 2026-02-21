use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendStartConfig {
    pub host: Option<String>,
    pub port: Option<u16>,
    pub repo_root: Option<String>,
    pub force_restart: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendStatus {
    pub running: bool,
    pub port: u16,
    pub health: bool,
    pub app_name: Option<String>,
    pub host: String,
    pub base_url: String,
    pub last_error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionMeta {
    pub id: String,
    pub app_name: String,
    pub user_id: String,
    pub last_update_time: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionCreateInput {
    pub app_name: String,
    pub user_id: String,
    pub session_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionListInput {
    pub app_name: String,
    pub user_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StreamRunInput {
    pub request_id: String,
    pub app_name: String,
    pub user_id: String,
    pub session_id: String,
    pub text: String,
    pub invocation_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct KeysInput {
    pub google_api_key: Option<String>,
    pub brave_api_key: Option<String>,
    pub gemini_api_key: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct KeyPresence {
    pub google_api_key_set: bool,
    pub brave_api_key_set: bool,
    pub gemini_api_key_set: bool,
    pub google_api_key_masked: Option<String>,
    pub brave_api_key_masked: Option<String>,
    pub gemini_api_key_masked: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Ack {
    pub ok: bool,
    pub message: Option<String>,
}
