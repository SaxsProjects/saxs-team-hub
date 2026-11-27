//! SaxsProjects Team Hub for Windows.
//!
//! One window that shows hub.saxsprojects.co.za, the same Team Hub as on the web. Windows Hello works
//! through passkeys in the built-in Edge WebView2. The app adds what a browser tab can't:
//! a Start menu entry, one window only, its size and place remembered, a friendly offline page,
//! downloads into Downloads\Team Hub, and automatic updates from the GitHub releases.
//!
//! The pages have no access to the computer: the hub is loaded as an ordinary website, with no Tauri
//! commands exposed to it. Only the Team Hub's own addresses open inside the app; any other link
//! opens in the person's normal browser.

use std::path::{Path, PathBuf};
use std::time::Duration;

use tauri::webview::DownloadEvent;
use tauri::{AppHandle, Manager, Url, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_updater::UpdaterExt;

const HUB_HOSTS: [&str; 2] = ["hub.saxsprojects.co.za", "api.saxsprojects.co.za"];
const MAIN: &str = "main";

/// The web app recognises the Windows app by this, so the device list says "Team Hub Windows app".
const USER_AGENT: &str = concat!(
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) ",
    "Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0 TeamHubDesktop/",
    env!("CARGO_PKG_VERSION")
);

/// Addresses that may open inside the app window.
fn stays_inside(url: &Url) -> bool {
    match url.scheme() {
        "https" => url.host_str().is_some_and(|h| HUB_HOSTS.contains(&h)),
        // The offline page bundled with the app.
        "tauri" | "http" => {
            url.host_str() == Some("tauri.localhost") || url.host_str() == Some("localhost")
        }
        "about" | "blob" | "data" => true,
        _ => false,
    }
}

/// Links that may leave the app for the normal browser or mail program. Anything else is ignored.
fn may_open_outside(url: &Url) -> bool {
    matches!(url.scheme(), "https" | "mailto")
}

fn open_outside(url: &Url) {
    if may_open_outside(url) {
        let _ = tauri_plugin_opener::open_url(url.as_str(), None::<&str>);
    }
}

/// Downloads\Team Hub\<file name>, without overwriting an earlier file of the same name.
fn download_target(app: &AppHandle, suggested: &Path) -> Option<PathBuf> {
    let dir = app.path().download_dir().ok()?.join("Team Hub");
    std::fs::create_dir_all(&dir).ok()?;
    let name = suggested.file_name()?.to_string_lossy().to_string();
    let safe: String = name
        .chars()
        .map(|c| {
            if "\\/:*?\"<>|".contains(c) || c.is_control() {
                '_'
            } else {
                c
            }
        })
        .collect();
    let safe = if safe.trim_matches('.').trim().is_empty() {
        "document".to_string()
    } else {
        safe
    };
    let path = PathBuf::from(&safe);
    let (stem, ext) = (
        path.file_stem()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_else(|| "document".into()),
        path.extension()
            .map(|e| format!(".{}", e.to_string_lossy()))
            .unwrap_or_default(),
    );
    let mut target = dir.join(&safe);
    let mut n = 2;
    while target.exists() {
        target = dir.join(format!("{stem} ({n}){ext}"));
        n += 1;
    }
    Some(target)
}

fn main_window(app: &AppHandle) -> tauri::Result<()> {
    let handle = app.clone();
    WebviewWindowBuilder::new(app, MAIN, WebviewUrl::App("index.html".into()))
        .title("SaxsProjects Team Hub")
        .inner_size(1280.0, 820.0)
        .min_inner_size(380.0, 560.0)
        .user_agent(USER_AGENT)
        .on_navigation(|url| {
            if stays_inside(url) {
                true
            } else {
                open_outside(url);
                false
            }
        })
        .on_new_window(|url, _features| {
            // target="_blank" and window.open: the hub's own pages replace nothing, other sites go to the browser.
            open_outside(&url);
            tauri::webview::NewWindowResponse::Deny
        })
        .on_download(move |_webview, event| match event {
            DownloadEvent::Requested { url, destination } => {
                if !stays_inside(&url) {
                    return false;
                }
                match download_target(&handle, destination) {
                    Some(target) => {
                        *destination = target;
                        true
                    }
                    None => false,
                }
            }
            DownloadEvent::Finished { .. } => true,
            _ => true,
        })
        .build()?;
    Ok(())
}

