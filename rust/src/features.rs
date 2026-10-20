//! Feature manifest — the IDs this implementation claims to provide.

pub const VERSION: &str = "1.2.0";
pub const WIRE_VERSION: i64 = 1;
pub const LANGUAGE: &str = "rust";
pub const IMPL: &str = "rust-chaincraft/1.2.0";

pub const FEATURES: &[&str] = &[
    "wire.canonical-json",
    "wire.payload-digest",
    "wire.envelope",
    "wire.framing-tcp",
    "wire.framing-udp",
    "wire.control",
    "wire.version-negotiation",
    "wire.sig-schnorr",
    "wire.sig-ed25519",
    "wire.dedup",
    "wire.paths",
    "object.contract",
    "object.pipeline",
    "object.memento",
    "object.merkle-digest",
    "object.tiebreak",
    "crypto.ecdsa",
    "crypto.vdf",
    "crypto.vrf",
    "discovery.peer",
    "discovery.local",
    "discovery.nat",
    "consensus.pow",
    "consensus.pos",
    "consensus.pbft",
    "ledger.balance",
    "ledger.utxo",
    "mempool.basic",
    "fees.policy",
    "storage.persistent",
    "cli.node",
    "bittorrent.swarm",
    "wire.channel",
    "channel.udp",
    "channel.mailto",
    "channel.webrtc",
    "channel.peer",
    "channel.forum",
    "channel.pipe",
    "app.pubsub",
    "app.stream",
];

/// JSON on stdout for `tools/parity_check.py`. Nothing else may reach stdout.
pub fn manifest_json() -> String {
    let mut features: Vec<&str> = FEATURES.to_vec();
    features.sort_unstable();
    let list = features
        .iter()
        .map(|f| format!("    \"{f}\""))
        .collect::<Vec<_>>()
        .join(",\n");
    format!(
        "{{\n  \"impl\": \"{IMPL}\",\n  \"language\": \"{LANGUAGE}\",\n  \"version\": \"{VERSION}\",\n  \"wire_version\": {WIRE_VERSION},\n  \"features\": [\n{list}\n  ]\n}}\n"
    )
}
