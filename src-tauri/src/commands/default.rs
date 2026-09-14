use super::errors::Error;
use std::fs;
use std::path::{Path, PathBuf};
use tauri::{AppHandle, Manager};

#[tauri::command]
pub fn read(app: AppHandle, path: String) -> Result<String, Error> {
    let data = read_at(&app_data_dir(&app)?, &path)?;
    let string = String::from_utf8(data)?;
    Ok(string)
}

#[tauri::command]
pub fn write(app: AppHandle, path: String, contents: String) -> Result<(), Error> {
    write_at(&app_data_dir(&app)?, &path, contents)
}

fn app_data_dir(app: &AppHandle) -> Result<PathBuf, Error> {
    app.path()
        .app_data_dir()
        .map_err(|e| Error::InvalidPath(e.to_string()))
}

fn safe_path(base: &Path, path: &str) -> Result<PathBuf, Error> {
    // The allowlist is exact-match, so `canonicalize` + `starts_with` below
    // can never fire today. It's kept as defence-in-depth for the day someone
    // relaxes the allowlist to a glob or user-provided filename — at that
    // point the containment check becomes load-bearing, not decorative.
    match path {
        "greet.txt" | "name.txt" => {
            let base = fs::canonicalize(base)?;
            let candidate = base.join(path);
            if candidate.exists() {
                let target = fs::canonicalize(&candidate)?;
                if !target.starts_with(&base) {
                    return Err(Error::InvalidPath(path.to_string()));
                }
            }
            Ok(candidate)
        }
        _ => Err(Error::InvalidPath(path.to_string())),
    }
}

fn read_at(base: &Path, path: &str) -> Result<Vec<u8>, Error> {
    // safe_path canonicalizes `base`, which fails if the dir doesn't exist
    // yet (e.g. first launch before the sidecar setup creates it).
    fs::create_dir_all(base)?;
    Ok(fs::read(safe_path(base, path)?)?)
}

fn write_at(base: &Path, path: &str, contents: String) -> Result<(), Error> {
    fs::create_dir_all(base)?;
    fs::write(safe_path(base, path)?, contents)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn write_then_read_roundtrip() {
        let tmp = tempdir().unwrap();
        let base = tmp.path();

        write_at(base, "greet.txt", "Hello, Tauri!".to_string()).unwrap();
        let result = String::from_utf8(read_at(base, "greet.txt").unwrap()).unwrap();
        assert_eq!(result, "Hello, Tauri!");
    }

    #[test]
    fn write_overwrites_existing_content() {
        let tmp = tempdir().unwrap();
        let base = tmp.path();

        write_at(base, "name.txt", "first".to_string()).unwrap();
        write_at(base, "name.txt", "second".to_string()).unwrap();
        let result = String::from_utf8(read_at(base, "name.txt").unwrap()).unwrap();
        assert_eq!(result, "second");
    }

    #[test]
    fn write_empty_string() {
        let tmp = tempdir().unwrap();
        let base = tmp.path();

        write_at(base, "greet.txt", String::new()).unwrap();
        let result = String::from_utf8(read_at(base, "greet.txt").unwrap()).unwrap();
        assert_eq!(result, "");
    }

    #[test]
    fn write_unicode_content() {
        let tmp = tempdir().unwrap();
        let base = tmp.path();

        let unicode = "Olá, 世界! 🎉".to_string();
        write_at(base, "name.txt", unicode.clone()).unwrap();
        let result = String::from_utf8(read_at(base, "name.txt").unwrap()).unwrap();
        assert_eq!(result, unicode);
    }

    #[test]
    fn read_creates_missing_base_dir() {
        let tmp = tempdir().unwrap();
        let base = tmp.path().join("not-yet-created");
        assert!(!base.exists());

        let result = read_at(&base, "name.txt");
        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), Error::Io(_)));
        assert!(base.is_dir());
    }

    #[test]
    fn read_nonexistent_file_returns_io_error() {
        let tmp = tempdir().unwrap();
        let result = read_at(tmp.path(), "name.txt");
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(matches!(err, Error::Io(_)));
    }

    #[test]
    fn rejects_paths_outside_the_application_file_allowlist() {
        let tmp = tempdir().unwrap();
        let result = read_at(tmp.path(), "..\\secrets.txt");
        assert!(matches!(result, Err(Error::InvalidPath(_))));
    }

    #[test]
    fn read_invalid_utf8_returns_utf8_error() {
        let tmp = tempdir().unwrap();
        let base = tmp.path();
        // Write invalid UTF-8 bytes to an allowed application file.
        fs::write(base.join("name.txt"), [0xFF, 0xFE, 0x00, 0x80]).unwrap();

        let result = String::from_utf8(read_at(base, "name.txt").unwrap());
        assert!(result.is_err());
        assert!(matches!(result, Err(_)));
    }
}
