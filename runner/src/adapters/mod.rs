#[cfg(feature = "pr2348")]
mod tk_train_pr2348;
pub mod tk_train_v1;

#[cfg(feature = "pr2348")]
use tk_train_pr2348::normalize_bytes;
#[cfg(not(feature = "pr2348"))]
use tk_train_v1::normalize_bytes;
