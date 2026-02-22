use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::{params, Connection, OptionalExtension};
use tauri::{AppHandle, Manager};
use uuid::Uuid;

use crate::types::{
    RunMode, SessionCreateInput, SessionListInput, SessionMessage, SessionMessageAppendInput,
    SessionMeta, SessionPhase, SessionPhaseState,
};

const DEFAULT_DB_NAME: &str = "desktop_sessions.sqlite3";

#[derive(Debug, Clone)]
pub struct ReplayMessage {
    pub role: String,
    pub text: String,
}

#[derive(Debug, Clone)]
pub struct SessionStore {
    db_path: PathBuf,
}

impl SessionStore {
    pub fn from_app(app: &AppHandle) -> Result<Self, String> {
        let app_data_dir = app
            .path()
            .app_data_dir()
            .map_err(|e| format!("Failed to resolve app data dir: {e}"))?;

        fs::create_dir_all(&app_data_dir)
            .map_err(|e| format!("Failed to create app data dir {:?}: {e}", app_data_dir))?;

        Ok(Self::from_path(app_data_dir.join(DEFAULT_DB_NAME)))
    }

    pub fn from_path(db_path: PathBuf) -> Self {
        Self { db_path }
    }

    pub fn db_path(&self) -> PathBuf {
        self.db_path.clone()
    }

    pub fn create_session(&self, input: &SessionCreateInput) -> Result<SessionMeta, String> {
        let id = input
            .session_id
            .clone()
            .unwrap_or_else(|| format!("desktop-{}", Uuid::new_v4()));
        let now = now_ms();

        let conn = self.open_conn()?;
        conn.execute(
            "INSERT OR IGNORE INTO sessions (id, title, app_name, user_id, phase, read_only, created_at_ms, updated_at_ms)
             VALUES (?1, '', ?2, ?3, ?4, 0, ?5, ?5)",
            params![
                id,
                input.app_name,
                input.user_id,
                SessionPhase::IdeaInput.as_str(),
                now
            ],
        )
        .map_err(|e| format!("Failed to create session in local DB: {e}"))?;

        self.get_session(&conn, &id)?
            .ok_or_else(|| "Created session could not be loaded from local DB.".to_string())
    }

    pub fn list_sessions(&self, input: &SessionListInput) -> Result<Vec<SessionMeta>, String> {
        let conn = self.open_conn()?;
        let mut stmt = conn
            .prepare(
                "SELECT id, title, app_name, user_id, phase, read_only, created_at_ms, updated_at_ms
                 FROM sessions
                 WHERE app_name = ?1 AND user_id = ?2
                 ORDER BY updated_at_ms DESC, created_at_ms DESC",
            )
            .map_err(|e| format!("Failed to prepare session list query: {e}"))?;

        let rows = stmt
            .query_map(params![input.app_name, input.user_id], |row| {
                map_session_row(
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                    row.get(5)?,
                    row.get(6)?,
                    row.get(7)?,
                )
            })
            .map_err(|e| format!("Failed to query session list: {e}"))?;

        let mut out = Vec::new();
        for row in rows {
            out.push(row.map_err(|e| format!("Failed to parse session list row: {e}"))?);
        }
        Ok(out)
    }

    pub fn delete_session(&self, session_id: &str) -> Result<bool, String> {
        let conn = self.open_conn()?;
        let deleted = conn
            .execute("DELETE FROM sessions WHERE id = ?1", params![session_id])
            .map_err(|e| format!("Failed to delete session '{}': {e}", session_id))?;
        Ok(deleted > 0)
    }

    pub fn messages_get(&self, session_id: &str) -> Result<Vec<SessionMessage>, String> {
        let conn = self.open_conn()?;
        let mut stmt = conn
            .prepare(
                "SELECT id, session_id, role, text, status, created_at_ms
                 FROM messages
                 WHERE session_id = ?1
                 ORDER BY created_at_ms ASC, rowid ASC",
            )
            .map_err(|e| format!("Failed to prepare messages query: {e}"))?;

        let rows = stmt
            .query_map(params![session_id], |row| {
                Ok(SessionMessage {
                    id: row.get(0)?,
                    session_id: row.get(1)?,
                    role: row.get(2)?,
                    text: row.get(3)?,
                    status: row.get(4)?,
                    created_at_ms: row.get(5)?,
                })
            })
            .map_err(|e| format!("Failed to query messages: {e}"))?;

        let mut out = Vec::new();
        for row in rows {
            out.push(row.map_err(|e| format!("Failed to parse message row: {e}"))?);
        }
        Ok(out)
    }

