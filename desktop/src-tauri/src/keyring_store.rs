#[cfg(not(target_os = "macos"))]
use keyring::{Entry, Error as KeyringError};
#[cfg(target_os = "macos")]
use std::process::Command;

use crate::types::{KeyPresence, KeysInput};

const SERVICE: &str = "project-validator-search";
const GOOGLE_ACCOUNT: &str = "google_api_key";
const BRAVE_ACCOUNT: &str = "brave_search_api_key";
const GEMINI_ACCOUNT: &str = "gemini_api_key";

#[derive(Debug, Clone)]
pub struct KeyEnv {
    pub google_api_key: Option<String>,
    pub brave_api_key: Option<String>,
    pub gemini_api_key: Option<String>,
}

#[derive(Debug, Clone, Default)]
pub struct KeyStore;

impl KeyStore {
    pub fn set_keys(&self, keys: KeysInput) -> Result<(), String> {
        let google_provided = keys
            .google_api_key
            .as_ref()
            .map(|v| !v.trim().is_empty())
            .unwrap_or(false);
        let brave_provided = keys
            .brave_api_key
            .as_ref()
            .map(|v| !v.trim().is_empty())
            .unwrap_or(false);
        let gemini_provided = keys
            .gemini_api_key
            .as_ref()
            .map(|v| !v.trim().is_empty())
            .unwrap_or(false);

        if let Some(value) = keys.google_api_key {
            set_value(GOOGLE_ACCOUNT, &value)?;
        }
        if let Some(value) = keys.brave_api_key {
            set_value(BRAVE_ACCOUNT, &value)?;
        }
        if let Some(value) = keys.gemini_api_key {
            set_value(GEMINI_ACCOUNT, &value)?;
        }

        let presence = self.key_presence()?;
        eprintln!(
            "[keyring] set_keys provided google={} brave={} gemini={} | post-save presence google={} brave={} gemini={}",
            google_provided,
            brave_provided,
            gemini_provided,
            presence.google_api_key_set,
            presence.brave_api_key_set,
            presence.gemini_api_key_set
        );

        if google_provided && !presence.google_api_key_set {
            return Err(
                "Google API key was submitted but could not be verified from OS keychain.".to_string(),
            );
        }
        if brave_provided && !presence.brave_api_key_set {
            return Err(
                "Brave Search API key was submitted but could not be verified from OS keychain."
                    .to_string(),
            );
        }
        if gemini_provided && !presence.gemini_api_key_set {
            return Err(
                "Gemini API key was submitted but could not be verified from OS keychain.".to_string(),
            );
        }

        Ok(())
    }

    pub fn clear_keys(&self) -> Result<(), String> {
        delete_value(GOOGLE_ACCOUNT)?;
        delete_value(BRAVE_ACCOUNT)?;
        delete_value(GEMINI_ACCOUNT)?;
        Ok(())
    }

    pub fn read_env_values(&self) -> Result<KeyEnv, String> {
        Ok(KeyEnv {
            google_api_key: get_value(GOOGLE_ACCOUNT)?,
            brave_api_key: get_value(BRAVE_ACCOUNT)?,
            gemini_api_key: get_value(GEMINI_ACCOUNT)?,
        })
    }

    pub fn key_presence(&self) -> Result<KeyPresence, String> {
        let google = get_value(GOOGLE_ACCOUNT)?;
        let brave = get_value(BRAVE_ACCOUNT)?;
        let gemini = get_value(GEMINI_ACCOUNT)?;

        Ok(KeyPresence {
            google_api_key_set: google.is_some(),
            brave_api_key_set: brave.is_some(),
            gemini_api_key_set: gemini.is_some(),
            google_api_key_masked: google.as_deref().map(mask_secret),
            brave_api_key_masked: brave.as_deref().map(mask_secret),
            gemini_api_key_masked: gemini.as_deref().map(mask_secret),
        })
    }
}

#[cfg(not(target_os = "macos"))]
fn entry(account: &str) -> Result<Entry, String> {
    Entry::new(SERVICE, account).map_err(|e| e.to_string())
}