/// How often a long-open app looks for a new version (it also looks every time it starts).
const UPDATE_CHECK_EVERY: Duration = Duration::from_secs(6 * 60 * 60);
const RELEASES: &str = "https://github.com/SaxsProjects/saxs-team-hub/releases/latest";

/// Look for a new version in the GitHub releases; ask before installing it.
async fn check_for_update(app: &AppHandle) {
    let Ok(updater) = app.updater() else { return };
    let Ok(Some(update)) = updater.check().await else {
        return; // offline, or already up to date
    };
    let install = app
        .dialog()
        .message(format!(
            "Version {} of the Team Hub app is ready (you have {}). It installs in a few seconds and the app opens again.",
            update.version, update.current_version
        ))
        .title("Update available")
        .kind(MessageDialogKind::Info)
        .buttons(MessageDialogButtons::OkCancelCustom("Update now".into(), "Later".into()))
        .blocking_show();
    if !install {
        return;
    }
    // The update is only installed if its signature matches the key built into this app.
    match update.download_and_install(|_, _| {}, || {}).await {
        Ok(()) => app.restart(),
        Err(_) => {
            let open = app
                .dialog()
                .message(format!(
                    "Version {} couldn't be installed. Security software may have blocked the installer. \
                     You can download it from the Team Hub releases on GitHub instead.",
                    update.version
                ))
                .title("Update not installed")
                .kind(MessageDialogKind::Warning)
                .buttons(MessageDialogButtons::OkCancelCustom("Open releases".into(), "Close".into()))
                .blocking_show();
            if open {
                let _ = tauri_plugin_opener::open_url(RELEASES, None::<&str>);
            }
        }
    }
}

/// Check now, then every few hours while the app stays open. Runs on its own thread so the
/// question never holds up the window.
fn watch_for_updates(app: AppHandle) {
    std::thread::spawn(move || loop {
        tauri::async_runtime::block_on(check_for_update(&app));
        std::thread::sleep(UPDATE_CHECK_EVERY);
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // Opening the app again brings the open window forward instead of starting a second copy.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window(MAIN) {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            main_window(app.handle())?;
            watch_for_updates(app.handle().clone());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("the Team Hub app could not start");
}

#[cfg(test)]
mod tests {
    use super::*;

    fn url(s: &str) -> Url {
        Url::parse(s).unwrap()
    }

    #[test]
    fn only_the_team_hub_opens_inside() {
        assert!(stays_inside(&url(
            "https://hub.saxsprojects.co.za/my/payouts"
        )));
        assert!(stays_inside(&url(
            "https://api.saxsprojects.co.za/forgot-password"
        )));
        assert!(stays_inside(&url("http://tauri.localhost/index.html")));
        assert!(!stays_inside(&url("http://hub.saxsprojects.co.za/"))); // never plain http
        assert!(!stays_inside(&url(
            "https://hub.saxsprojects.co.za.evil.example/"
        )));
        assert!(!stays_inside(&url("https://saxsprojects.co.za/")));
        assert!(!stays_inside(&url("file:///C:/Windows/win.ini")));
    }

    #[test]
    fn only_web_and_mail_links_leave_the_app() {
        assert!(may_open_outside(&url("https://www.sars.gov.za/")));
        assert!(may_open_outside(&url("mailto:founder@example.com")));
        assert!(!may_open_outside(&url(
            "file:///C:/Windows/System32/cmd.exe"
        )));
        assert!(!may_open_outside(&url("ms-settings:privacy")));
        assert!(!may_open_outside(&url("http://example.com/")));
    }
}