    pub fn message_append(
        &self,
        input: &SessionMessageAppendInput,
    ) -> Result<SessionMessage, String> {
        let conn = self.open_conn()?;
        let session_exists: Option<String> = conn
            .query_row(
                "SELECT id FROM sessions WHERE id = ?1",
                params![input.session_id],
                |row| row.get(0),
            )
            .optional()
            .map_err(|e| format!("Failed to verify session before appending message: {e}"))?;

        if session_exists.is_none() {
            return Err(format!(
                "Cannot append message: session '{}' does not exist in local DB.",
                input.session_id
            ));
        }

        let message = SessionMessage {
            id: format!("msg-{}", Uuid::new_v4()),
            session_id: input.session_id.clone(),
            role: input.role.clone(),
            text: input.text.clone(),
            status: input.status.clone(),
            created_at_ms: input.created_at_ms.unwrap_or_else(now_ms),
        };

        conn.execute(
            "INSERT INTO messages (id, session_id, role, text, status, created_at_ms)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params![
                message.id,
                message.session_id,
                message.role,
                message.text,
                message.status,
                message.created_at_ms
            ],
        )
        .map_err(|e| format!("Failed to append message: {e}"))?;

        let title_candidate = infer_title_from_message(&message.role, &message.text);
        let update_time = now_ms();

        conn.execute(
            "UPDATE sessions
             SET title = CASE WHEN TRIM(title) = '' AND ?1 IS NOT NULL THEN ?1 ELSE title END,
                 updated_at_ms = ?2
             WHERE id = ?3",
            params![title_candidate, update_time, input.session_id],
        )
        .map_err(|e| format!("Failed to update session metadata after message append: {e}"))?;

        Ok(message)
    }

    pub fn phase_get(&self, session_id: &str) -> Result<SessionPhaseState, String> {
        let conn = self.open_conn()?;
        let row: Option<(String, i64)> = conn
            .query_row(
                "SELECT phase, read_only FROM sessions WHERE id = ?1",
                params![session_id],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()
            .map_err(|e| format!("Failed to read session phase: {e}"))?;

        let Some((phase_raw, read_only_raw)) = row else {
            return Err(format!("Session '{}' was not found.", session_id));
        };

        Ok(SessionPhaseState {
            phase: parse_phase(&phase_raw)?,
            read_only: read_only_raw != 0,
        })
    }

    pub fn phase_set(
        &self,
        session_id: &str,
        phase: SessionPhase,
        read_only: bool,
    ) -> Result<SessionPhaseState, String> {
        let conn = self.open_conn()?;
        let updated = conn
            .execute(
                "UPDATE sessions
                 SET phase = ?1, read_only = ?2, updated_at_ms = ?3
                 WHERE id = ?4",
                params![
                    phase.as_str(),
                    if read_only { 1 } else { 0 },
                    now_ms(),
                    session_id
                ],
            )
            .map_err(|e| format!("Failed to update session phase: {e}"))?;

        if updated == 0 {
            return Err(format!("Session '{}' was not found.", session_id));
        }

        Ok(SessionPhaseState { phase, read_only })
    }

    pub fn validate_run_mode(
        &self,
        session_id: &str,
        run_mode: RunMode,
    ) -> Result<SessionPhaseState, String> {
        let state = self.phase_get(session_id)?;
        if state.read_only {
            return Err(format!(
                "Session is read-only in phase '{}'.",
                state.phase.as_str()
            ));
        }

        if !is_run_mode_allowed(state.phase, run_mode) {
            return Err(format!(
                "Run mode '{}' is not allowed while phase is '{}'.",
                run_mode_as_str(run_mode),
                state.phase.as_str()
            ));
        }

        Ok(state)
    }

    pub fn replay_messages(
        &self,
        session_id: &str,
        current_text: &str,
        max_messages: usize,
    ) -> Result<Vec<ReplayMessage>, String> {
        let mut messages: Vec<ReplayMessage> = self
            .messages_get(session_id)?
            .into_iter()
            .filter_map(|m| {
                if m.status.trim().to_ascii_lowercase() != "done" {
                    return None;
                }

                let trimmed = m.text.trim().to_string();
                if trimmed.is_empty() {
                    return None;
                }
                Some(ReplayMessage {
                    role: m.role,
                    text: trimmed,
                })
            })
            .collect();

        if let Some(last) = messages.last() {
            if normalize_text(&last.text) == normalize_text(current_text)
                && normalize_text(&last.role) == "user"
            {
                messages.pop();
            }
        }

        if messages.len() > max_messages {
            let start = messages.len() - max_messages;
            messages = messages[start..].to_vec();
        }

        Ok(messages)
    }

    fn open_conn(&self) -> Result<Connection, String> {
        let conn = Connection::open(&self.db_path)
            .map_err(|e| format!("Failed to open local session DB {:?}: {e}", self.db_path))?;
        conn.execute("PRAGMA foreign_keys = ON", [])
            .map_err(|e| format!("Failed to enable foreign keys on local session DB: {e}"))?;
        conn.pragma_update(None, "journal_mode", "WAL")
            .map_err(|e| format!("Failed to set WAL mode on local session DB: {e}"))?;
        self.init_schema(&conn)?;
        Ok(conn)
    }

    fn init_schema(&self, conn: &Connection) -> Result<(), String> {
        conn.execute_batch(
            "
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                app_name TEXT NOT NULL,
                user_id TEXT NOT NULL,
                phase TEXT NOT NULL,
                read_only INTEGER NOT NULL DEFAULT 0,
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_owner
                ON sessions(app_name, user_id, updated_at_ms DESC);

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session_created
                ON messages(session_id, created_at_ms ASC);
            ",
        )
        .map_err(|e| format!("Failed to initialize local session DB schema: {e}"))?;
        Ok(())
    }

    fn get_session(
        &self,
        conn: &Connection,
        session_id: &str,
    ) -> Result<Option<SessionMeta>, String> {
        conn.query_row(
            "SELECT id, title, app_name, user_id, phase, read_only, created_at_ms, updated_at_ms
             FROM sessions
             WHERE id = ?1",
            params![session_id],
            |row| {
                map_session_row(
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                    row.get(5)?,
                    row.get(6)?,
                    row.get(7)?,
                )
            },
        )
        .optional()
        .map_err(|e| format!("Failed to load session '{}': {e}", session_id))
    }
}