#[cfg(target_os = "macos")]
fn command_output(cmd: &mut Command) -> Result<std::process::Output, String> {
    cmd.output()
        .map_err(|e| format!("failed to invoke macOS `security` CLI: {e}"))
}

#[cfg(target_os = "macos")]
fn set_value(account: &str, value: &str) -> Result<(), String> {
    if value.trim().is_empty() {
        return Ok(());
    }

    let mut cmd = Command::new("security");
    cmd.args([
        "add-generic-password",
        "-U",
        "-s",
        SERVICE,
        "-a",
        account,
        "-w",
        value,
    ]);

    let output = command_output(&mut cmd)?;
    if output.status.success() {
        return Ok(());
    }

    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    Err(format!(
        "failed to store key '{}' via macOS keychain (exit={}): {}",
        account,
        output
            .status
            .code()
            .map(|code| code.to_string())
            .unwrap_or_else(|| "signal".to_string()),
        if stderr.is_empty() {
            "unknown error".to_string()
        } else {
            stderr
        }
    ))
}

#[cfg(not(target_os = "macos"))]
fn set_value(account: &str, value: &str) -> Result<(), String> {
    if value.trim().is_empty() {
        return Ok(());
    }
    entry(account)?
        .set_password(value)
        .map_err(|e| format!("failed to store key '{}': {}", account, e))
}

#[cfg(target_os = "macos")]
fn get_value(account: &str) -> Result<Option<String>, String> {
    let mut cmd = Command::new("security");
    cmd.args([
        "find-generic-password",
        "-s",
        SERVICE,
        "-a",
        account,
        "-w",
    ]);

    let output = command_output(&mut cmd)?;
    if output.status.success() {
        let value = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if value.is_empty() {
            return Ok(None);
        }
        return Ok(Some(value));
    }

    if matches!(output.status.code(), Some(44)) {
        return Ok(None);
    }

    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    Err(format!(
        "failed to read key '{}' via macOS keychain (exit={}): {}",
        account,
        output
            .status
            .code()
            .map(|code| code.to_string())
            .unwrap_or_else(|| "signal".to_string()),
        if stderr.is_empty() {
            "unknown error".to_string()
        } else {
            stderr
        }
    ))
}

#[cfg(not(target_os = "macos"))]
fn get_value(account: &str) -> Result<Option<String>, String> {
    match entry(account)?.get_password() {
        Ok(value) if !value.trim().is_empty() => Ok(Some(value)),
        Ok(_) => Ok(None),
        Err(KeyringError::NoEntry) => Ok(None),
        Err(err) => Err(format!("failed to read key '{}': {}", account, err)),
    }
}

#[cfg(target_os = "macos")]
fn delete_value(account: &str) -> Result<(), String> {
    let mut cmd = Command::new("security");
    cmd.args(["delete-generic-password", "-s", SERVICE, "-a", account]);

    let output = command_output(&mut cmd)?;
    if output.status.success() || matches!(output.status.code(), Some(44)) {
        return Ok(());
    }

    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    Err(format!(
        "failed to clear key '{}' via macOS keychain (exit={}): {}",
        account,
        output
            .status
            .code()
            .map(|code| code.to_string())
            .unwrap_or_else(|| "signal".to_string()),
        if stderr.is_empty() {
            "unknown error".to_string()
        } else {
            stderr
        }
    ))
}

#[cfg(not(target_os = "macos"))]
fn delete_value(account: &str) -> Result<(), String> {
    match entry(account)?.delete_credential() {
        Ok(_) | Err(KeyringError::NoEntry) => Ok(()),
        Err(err) => Err(format!("failed to clear key '{}': {}", account, err)),
    }
}

pub fn mask_secret(secret: &str) -> String {
    let suffix_len = 4usize.min(secret.len());
    let suffix = &secret[secret.len().saturating_sub(suffix_len)..];
    format!("***{}", suffix)
}

#[cfg(test)]
mod tests {
    use super::mask_secret;

    #[test]
    fn mask_secret_keeps_last_four() {
        assert_eq!(mask_secret("abcdef1234"), "***1234");
        assert_eq!(mask_secret("abc"), "***abc");
    }
}
