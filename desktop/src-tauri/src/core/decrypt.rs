use super::{footer, qmc2, Error, MusicExFooter, OutputMode, Result};
use std::fs::{self, File};
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};
use std::process::Command;

const BUFFER_SIZE: usize = 256 * 1024;

pub fn decrypt_file_with_progress<F>(
    input: &Path,
    output_dir: Option<&Path>,
    footer: &MusicExFooter,
    ekey: &str,
    output_mode: &OutputMode,
    mut on_progress: F,
) -> Result<(PathBuf, String)>
where
    F: FnMut(u64, u64, &'static str),
{
    let key = qmc2::derive_key(ekey)?;
    let file = File::open(input)?;
    let mut reader = BufReader::new(file).take(footer.audio_length);
    let mut first = vec![0u8; BUFFER_SIZE.min(footer.audio_length as usize)];
    let first_len = reader.read(&mut first)?;
    if first_len == 0 {
        return Err(Error::from("加密音频部分为空"));
    }
    first.truncate(first_len);
    qmc2::decrypt_chunk(&mut first, &key, 0);
    let format = qmc2::detect_format(&first).to_string();
    if format == "bin" {
        return Err(Error::from("ekey 无效，或文件不是受支持的 QMC2 音频"));
    }
    let output_folder = output_dir.unwrap_or_else(|| input.parent().unwrap_or(Path::new(".")));
    fs::create_dir_all(output_folder)?;
    let stem = input
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("decrypted");
    let raw_output = available_path(output_folder, stem, &format);
    let mut writer = BufWriter::new(File::create(&raw_output)?);
    writer.write_all(&first)?;
    let mut offset = first.len() as u64;
    on_progress(offset, footer.audio_length, "decrypt");
    let mut buffer = vec![0u8; BUFFER_SIZE];
    loop {
        let size = reader.read(&mut buffer)?;
        if size == 0 {
            break;
        }
        qmc2::decrypt_chunk(&mut buffer[..size], &key, offset);
        writer.write_all(&buffer[..size])?;
        offset += size as u64;
        on_progress(offset, footer.audio_length, "decrypt");
    }
    writer.flush()?;
    if matches!(output_mode, OutputMode::Mp3) && format != "mp3" {
        on_progress(0, 1, "transcode");
        let mp3_path = available_path(output_folder, stem, "mp3");
        convert_to_mp3(&raw_output, &mp3_path)?;
        on_progress(1, 1, "transcode");
        fs::remove_file(&raw_output)?;
        return Ok((mp3_path, "mp3".into()));
    }
    Ok((raw_output, format))
}

pub fn info(path: &Path) -> Result<MusicExFooter> {
    footer::parse_file(path)
}

pub(crate) fn available_path(directory: &Path, stem: &str, extension: &str) -> PathBuf {
    let base = directory.join(format!("{stem}.{extension}"));
    if !base.exists() {
        return base;
    }
    for index in 1..10_000 {
        let candidate = directory.join(format!("{stem} ({index}).{extension}"));
        if !candidate.exists() {
            return candidate;
        }
    }
    directory.join(format!("{stem}-decrypted.{extension}"))
}

/// 用 FFmpeg（libmp3lame VBR -q:a 2）把任意音频转成 MP3，加密与普通音频通道共用。
pub(crate) fn convert_to_mp3(input: &Path, output: &Path) -> Result<()> {
    let result = Command::new(ffmpeg_path())
        .args(["-y", "-i"])
        .arg(input)
        // 先映射全局标签（FLAC / M4A），再叠加首条音轨的流级标签：Ogg Vorbis 的注释
        // 挂在流上，只映射全局会把歌名、歌手全部丢掉
        .args(["-map_metadata", "0", "-map_metadata", "0:s:a:0"])
        .args(["-vn", "-codec:a", "libmp3lame", "-q:a", "2"])
        .arg(output)
        .output();
    match result {
        Ok(result)
            if result.status.success()
                && output
                    .metadata()
                    .map(|meta| meta.len() > 1024)
                    .unwrap_or(false) =>
        {
            Ok(())
        }
        Ok(result) => {
            // 失败时 FFmpeg 可能已留下半截文件，删掉，免得被当成可用输出
            let _ = fs::remove_file(output);
            Err(Error::from(format!(
                "FFmpeg 转码失败：{}",
                String::from_utf8_lossy(&result.stderr)
                    .lines()
                    .last()
                    .unwrap_or("未知错误")
            )))
        }
        Err(_) => Err(Error::from(
            "找不到 FFmpeg。发布包应包含 LGPL FFmpeg，开发环境请安装 ffmpeg 并加入 PATH",
        )),
    }
}

pub(crate) fn ffmpeg_path() -> PathBuf {
    let (folder, filename) = if cfg!(windows) {
        ("windows-x64", "ffmpeg.exe")
    } else {
        ("macos-universal", "ffmpeg")
    };
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            let candidates = [
                parent.join("resources/ffmpeg").join(folder).join(filename),
                parent
                    .join("../Resources/resources/ffmpeg")
                    .join(folder)
                    .join(filename),
                parent
                    .join("../Resources/ffmpeg")
                    .join(folder)
                    .join(filename),
                parent.join(filename),
            ];
            for candidate in candidates {
                if candidate.exists() {
                    return candidate;
                }
            }
        }
    }
    PathBuf::from(filename)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::tags;

    /// 端到端验证普通音频转 MP3：未加密 OGG → MP3，标签随转码保留，之后能内嵌封面。
    /// 需要本机 PATH 中有 ffmpeg，默认忽略：`cargo test -- --ignored`。
    #[test]
    #[ignore]
    fn ogg_transcodes_to_mp3_and_accepts_cover() {
        let dir = std::env::temp_dir().join(format!("qmunlock-ogg-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        let ogg = dir.join("测试歌曲.ogg");
        // 打包的精简 FFmpeg 没有 lavfi / libvorbis，测试素材用系统 ffmpeg 生成；
        // 转码本身仍走 ffmpeg_path()，与发布包一致
        let made = Command::new("ffmpeg")
            .args(["-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3"])
            .args(["-ac", "2", "-codec:a", "vorbis", "-strict", "-2"])
            .args(["-metadata", "title=测试歌曲"])
            .args(["-metadata", "artist=测试歌手"])
            .arg(&ogg)
            .output()
            .unwrap();
        assert!(
            made.status.success(),
            "{}",
            String::from_utf8_lossy(&made.stderr)
        );

        let mp3 = available_path(&dir, "测试歌曲", "mp3");
        convert_to_mp3(&ogg, &mp3).unwrap();
        assert!(ogg.exists(), "源 OGG 不能被删除或覆盖");
        let found = tags::read_embedded_tags(&mp3).expect("转码后应带 ID3 标签");
        assert_eq!(found.title, "测试歌曲");
        assert_eq!(found.artist, "测试歌手");

        // 最小 JPEG 头即可：只验证 APIC 帧能写入转码产物
        let image = [
            0xFF, 0xD8, 0xFF, 0xE0, 0, 0x10, b'J', b'F', b'I', b'F', 0, 0xFF, 0xD9,
        ];
        let meta = tags::SongMeta {
            album_mid: String::new(),
            album: "测试专辑".into(),
            album_singers: String::new(),
            title: "测试歌曲".into(),
            singers: "测试歌手".into(),
            release_date: String::new(),
            track_number: None,
            disc_number: None,
            song_mid: String::new(),
        };
        tags::embed_cover_into_mp3(&mp3, &image, "测试歌曲 - 测试歌手", &meta).unwrap();
        let tag = id3::Tag::read_from_path(&mp3).unwrap();
        assert_eq!(tag.pictures().count(), 1);

        // 第二次转码不覆盖已有 MP3
        assert_eq!(
            available_path(&dir, "测试歌曲", "mp3"),
            dir.join("测试歌曲 (1).mp3")
        );
        let _ = fs::remove_dir_all(&dir);
    }
}
