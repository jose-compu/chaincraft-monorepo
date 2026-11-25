//! Three meshes: hub `allow_peer` rejects only the sender's gossip.

use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use chaincraft::canonical::JsonValue;
use chaincraft::mesh::Mesh;

#[test]
fn three_node_allow_peer_blocks_sender_only() {
    let sender = Arc::new(Mutex::new(None::<String>));
    let gate = Arc::clone(&sender);
    let got_b = Arc::new(Mutex::new(Vec::<String>::new()));
    let b = Mesh::bind("127.0.0.1:0").unwrap();
    {
        let mut guard = b.lock().unwrap();
        guard.set_allow_peer(Arc::new(move |addr| {
            let locked = gate.lock().unwrap();
            locked.as_deref() != Some(addr)
        }));
        let got_cb = Arc::clone(&got_b);
        guard.set_on_app(Arc::new(move |type_name, _data| {
            got_cb.lock().unwrap().push(type_name.to_string());
        }));
    }
    let a = Mesh::bind("127.0.0.1:0").unwrap();
    let c = Mesh::bind("127.0.0.1:0").unwrap();
    let addr_b = b.lock().unwrap().listen_addr().to_string();
    Mesh::connect(&a, &addr_b).unwrap();
    let deadline = std::time::Instant::now() + Duration::from_secs(2);
    while b.lock().unwrap().peer_addrs().is_empty() && std::time::Instant::now() < deadline {
        thread::sleep(Duration::from_millis(50));
    }
    assert!(!b.lock().unwrap().peer_addrs().is_empty());
    *sender.lock().unwrap() = Some(b.lock().unwrap().peer_addrs()[0].clone());
    Mesh::connect(&c, &addr_b).unwrap();

    let blocked = Mesh::broadcast(
        &a,
        "app.blocked",
        JsonValue::object([("n".into(), JsonValue::Number(0))]),
    )
    .unwrap();
    let deadline = std::time::Instant::now() + Duration::from_secs(2);
    while std::time::Instant::now() < deadline {
        thread::sleep(Duration::from_millis(50));
    }
    assert!(got_b.lock().unwrap().is_empty());
    assert!(!b.lock().unwrap().ids().iter().any(|item| item == &blocked));
    assert!(!c.lock().unwrap().ids().iter().any(|item| item == &blocked));

    got_b.lock().unwrap().clear();
    let allowed = Mesh::broadcast(
        &c,
        "app.ok",
        JsonValue::object([("n".into(), JsonValue::Number(1))]),
    )
    .unwrap();
    let deadline = std::time::Instant::now() + Duration::from_secs(2);
    while !b.lock().unwrap().ids().iter().any(|item| item == &allowed)
        && std::time::Instant::now() < deadline
    {
        thread::sleep(Duration::from_millis(50));
    }
    assert_eq!(&*got_b.lock().unwrap(), &["app.ok"]);
    assert!(b.lock().unwrap().ids().iter().any(|item| item == &allowed));
    assert!(c.lock().unwrap().ids().iter().any(|item| item == &allowed));
}