pub fn is_run_mode_allowed(phase: SessionPhase, run_mode: RunMode) -> bool {
    matches!(
        (phase, run_mode),
        (SessionPhase::IdeaInput, RunMode::Idea)
            | (SessionPhase::AwaitingApproval, RunMode::EditPlan)
            | (SessionPhase::AwaitingApproval, RunMode::Approve)
    )
}

pub fn phase_after_run(run_mode: RunMode, succeeded: bool) -> (SessionPhase, bool) {
    if succeeded {
        match run_mode {
            RunMode::Idea | RunMode::EditPlan => (SessionPhase::AwaitingApproval, false),
            RunMode::Approve => (SessionPhase::Completed, true),
        }
    } else {
        (SessionPhase::Failed, true)
    }
}

fn map_session_row(
    id: String,
    title: String,
    app_name: String,
    user_id: String,
    phase_raw: String,
    read_only_raw: i64,
    created_at_ms: i64,
    updated_at_ms: i64,
) -> rusqlite::Result<SessionMeta> {
    let phase = parse_phase(&phase_raw).map_err(|e| {
        rusqlite::Error::FromSqlConversionFailure(
            0,
            rusqlite::types::Type::Text,
            Box::new(std::io::Error::new(std::io::ErrorKind::InvalidData, e)),
        )
    })?;

    Ok(SessionMeta {
        id,
        title,
        app_name,
        user_id,
        phase,
        read_only: read_only_raw != 0,
        created_at_ms,
        updated_at_ms,
    })
}

fn parse_phase(raw: &str) -> Result<SessionPhase, String> {
    match raw.trim().to_ascii_lowercase().as_str() {
        "idea_input" => Ok(SessionPhase::IdeaInput),
        "awaiting_approval" => Ok(SessionPhase::AwaitingApproval),
        "running" => Ok(SessionPhase::Running),
        "completed" => Ok(SessionPhase::Completed),
        "failed" => Ok(SessionPhase::Failed),
        other => Err(format!("Unknown session phase '{}'.", other)),
    }
}

fn run_mode_as_str(run_mode: RunMode) -> &'static str {
    match run_mode {
        RunMode::Idea => "idea",
        RunMode::EditPlan => "edit_plan",
        RunMode::Approve => "approve",
    }
}

fn now_ms() -> i64 {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    elapsed.as_millis() as i64
}

