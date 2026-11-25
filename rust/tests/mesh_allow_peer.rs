//! Three meshes: the hub records the first gossip peer and blocks the rest.

use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use chaincraft::canonical::JsonValue;
use chaincraft::mesh::Mesh;

#[test]
fn three_node_allow_peer_blocks_late_gossip() {
    let first = Arc::new(Mutex::new(None::<String>));
    let gate = Arc::clone(&first);
    let got_b = Arc::new(Mutex::new(0usize));
    let b = Mesh::bind("127.0.0.1:0").unwrap();
    {
        let mut guard = b.lock().unwrap();
        guard.set_allow_peer(Arc::new(move |addr| {
            let mut slot = gate.lock().unwrap();
            if slot.is_none() {
                *slot = Some(addr.to_string());
                return true;
            }
            slot.as_deref() == Some(addr)
        }));
        let got_cb = Arc::clone(&got_b);
        guard.set_on_app(Arc::new(move |_type_name, _data| {
            *got_cb.lock().unwrap() += 1;
        }));
    }
    let a = Mesh::bind("127.0.0.1:0").unwrap();
    let c = Mesh::bind("127.0.0.1:0").unwrap();
    let addr_b = b.lock().unwrap().listen_addr().to_string();
    Mesh::connect(&a, &addr_b).unwrap();
    Mesh::connect(&c, &addr_b).unwrap();
    Mesh::broadcast(
        &a,
        "app.warm",
        JsonValue::object([("n".into(), JsonValue::Number(0))]),
    )
    .unwrap();
    let deadline = std::time::Instant::now() + Duration::from_secs(2);
    while first.lock().unwrap().is_none() && std::time::Instant::now() < deadline {
        thread::sleep(Duration::from_millis(50));
    }
    assert!(first.lock().unwrap().is_some(), "first gossip peer");
    *got_b.lock().unwrap() = 0;
    let digest = Mesh::broadcast(
        &c,
        "app.blocked",
        JsonValue::object([("n".into(), JsonValue::Number(1))]),
    )
    .unwrap();
    let deadline = std::time::Instant::now() + Duration::from_secs(2);
    while std::time::Instant::now() < deadline {
        thread::sleep(Duration::from_millis(50));
    }
    assert_eq!(*got_b.lock().unwrap(), 0);
    assert!(!b.lock().unwrap().ids().iter().any(|item| item == &digest));
    assert!(c.lock().unwrap().ids().iter().any(|item| item == &digest));
}
