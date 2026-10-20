//! Two meshes exchange one envelope on the optional UDP listener.

use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use chaincraft::canonical::JsonValue;
use chaincraft::mesh::Mesh;

#[test]
fn udp_listener_delivers_gossip() {
    let left = Mesh::bind("127.0.0.1:0").unwrap();
    let right = Mesh::bind("127.0.0.1:0").unwrap();
    let seen = Arc::new(Mutex::new(Vec::new()));
    {
        let mut guard = right.lock().unwrap();
        let seen = Arc::clone(&seen);
        guard.set_on_app(Arc::new(move |_type_name, data| {
            if let JsonValue::Object(map) = data {
                if let Some(JsonValue::String(text)) = map.get("message") {
                    seen.lock().unwrap().push(text.clone());
                }
            }
        }));
    }
    let port = Mesh::bind_udp(&right).unwrap();
    Mesh::bind_udp(&left).unwrap();
    Mesh::connect(&left, &format!("udp://{port}")).unwrap();
    Mesh::broadcast(
        &left,
        "app.hello",
        JsonValue::object([("message".into(), JsonValue::String("hi".into()))]),
    )
    .unwrap();
    let deadline = std::time::Instant::now() + Duration::from_secs(3);
    while seen.lock().unwrap().is_empty() && std::time::Instant::now() < deadline {
        thread::sleep(Duration::from_millis(50));
    }
    assert_eq!(seen.lock().unwrap().as_slice(), ["hi"]);
}