fn normalize_text(value: &str) -> String {
    value
        .trim()
        .to_ascii_lowercase()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn infer_title_from_message(role: &str, text: &str) -> Option<String> {
    if normalize_text(role) != "user" {
        return None;
    }

    let normalized = text.trim().split_whitespace().collect::<Vec<_>>().join(" ");
    if normalized.is_empty() {
        return None;
    }

    if normalized.chars().count() <= 56 {
        return Some(normalized);
    }

    Some(format!(
        "{}...",
        normalized.chars().take(56).collect::<String>()
    ))
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use crate::types::{
        RunMode, SessionCreateInput, SessionListInput, SessionMessageAppendInput, SessionPhase,
    };

    use super::{is_run_mode_allowed, phase_after_run, SessionStore};

    fn test_db_path(name: &str) -> PathBuf {
        let mut path = std::env::temp_dir();
        path.push(format!(
            "pv-desktop-{name}-{}.sqlite3",
            uuid::Uuid::new_v4()
        ));
        path
    }

    #[test]
    fn session_crud_and_message_ordering() {
        let store = SessionStore::from_path(test_db_path("crud"));
        let session = store
            .create_session(&SessionCreateInput {
                app_name: "product_validator_search".to_string(),
                user_id: "u1".to_string(),
                session_id: None,
            })
            .expect("session should be created");

        store
            .message_append(&SessionMessageAppendInput {
                session_id: session.id.clone(),
                role: "user".to_string(),
                text: "hello".to_string(),
                status: "done".to_string(),
                created_at_ms: Some(10),
            })
            .expect("first message");
        store
            .message_append(&SessionMessageAppendInput {
                session_id: session.id.clone(),
                role: "assistant".to_string(),
                text: "world".to_string(),
                status: "done".to_string(),
                created_at_ms: Some(20),
            })
            .expect("second message");

        let sessions = store
            .list_sessions(&SessionListInput {
                app_name: "product_validator_search".to_string(),
                user_id: "u1".to_string(),
            })
            .expect("list sessions");
        assert_eq!(sessions.len(), 1);
        assert_eq!(sessions[0].title, "hello");
        assert_eq!(sessions[0].phase, SessionPhase::IdeaInput);

        let messages = store.messages_get(&session.id).expect("messages");
        assert_eq!(messages.len(), 2);
        assert_eq!(messages[0].text, "hello");
        assert_eq!(messages[1].text, "world");
    }

    #[test]
    fn run_mode_matrix_matches_phase_contract() {
        assert!(is_run_mode_allowed(SessionPhase::IdeaInput, RunMode::Idea));
        assert!(!is_run_mode_allowed(
            SessionPhase::IdeaInput,
            RunMode::EditPlan
        ));
        assert!(is_run_mode_allowed(
            SessionPhase::AwaitingApproval,
            RunMode::EditPlan
        ));
        assert!(is_run_mode_allowed(
            SessionPhase::AwaitingApproval,
            RunMode::Approve
        ));
        assert!(!is_run_mode_allowed(SessionPhase::Completed, RunMode::Idea));
    }

    #[test]
    fn phase_transition_defaults_follow_plan() {
        assert_eq!(
            phase_after_run(RunMode::Idea, true),
            (SessionPhase::AwaitingApproval, false)
        );
        assert_eq!(
            phase_after_run(RunMode::EditPlan, true),
            (SessionPhase::AwaitingApproval, false)
        );
        assert_eq!(
            phase_after_run(RunMode::Approve, true),
            (SessionPhase::Completed, true)
        );
        assert_eq!(
            phase_after_run(RunMode::Approve, false),
            (SessionPhase::Failed, true)
        );
    }

    #[test]
    fn replay_window_keeps_last_twenty_and_drops_current_duplicate() {
        let store = SessionStore::from_path(test_db_path("replay"));
        let session = store
            .create_session(&SessionCreateInput {
                app_name: "product_validator_search".to_string(),
                user_id: "u1".to_string(),
                session_id: Some("s1".to_string()),
            })
            .expect("session create");

        for index in 0..25 {
            store
                .message_append(&SessionMessageAppendInput {
                    session_id: session.id.clone(),
                    role: "user".to_string(),
                    text: format!("message-{index}"),
                    status: "done".to_string(),
                    created_at_ms: Some(index),
                })
                .expect("append");
        }

        let replay = store
            .replay_messages(&session.id, "message-24", 20)
            .expect("replay");
        assert_eq!(replay.len(), 20);
        assert_eq!(replay.first().map(|m| m.text.as_str()), Some("message-4"));
        assert_eq!(replay.last().map(|m| m.text.as_str()), Some("message-23"));
    }

    #[test]
    fn delete_session_removes_messages_via_cascade() {
        let store = SessionStore::from_path(test_db_path("delete"));
        let session = store
            .create_session(&SessionCreateInput {
                app_name: "product_validator_search".to_string(),
                user_id: "u1".to_string(),
                session_id: None,
            })
            .expect("session create");

        store
            .message_append(&SessionMessageAppendInput {
                session_id: session.id.clone(),
                role: "user".to_string(),
                text: "hello".to_string(),
                status: "done".to_string(),
                created_at_ms: Some(10),
            })
            .expect("append");

        assert!(store
            .delete_session(&session.id)
            .expect("delete should work"));
        let messages = store.messages_get(&session.id).expect("messages read");
        assert!(messages.is_empty());
    }
}
