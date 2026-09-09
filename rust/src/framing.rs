//! Framing and transport — SPEC/wire-v1.md §4.

use crate::error::{Error, Result};

pub const MAX_FRAME_BYTES: u32 = 16_777_216; // 16 MiB
pub const MAX_UDP_BYTES: usize = 65_507;

/// Prefix a body with its big-endian u32 length — §4.1.
pub fn encode_frame(body: &[u8]) -> Result<Vec<u8>> {
    if body.is_empty() {
        return Err(Error::framing("zero-length frame is invalid"));
    }
    if body.len() as u64 > MAX_FRAME_BYTES as u64 {
        return Err(Error::framing(format!(
            "frame of {} bytes exceeds {MAX_FRAME_BYTES}",
            body.len()
        )));
    }
    let mut out = Vec::with_capacity(4 + body.len());
    out.extend_from_slice(&(body.len() as u32).to_be_bytes());
    out.extend_from_slice(body);
    Ok(out)
}

/// One envelope per datagram, no length prefix — §4.2.
pub fn encode_datagram(body: &[u8]) -> Result<Vec<u8>> {
    check_datagram(body.len())?;
    Ok(body.to_vec())
}

pub fn decode_datagram(data: &[u8]) -> Result<Vec<u8>> {
    check_datagram(data.len())?;
    Ok(data.to_vec())
}

fn check_datagram(length: usize) -> Result<()> {
    if length == 0 {
        return Err(Error::framing("zero-length datagram is invalid"));
    }
    if length > MAX_UDP_BYTES {
        return Err(Error::framing(format!(
            "datagram of {length} bytes exceeds {MAX_UDP_BYTES}"
        )));
    }
    Ok(())
}

/// Reassembles frames from an arbitrarily chunked byte stream.
pub struct FrameReader {
    buffer: Vec<u8>,
    pub max_frame_bytes: u32,
}

impl FrameReader {
    pub fn new() -> Self {
        Self::with_max(MAX_FRAME_BYTES)
    }

    pub fn with_max(max_frame_bytes: u32) -> Self {
        Self {
            buffer: Vec::new(),
            max_frame_bytes,
        }
    }

    /// Append a chunk and return every frame that is now complete.
    pub fn feed(&mut self, chunk: &[u8]) -> Result<Vec<Vec<u8>>> {
        if !chunk.is_empty() {
            self.buffer.extend_from_slice(chunk);
        }
        let mut frames = Vec::new();
        loop {
            if self.buffer.len() < 4 {
                break;
            }
            let length = u32::from_be_bytes(self.buffer[0..4].try_into().unwrap());
            if length == 0 {
                return Err(Error::framing("zero-length frame is invalid"));
            }
            if length > self.max_frame_bytes {
                return Err(Error::framing(format!(
                    "declared length {length} exceeds {}",
                    self.max_frame_bytes
                )));
            }
            let total = 4 + length as usize;
            if self.buffer.len() < total {
                break;
            }
            frames.push(self.buffer[4..total].to_vec());
            self.buffer.drain(..total);
        }
        Ok(frames)
    }

    pub fn pending(&self) -> usize {
        self.buffer.len()
    }
}

impl Default for FrameReader {
    fn default() -> Self {
        Self::new()
    }
}
