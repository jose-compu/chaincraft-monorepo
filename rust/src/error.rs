//! Error classes.
//!
//! Parity is of error *class*, not of message text: where Python raises
//! `CanonicalError`, this returns `Err(Error::Canonical(_))`.

use thiserror::Error;

#[derive(Debug, Error)]
pub enum Error {
    #[error("{0}")]
    Canonical(String),
    #[error("{0}")]
    Protocol(String),
    #[error("{0}")]
    Framing(String),
}

impl Error {
    pub fn canonical(message: impl Into<String>) -> Self {
        Self::Canonical(message.into())
    }

    pub fn protocol(message: impl Into<String>) -> Self {
        Self::Protocol(message.into())
    }

    pub fn framing(message: impl Into<String>) -> Self {
        Self::Framing(message.into())
    }

    pub fn is_canonical(&self) -> bool {
        matches!(self, Self::Canonical(_))
    }

    pub fn is_protocol(&self) -> bool {
        matches!(self, Self::Protocol(_))
    }

    pub fn is_framing(&self) -> bool {
        matches!(self, Self::Framing(_))
    }
}

pub type Result<T> = std::result::Result<T, Error>;
