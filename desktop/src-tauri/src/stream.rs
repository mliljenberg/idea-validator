use std::time::Duration;

use futures_util::StreamExt;
use reqwest::{Client, StatusCode};
use serde::Serialize;
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter};
use tokio_util::sync::CancellationToken;

use crate::backend::{run_fallback_url, run_sse_url};
use crate::session_store::ReplayMessage;
use crate::types::StreamRunInput;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct StreamOpen {
    kind: &'static str,
    request_id: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct StreamMessage {
    kind: &'static str,
    request_id: String,
    text: String,
    source: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct StreamRaw {
    kind: &'static str,
    request_id: String,
    event: Value,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct StreamError {
    kind: &'static str,
    request_id: String,
    message: String,
    retryable: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct StreamDone {
    kind: &'static str,
    request_id: String,
    usage: Option<Value>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct StreamMeta {
    kind: &'static str,
    request_id: String,
    invocation_id: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct StreamProgress {
    kind: &'static str,
    request_id: String,
    percent: u8,
    stage: String,
    tools_completed: usize,
    tools_total: usize,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct StreamTool {
    kind: &'static str,
    request_id: String,
    phase: &'static str,
    name: String,
    query: Option<String>,
    detail: Option<String>,
}

#[derive(Debug, Clone)]
struct ToolSignal {
    phase: &'static str,
    name: String,
    query: Option<String>,
    detail: Option<String>,
}

#[derive(Debug, Default)]
struct StreamState {
    last_model_text: String,
    saw_model_text: bool,
    saw_error: bool,
    tools_started: usize,
    tools_completed: usize,
    last_progress_percent: Option<u8>,
    last_progress_stage: Option<String>,
    last_invocation_id: Option<String>,
}

#[derive(Debug, Clone)]
struct SseFailure {
    status: Option<u16>,
    message: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StreamOutcome {
    Completed,
    Failed,
}

pub async fn run_stream_task(
    app: AppHandle,
    base_url: String,
    input: StreamRunInput,
    replay_messages: Vec<ReplayMessage>,
    cancel: CancellationToken,
) -> Result<StreamOutcome, String> {
    ensure_adk_session(&base_url, &input).await?;

    emit(
        &app,
        &input.request_id,
        StreamOpen {
            kind: "stream_open",
            request_id: input.request_id.clone(),
        },
    )?;
    emit(
        &app,
        &input.request_id,
        StreamProgress {
            kind: "stream_progress",
            request_id: input.request_id.clone(),
            percent: 5,
            stage: "Rehydrating context".to_string(),
            tools_completed: 0,
            tools_total: 0,
        },
    )?;

    if !replay_messages.is_empty() {
        if let Err(err) = replay_history(&base_url, &input, &replay_messages, &cancel).await {
            emit(
                &app,
                &input.request_id,
                StreamTool {
                    kind: "stream_tool",
                    request_id: input.request_id.clone(),
                    phase: "info",
                    name: "context_replay".to_string(),
                    query: None,
                    detail: Some(format!("Replay degraded: {}", truncate(&err, 240))),
                },
            )?;
        }
    }

    match run_sse_stream(&app, &base_url, &input, cancel).await {
        Ok(outcome) => Ok(outcome),
        Err(failure) => {
            // Fall back to /run only when /run_sse is clearly unsupported by this backend.
            let fallback_allowed = matches!(failure.status, Some(404 | 405 | 501));
            if fallback_allowed {
                run_non_streaming_fallback(app, &base_url, &input, failure.status).await
            } else {
                emit(
                    &app,
                    &input.request_id,
                    StreamError {
                        kind: "stream_error",
                        request_id: input.request_id.clone(),
                        message: format!("SSE stream failed: {}", failure.message),
                        retryable: true,
                    },
                )?;
                emit(
                    &app,
                    &input.request_id,
                    StreamDone {
                        kind: "stream_done",
                        request_id: input.request_id.clone(),
                        usage: None,
                    },
                )?;
                Ok(StreamOutcome::Failed)
            }
        }
    }
}

async fn run_sse_stream(
    app: &AppHandle,
    base_url: &str,
    input: &StreamRunInput,
    cancel: CancellationToken,
) -> Result<StreamOutcome, SseFailure> {
    let response = send_run_sse_request(base_url, input).await?;
    let status = response.status();
    if !status.is_success() {
        let body = response.text().await.unwrap_or_default();
        return Err(SseFailure {
            status: Some(status.as_u16()),
            message: format!(
                "/run_sse returned {}{}",
                status,
                if body.trim().is_empty() {
                    "".to_string()
                } else {
                    format!(" | backend: {}", truncate(body.trim(), 800))
                }
            ),
        });
    }

    let mut usage = None;
    let mut state = StreamState::default();
    emit_progress_if_changed(app, &input.request_id, &mut state, false).map_err(|e| {
        SseFailure {
            status: None,
            message: e,
        }
    })?;

    let mut stream = response.bytes_stream();
    let mut line_buffer = String::new();
    let mut data_lines: Vec<String> = Vec::new();
    let mut done = false;
    let mut cancelled = false;

    while !done {
        let next = tokio::select! {
            _ = cancel.cancelled() => {
                cancelled = true;
                break;
            }
            chunk = stream.next() => chunk,
        };

        match next {
            None => break,
            Some(Err(err)) => {
                return Err(SseFailure {
                    status: None,
                    message: format!("error reading SSE stream: {err}"),
                });
            }
            Some(Ok(chunk)) => {
                line_buffer.push_str(&String::from_utf8_lossy(&chunk));

                while let Some(newline_idx) = line_buffer.find('\n') {
                    let mut line = line_buffer[..newline_idx].to_string();
                    line_buffer = line_buffer[newline_idx + 1..].to_string();
                    if line.ends_with('\r') {
                        line.pop();
                    }

                    if line.is_empty() {
                        done = consume_sse_event(
                            app,
                            &input.request_id,
                            &mut state,
                            &mut usage,
                            &mut data_lines,
                        )
                        .map_err(|e| SseFailure {
                            status: None,
                            message: e,
                        })?;
                        continue;
                    }

                    if let Some(data) = line.strip_prefix("data:") {
                        data_lines.push(data.trim_start().to_string());
                    }
                }
            }
        }
    }

    if !done {
        if !line_buffer.trim().is_empty() {
            if let Some(data) = line_buffer.trim().strip_prefix("data:") {
                data_lines.push(data.trim_start().to_string());
            }
        }
        done = consume_sse_event(
            app,
            &input.request_id,
            &mut state,
            &mut usage,
            &mut data_lines,
        )
        .map_err(|e| SseFailure {
            status: None,
            message: e,
        })?;
        let _ = done;
    }

    if cancelled {
        emit(
            app,
            &input.request_id,
            StreamError {
                kind: "stream_error",
                request_id: input.request_id.clone(),
                message: "Run cancelled.".to_string(),
                retryable: false,
            },
        )
        .map_err(|e| SseFailure {
            status: None,
            message: e,
        })?;
    }

    emit(
        app,
        &input.request_id,
        StreamDone {
            kind: "stream_done",
            request_id: input.request_id.clone(),
            usage,
        },
    )
    .map_err(|e| SseFailure {
        status: None,
        message: e,
    })?;
    emit_progress_if_changed(app, &input.request_id, &mut state, true).map_err(|e| SseFailure {
        status: None,
        message: e,
    })?;

    if cancelled || state.saw_error {
        Ok(StreamOutcome::Failed)
    } else {
        Ok(StreamOutcome::Completed)
    }
}

fn consume_sse_event(
    app: &AppHandle,
    request_id: &str,
    state: &mut StreamState,
    usage: &mut Option<Value>,
    data_lines: &mut Vec<String>,
) -> Result<bool, String> {
    if data_lines.is_empty() {
        return Ok(false);
    }

    let payload = data_lines.join("\n");
    data_lines.clear();
    let trimmed = payload.trim();
    if trimmed.is_empty() {
        return Ok(false);
    }
    if trimmed == "[DONE]" {
        return Ok(true);
    }

    let parsed = match serde_json::from_str::<Value>(trimmed) {
        Ok(value) => value,
        Err(_) => return Ok(false),
    };

    let events = extract_run_events(&parsed).unwrap_or_else(|| vec![parsed]);
    for event in events {
        process_event(app, request_id, &event, state, usage)?;
    }

    Ok(false)
}

async fn run_non_streaming_fallback(
    app: AppHandle,
    base_url: &str,
    input: &StreamRunInput,
    sse_status: Option<u16>,
) -> Result<StreamOutcome, String> {
    let (status, response_text) = send_run_request(base_url, input).await?;

    if !status.is_success() {
        let body_excerpt = truncate(response_text.trim(), 800);
        emit(
            &app,
            &input.request_id,
            StreamError {
                kind: "stream_error",
                request_id: input.request_id.clone(),
                message: format!(
                    "Streaming failed{} and fallback /run returned {}{}",
                    sse_status
                        .map(|s| format!(" with HTTP {s}"))
                        .unwrap_or_else(|| "".to_string()),
                    status,
                    if body_excerpt.is_empty() {
                        "".to_string()
                    } else {
                        format!(" | backend: {body_excerpt}")
                    }
                ),
                retryable: true,
            },
        )?;
        emit(
            &app,
            &input.request_id,
            StreamDone {
                kind: "stream_done",
                request_id: input.request_id.clone(),
                usage: None,
            },
        )?;
        return Ok(StreamOutcome::Failed);
    }

    let payload = serde_json::from_str::<Value>(&response_text).map_err(|e| {
        format!(
            "Failed to parse fallback /run response: {e}. Body: {}",
            truncate(&response_text, 500)
        )
    })?;
    let events = extract_run_events(&payload).ok_or_else(|| {
        format!(
            "Unexpected /run response shape: {}",
            summarize_json_shape(&payload)
        )
    })?;

    let mut usage = None;
    let mut state = StreamState::default();
    emit_progress_if_changed(&app, &input.request_id, &mut state, false)?;
    for event in events {
        process_event(&app, &input.request_id, &event, &mut state, &mut usage)?;
    }

    emit(
        &app,
        &input.request_id,
        StreamDone {
            kind: "stream_done",
            request_id: input.request_id.clone(),
            usage,
        },
    )?;
    emit_progress_if_changed(&app, &input.request_id, &mut state, true)?;

    if state.saw_error {
        Ok(StreamOutcome::Failed)
    } else {
        Ok(StreamOutcome::Completed)
    }
}

async fn send_run_request(
    base_url: &str,
    input: &StreamRunInput,
) -> Result<(StatusCode, String), String> {
    let fallback_body = json!({
        "app_name": input.app_name,
        "user_id": input.user_id,
        "session_id": input.session_id,
        "streaming": false,
        "new_message": {
            "role": "user",
            "parts": [{"text": input.text}]
        }
    });

    let response = http_client_long()
        .post(run_fallback_url(base_url))
        .json(&fallback_body)
        .send()
        .await
        .map_err(|e| format!("Fallback /run failed: {e}"))?;

    let status = response.status();
    let response_text = response
        .text()
        .await
        .map_err(|e| format!("Failed to read /run response body: {e}"))?;

    Ok((status, response_text))
}

async fn ensure_adk_session(base_url: &str, input: &StreamRunInput) -> Result<(), String> {
    let url = format!(
        "{}/apps/{}/users/{}/sessions",
        base_url, input.app_name, input.user_id
    );
    let body = json!({ "sessionId": input.session_id });

    let response = http_client()
        .post(url)
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("Failed to create ADK execution session: {e}"))?;

    if response.status().is_success() {
        return Ok(());
    }

    let status = response.status();
    let body_text = response.text().await.unwrap_or_default();
    Err(format!(
        "Failed to create ADK execution session (HTTP {status}){}",
        if body_text.trim().is_empty() {
            "".to_string()
        } else {
            format!(" | backend: {}", truncate(body_text.trim(), 500))
        }
    ))
}

async fn replay_history(
    base_url: &str,
    input: &StreamRunInput,
    replay_messages: &[ReplayMessage],
    cancel: &CancellationToken,
) -> Result<(), String> {
    for (index, message) in replay_messages.iter().enumerate() {
        if cancel.is_cancelled() {
            return Err("Replay cancelled.".to_string());
        }

        let replay_text = replay_text(message);
        let body = json!({
            "app_name": input.app_name,
            "user_id": input.user_id,
            "session_id": input.session_id,
            "streaming": false,
            "new_message": {
                "role": "user",
                "parts": [{ "text": replay_text }]
            }
        });

        let response = http_client_long()
            .post(run_fallback_url(base_url))
            .json(&body)
            .send()
            .await
            .map_err(|e| {
                format!(
                    "Failed replay request {} of {}: {e}",
                    index + 1,
                    replay_messages.len()
                )
            })?;

        if !response.status().is_success() {
            let status = response.status();
            let body_text = response.text().await.unwrap_or_default();
            return Err(format!(
                "Replay request {} of {} returned {}{}",
                index + 1,
                replay_messages.len(),
                status,
                if body_text.trim().is_empty() {
                    "".to_string()
                } else {
                    format!(" | backend: {}", truncate(body_text.trim(), 500))
                }
            ));
        }
    }

    Ok(())
}

fn replay_text(message: &ReplayMessage) -> String {
    let role = message.role.trim().to_ascii_lowercase();
    if role == "user" {
        return message.text.clone();
    }

    if role == "assistant" || role == "model" {
        return format!("Previous assistant response:\n{}", message.text);
    }

    format!("Previous context:\n{}", message.text)
}

async fn send_run_sse_request(
    base_url: &str,
    input: &StreamRunInput,
) -> Result<reqwest::Response, SseFailure> {
    let body = json!({
        "app_name": input.app_name,
        "user_id": input.user_id,
        "session_id": input.session_id,
        "streaming": true,
        "new_message": {
            "role": "user",
            "parts": [{"text": input.text}]
        }
    });

    http_client_stream()
        .post(run_sse_url(base_url))
        .header("Accept", "text/event-stream")
        .json(&body)
        .send()
        .await
        .map_err(|e| SseFailure {
            status: None,
            message: format!("error sending request to /run_sse: {e}"),
        })
}

fn http_client_long() -> Client {
    Client::builder()
        .timeout(std::time::Duration::from_secs(600))
        .build()
        .expect("reqwest client should build")
}

fn http_client() -> Client {
    Client::builder()
        .timeout(std::time::Duration::from_secs(120))
        .build()
        .expect("reqwest client should build")
}

fn http_client_stream() -> Client {
    Client::builder()
        .connect_timeout(Duration::from_secs(15))
        .timeout(Duration::from_secs(1800))
        .build()
        .expect("reqwest client should build")
}

fn process_event(
    app: &AppHandle,
    request_id: &str,
    event: &Value,
    state: &mut StreamState,
    usage: &mut Option<Value>,
) -> Result<(), String> {
    if let Some(invocation_id) = extract_invocation_id(event) {
        if state.last_invocation_id.as_deref() != Some(invocation_id.as_str()) {
            state.last_invocation_id = Some(invocation_id.clone());
            emit(
                app,
                request_id,
                StreamMeta {
                    kind: "stream_meta",
                    request_id: request_id.to_string(),
                    invocation_id,
                },
            )?;
        }
    }

    emit(
        app,
        request_id,
        StreamRaw {
            kind: "stream_event_raw",
            request_id: request_id.to_string(),
            event: event.clone(),
        },
    )?;

    if let Some(message) = extract_error_message(event) {
        state.saw_error = true;
        emit(
            app,
            request_id,
            StreamError {
                kind: "stream_error",
                request_id: request_id.to_string(),
                message,
                retryable: true,
            },
        )?;
    }

    for tool in extract_tool_signals(event) {
        if tool.phase == "start" {
            state.tools_started += 1;
        } else if tool.phase == "done" {
            state.tools_completed += 1;
            if state.tools_completed > state.tools_started {
                state.tools_started = state.tools_completed;
            }
        }

        emit(
            app,
            request_id,
            StreamTool {
                kind: "stream_tool",
                request_id: request_id.to_string(),
                phase: tool.phase,
                name: tool.name,
                query: tool.query,
                detail: tool.detail,
            },
        )?;
    }

    if let Some(full_text) = extract_model_text(event) {
        let normalized = full_text.trim().to_string();
        if !normalized.is_empty() && normalized != state.last_model_text {
            emit(
                app,
                request_id,
                StreamMessage {
                    kind: "stream_message",
                    request_id: request_id.to_string(),
                    text: normalized.clone(),
                    source: extract_event_source(event),
                },
            )?;
            state.saw_model_text = true;
            state.last_model_text = normalized;
        }
    }

    if let Some(u) = event.get("usageMetadata") {
        *usage = Some(u.clone());
    }

    emit_progress_if_changed(app, request_id, state, false)
}

fn extract_event_source(event: &Value) -> Option<String> {
    event
        .get("author")
        .and_then(Value::as_str)
        .or_else(|| event.get("source").and_then(Value::as_str))
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string())
}

fn extract_invocation_id(event: &Value) -> Option<String> {
    event
        .get("invocationId")
        .and_then(Value::as_str)
        .or_else(|| event.get("invocation_id").and_then(Value::as_str))
        .or_else(|| {
            event
                .get("metadata")
                .and_then(Value::as_object)
                .and_then(|m| m.get("invocationId"))
                .and_then(Value::as_str)
        })
        .or_else(|| {
            event
                .get("metadata")
                .and_then(Value::as_object)
                .and_then(|m| m.get("invocation_id"))
                .and_then(Value::as_str)
        })
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string())
}

fn extract_run_events(payload: &Value) -> Option<Vec<Value>> {
    if let Some(arr) = payload.as_array() {
        return Some(arr.to_vec());
    }

    let object = payload.as_object()?;
    for key in ["events", "response", "result", "items"] {
        if let Some(arr) = object.get(key).and_then(Value::as_array) {
            return Some(arr.to_vec());
        }
    }

    None
}

fn summarize_json_shape(value: &Value) -> String {
    match value {
        Value::Array(arr) => format!("array(len={})", arr.len()),
        Value::Object(obj) => {
            let keys = obj.keys().take(10).cloned().collect::<Vec<_>>().join(", ");
            format!("object(keys=[{}])", keys)
        }
        Value::String(_) => "string".to_string(),
        Value::Number(_) => "number".to_string(),
        Value::Bool(_) => "bool".to_string(),
        Value::Null => "null".to_string(),
    }
}

fn extract_model_text(event: &Value) -> Option<String> {
    let content = event.get("content")?;
    let role = content.get("role").and_then(Value::as_str);
    let author = event.get("author").and_then(Value::as_str);
    let is_model = matches!(role, Some("model") | Some("assistant"))
        || role.is_none() && matches!(author, Some("model") | Some("assistant"));
    if !is_model {
        return None;
    }

    let parts = content.get("parts")?.as_array()?;
    let mut out = String::new();
    for part in parts {
        if let Some(text) = part.get("text").and_then(Value::as_str) {
            out.push_str(text);
        }
    }

    if out.is_empty() {
        None
    } else {
        Some(out)
    }
}

fn extract_error_message(event: &Value) -> Option<String> {
    if let Some(message) = event.get("error").and_then(Value::as_str) {
        return Some(message.to_string());
    }

    if let Some(message) = event
        .get("error")
        .and_then(Value::as_object)
        .and_then(|obj| obj.get("message"))
        .and_then(Value::as_str)
    {
        return Some(message.to_string());
    }

    None
}

fn extract_tool_signals(event: &Value) -> Vec<ToolSignal> {
    let mut out = Vec::new();
    let parts = event
        .get("content")
        .and_then(|content| content.get("parts"))
        .and_then(Value::as_array);
    let Some(parts) = parts else {
        return out;
    };

    for part in parts {
        if let Some(function_call) = part
            .get("functionCall")
            .or_else(|| part.get("function_call"))
        {
            let name = function_call
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or("tool")
                .to_string();
            let args = function_call
                .get("args")
                .or_else(|| function_call.get("arguments"));
            let query = args.and_then(extract_search_query);
            let detail = args.and_then(summarize_args);
            out.push(ToolSignal {
                phase: "start",
                name,
                query,
                detail,
            });
        }

        if let Some(function_response) = part
            .get("functionResponse")
            .or_else(|| part.get("function_response"))
        {
            let name = function_response
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or("tool")
                .to_string();
            let detail = function_response
                .get("response")
                .and_then(summarize_response_shape);
            out.push(ToolSignal {
                phase: "done",
                name,
                query: None,
                detail,
            });
        }
    }

    out
}

fn extract_search_query(args: &Value) -> Option<String> {
    let mut queries = Vec::new();
    collect_queries(args, &mut queries, 0);
    if queries.is_empty() {
        None
    } else {
        let joined = queries.into_iter().take(2).collect::<Vec<_>>().join(" | ");
        Some(truncate(&joined, 180))
    }
}

fn collect_queries(value: &Value, out: &mut Vec<String>, depth: usize) {
    if depth > 5 || out.len() >= 4 {
        return;
    }

    match value {
        Value::Object(map) => {
            for (k, v) in map {
                let lower = k.to_lowercase();
                let looks_like_query = lower == "q"
                    || lower == "query"
                    || lower == "queries"
                    || lower.contains("query");
                if looks_like_query {
                    match v {
                        Value::String(s) if !s.trim().is_empty() => out.push(s.trim().to_string()),
                        Value::Array(arr) => {
                            for item in arr {
                                if let Some(s) = item.as_str() {
                                    let trimmed = s.trim();
                                    if !trimmed.is_empty() {
                                        out.push(trimmed.to_string());
                                    }
                                } else if let Some(obj) = item.as_object() {
                                    if let Some(q) = obj.get("q").and_then(Value::as_str) {
                                        let trimmed = q.trim();
                                        if !trimmed.is_empty() {
                                            out.push(trimmed.to_string());
                                        }
                                    }
                                }
                            }
                        }
                        _ => {}
                    }
                } else {
                    collect_queries(v, out, depth + 1);
                }
            }
        }
        Value::Array(arr) => {
            for item in arr {
                collect_queries(item, out, depth + 1);
            }
        }
        _ => {}
    }
}

fn summarize_args(args: &Value) -> Option<String> {
    if let Some(query) = extract_search_query(args) {
        return Some(format!("query: {query}"));
    }

    if let Some(obj) = args.as_object() {
        let keys = obj.keys().take(4).cloned().collect::<Vec<_>>().join(", ");
        if keys.is_empty() {
            None
        } else {
            Some(format!("args: {keys}"))
        }
    } else {
        None
    }
}

fn summarize_response_shape(response: &Value) -> Option<String> {
    if let Some(arr) = response.as_array() {
        return Some(format!("{} items returned", arr.len()));
    }
    if let Some(obj) = response.as_object() {
        return Some(format!("{} fields returned", obj.len()));
    }
    if response.is_null() {
        return Some("no payload".to_string());
    }
    None
}

fn truncate(text: &str, max_chars: usize) -> String {
    let mut out = text.trim().to_string();
    if out.chars().count() <= max_chars {
        return out;
    }

    out = out.chars().take(max_chars).collect::<String>();
    out.push_str("...");
    out
}

fn progress_snapshot(state: &StreamState, done: bool) -> (u8, String) {
    if done {
        return (100, "Complete".to_string());
    }

    if state.tools_started > 0 {
        let total = state.tools_started.max(state.tools_completed).max(1);
        let completed = state.tools_completed.min(total);
        if completed < total {
            let fraction = completed as f32 / total as f32;
            let percent = (25.0 + fraction * 55.0).round() as u8;
            return (
                percent.min(88),
                format!("Running tools ({completed}/{total})"),
            );
        }
        if state.saw_model_text {
            return (92, "Synthesizing report".to_string());
        }
        return (88, "Summarizing tool output".to_string());
    }

    if state.saw_model_text {
        return (90, "Finalizing response".to_string());
    }

    (12, "Understanding request".to_string())
}

fn emit_progress_if_changed(
    app: &AppHandle,
    request_id: &str,
    state: &mut StreamState,
    done: bool,
) -> Result<(), String> {
    let (percent, stage) = progress_snapshot(state, done);
    let changed = state.last_progress_percent != Some(percent)
        || state
            .last_progress_stage
            .as_deref()
            .map(|s| s != stage.as_str())
            .unwrap_or(true);
    if !changed {
        return Ok(());
    }

    state.last_progress_percent = Some(percent);
    state.last_progress_stage = Some(stage.clone());

    emit(
        app,
        request_id,
        StreamProgress {
            kind: "stream_progress",
            request_id: request_id.to_string(),
            percent,
            stage,
            tools_completed: state.tools_completed,
            tools_total: state.tools_started,
        },
    )
}

fn emit<T: Serialize + Clone>(app: &AppHandle, request_id: &str, payload: T) -> Result<(), String> {
    let event_name = format!("agent-stream:{request_id}");
    app.emit(&event_name, payload)
        .map_err(|e| format!("failed to emit stream event: {e}"))
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{
        extract_event_source, extract_invocation_id, extract_model_text, extract_run_events,
        extract_tool_signals,
    };

    #[test]
    fn extracts_only_model_text() {
        let model_event = json!({
            "content": {
                "role": "model",
                "parts": [{"text": "Hello"}]
            }
        });
        let tool_event = json!({
            "content": {
                "role": "user",
                "parts": [{"text": "Tool output"}]
            }
        });

        assert_eq!(extract_model_text(&model_event), Some("Hello".to_string()));
        assert_eq!(extract_model_text(&tool_event), None);
    }

    #[test]
    fn extracts_tool_calls_and_queries() {
        let event = json!({
            "content": {
                "parts": [
                    {
                        "functionCall": {
                            "name": "brave_search",
                            "args": { "query": "interview handoff tools" }
                        }
                    },
                    {
                        "functionResponse": {
                            "name": "brave_search",
                            "response": [{"title": "A"}]
                        }
                    }
                ]
            }
        });

        let signals = extract_tool_signals(&event);
        assert_eq!(signals.len(), 2);
        assert_eq!(signals[0].phase, "start");
        assert_eq!(signals[0].name, "brave_search");
        assert_eq!(
            signals[0].query,
            Some("interview handoff tools".to_string())
        );
        assert_eq!(signals[1].phase, "done");
        assert_eq!(signals[1].name, "brave_search");
    }

    #[test]
    fn extracts_event_source() {
        let event = json!({"author": "reddit_summary_agent"});
        assert_eq!(
            extract_event_source(&event),
            Some("reddit_summary_agent".to_string())
        );
    }

    #[test]
    fn extracts_invocation_id_from_common_shapes() {
        let direct = json!({ "invocationId": "abc" });
        let snake = json!({ "invocation_id": "def" });
        let nested = json!({ "metadata": { "invocationId": "ghi" } });
        assert_eq!(extract_invocation_id(&direct), Some("abc".to_string()));
        assert_eq!(extract_invocation_id(&snake), Some("def".to_string()));
        assert_eq!(extract_invocation_id(&nested), Some("ghi".to_string()));
    }

    #[test]
    fn extracts_events_from_wrapped_run_payload() {
        let wrapped = json!({
            "events": [
                {"id": "a"},
                {"id": "b"}
            ]
        });
        let extracted = extract_run_events(&wrapped).expect("events should exist");
        assert_eq!(extracted.len(), 2);
    }
}
