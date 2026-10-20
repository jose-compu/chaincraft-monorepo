//! Live PeerJS id from the public broker. Not a golden vector.

#[test]
fn live_peerjs_id() {
    let output = std::process::Command::new("curl")
        .args([
            "-fsS",
            "--max-time",
            "20",
            "https://dechess-org-peerjs.vercel.app/peerjs/id",
        ])
        .output()
        .expect("curl");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let body = String::from_utf8(output.stdout).expect("utf-8");
    let id = chaincraft::peer::parse_peer_id_body(&body).expect("peer id");
    let parsed = chaincraft::channel::parse_address(&format!("webrtc:{id}"));
    assert!(parsed.ok, "{}", parsed.canonical);
    let options = chaincraft::peer::peer_options(chaincraft::peer::DEFAULT_PEER_ORIGIN).unwrap();
    assert_eq!(options.host, "dechess-org-peerjs.vercel.app");
    assert_eq!(options.port, 443);
    assert!(options.secure);
    assert_eq!(options.key, "peerjs");
}
