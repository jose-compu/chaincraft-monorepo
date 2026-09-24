//! In-process pipe mesh — SPEC/features/channel-adapters.md.

use std::time::Instant;

use chaincraft_core::adapters::{AdapterBus, AdapterChannel};

#[test]
fn pipe_mesh_throughput() {
    let peers_n = 4;
    let burst = 65_536;
    let payload = "ab".repeat(64);
    let bus = AdapterBus::pipe();
    let names: Vec<String> = (0..peers_n).map(|index| format!("pipe:n{index}")).collect();
    let mut peers: Vec<AdapterChannel> = (0..peers_n).map(|_| AdapterChannel::new(&bus)).collect();
    for (peer, name) in peers.iter_mut().zip(names.iter()) {
        assert!(peer.listen(name));
    }
    let started = Instant::now();
    for index in 0..burst {
        let src = index % peers_n;
        let dst = (src + 1) % peers_n;
        assert!(peers[src].send(&names[dst], &payload));
    }
    let elapsed = started.elapsed().as_secs_f64();
    for peer in &peers {
        let got = peer.recv();
        assert_eq!(got.len(), burst / peers_n);
        assert_eq!(got[0].data, payload);
        assert!(got[0].from.starts_with("pipe:n"));
    }
    let rate = burst as f64 / elapsed;
    println!("channel.pipe apply: {burst} events in {elapsed:.6}s ({rate:.0}/s)");
    assert!(elapsed < 30.0, "{elapsed}");
}
