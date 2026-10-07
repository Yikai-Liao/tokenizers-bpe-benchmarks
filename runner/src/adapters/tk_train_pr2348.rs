//! PR #2348 predates the current Normalizer offset parameter.
use crate::protocol::Error;
use tk_encode::pipeline::Normalizer;

pub(super) fn normalize_bytes(piece: &str) -> Result<String, Error> {
    tk_encode::normalizers::byte_level::ByteLevel::new()
        .normalize(piece)
        .map(|text| text.into_owned())
}
