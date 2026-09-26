//! Apply and read throughput for app.stream — SPEC/features/app-stream.md.

use std::time::Instant;

use chaincraft::object::ApplicationObject;
use chaincraft::stream::{Stream, MAX_BATCH};
use chaincraft::{JsonValue, MAX_SAFE_INT};

const KEEP: i64 = 32;

fn message(pairs: Vec<(&str, JsonValue)>) -> JsonValue {
    JsonValue::object(
        pairs
            .into_iter()
            .map(|(key, value)| (key.to_owned(), value)),
    )
}

fn apply(obj: &mut Stream, message: &JsonValue) -> bool {
    if obj.is_valid(message) {
        obj.add_message(message, None);
        true
    } else {
        false
    }
}

fn ingest(obj: &mut Stream, burst: i64) -> f64 {
    let started = Instant::now();
    for partition in [0_i64, 1] {
        let mut seq = 0_i64;
        while seq < burst / 2 {
            let mut records = Vec::with_capacity(MAX_BATCH);
            for _ in 0..MAX_BATCH {
                records.push(JsonValue::object([
                    ("payload".into(), JsonValue::String("x".into())),
                    ("producer".into(), JsonValue::String("alice".into())),
                    ("seq".into(), JsonValue::Number(seq)),
                ]));
                seq += 1;
            }
            assert!(apply(
                obj,
                &message(vec![
                    ("app", JsonValue::String("stream".into())),
                    ("op", JsonValue::String("append".into())),
                    ("stream", JsonValue::String("orders".into())),
                    ("partition", JsonValue::Number(partition)),
                    ("records", JsonValue::Array(records)),
                ])
            ));
        }
    }
    started.elapsed().as_secs_f64()
}

fn prepared() -> Stream {
    let mut obj = Stream::new();
    for broker in ["n1", "n2"] {
        assert!(apply(
            &mut obj,
            &message(vec![
                ("app", JsonValue::String("stream".into())),
                ("op", JsonValue::String("join".into())),
                ("stream", JsonValue::String("orders".into())),
                ("broker", JsonValue::String(broker.into())),
            ])
        ));
    }
    for partition in [0_i64, 1] {
        assert!(apply(
            &mut obj,
            &message(vec![
                ("app", JsonValue::String("stream".into())),
                ("op", JsonValue::String("open".into())),
                ("stream", JsonValue::String("orders".into())),
                ("partition", JsonValue::Number(partition)),
                ("producer", JsonValue::String("alice".into())),
            ])
        ));
    }
    assert!(apply(
        &mut obj,
        &message(vec![
            ("app", JsonValue::String("stream".into())),
            ("op", JsonValue::String("retain".into())),
            ("stream", JsonValue::String("orders".into())),
            ("keep", JsonValue::Number(KEEP)),
        ])
    ));
    obj
}

#[test]
fn stream_apply_and_read_throughput() {
    let burst = 65_536_i64;
    let mut obj = prepared();
    let elapsed = ingest(&mut obj, burst);
    let rate = if elapsed == 0.0 {
        burst as f64
    } else {
        burst as f64 / elapsed
    };
    println!("app.stream apply: {burst} events in {elapsed:.6}s ({rate:.0}/s)");
    assert!(elapsed < 30.0, "{elapsed}");

    assert!(apply(
        &mut obj,
        &message(vec![
            ("app", JsonValue::String("stream".into())),
            ("op", JsonValue::String("fail".into())),
            ("stream", JsonValue::String("orders".into())),
            ("broker", JsonValue::String("n2".into())),
        ])
    ));
    let head = obj.read(
        "orders",
        &JsonValue::Number(0),
        &JsonValue::Null,
        &JsonValue::Number(KEEP),
    );
    assert_eq!(head.len(), KEEP as usize);
    assert!(apply(
        &mut obj,
        &message(vec![
            ("app", JsonValue::String("stream".into())),
            ("op", JsonValue::String("fail".into())),
            ("stream", JsonValue::String("orders".into())),
            ("broker", JsonValue::String("n1".into())),
        ])
    ));
    assert!(obj
        .read(
            "orders",
            &JsonValue::Number(0),
            &JsonValue::Null,
            &JsonValue::Number(4)
        )
        .is_empty());

    assert!(apply(
        &mut obj,
        &message(vec![
            ("app", JsonValue::String("stream".into())),
            ("op", JsonValue::String("join".into())),
            ("stream", JsonValue::String("orders".into())),
            ("broker", JsonValue::String("n1".into())),
        ])
    ));
    let read_started = Instant::now();
    let reads = 200usize;
    for _ in 0..reads {
        assert_eq!(
            obj.read(
                "orders",
                &JsonValue::Number(1),
                &JsonValue::Null,
                &JsonValue::Number(KEEP)
            )
            .len(),
            KEEP as usize
        );
    }
    let read_elapsed = read_started.elapsed().as_secs_f64();
    let read_rate = if read_elapsed == 0.0 {
        reads as f64
    } else {
        reads as f64 / read_elapsed
    };
    println!("app.stream read: {reads} reads in {read_elapsed:.6}s ({read_rate:.0}/s)");

    let mut sparse = Stream::new();
    assert!(apply(
        &mut sparse,
        &message(vec![
            ("app", JsonValue::String("stream".into())),
            ("op", JsonValue::String("open".into())),
            ("stream", JsonValue::String("orders".into())),
            ("producer", JsonValue::String("alice".into())),
        ])
    ));
    assert!(apply(
        &mut sparse,
        &message(vec![
            ("app", JsonValue::String("stream".into())),
            ("op", JsonValue::String("produce".into())),
            ("stream", JsonValue::String("orders".into())),
            ("producer", JsonValue::String("alice".into())),
            ("seq", JsonValue::Number(MAX_SAFE_INT)),
            ("payload", JsonValue::String("z".into())),
        ])
    ));
    let reject_started = Instant::now();
    assert!(!sparse.is_valid(&message(vec![
        ("app", JsonValue::String("stream".into())),
        ("op", JsonValue::String("commit".into())),
        ("stream", JsonValue::String("orders".into())),
        ("group", JsonValue::String("workers".into())),
        ("producer", JsonValue::String("alice".into())),
        ("seq", JsonValue::Number(MAX_SAFE_INT)),
    ])));
    let reject_elapsed = reject_started.elapsed().as_secs_f64();
    println!("app.stream high-seq commit rejection: {reject_elapsed:.6}s");
    assert!(reject_elapsed < 1.0, "{reject_elapsed}");
}

#[test]
fn stream_release_million() {
    if cfg!(debug_assertions) {
        return;
    }
    let burst = 1_048_576_i64;
    let mut obj = prepared();
    let build_started = Instant::now();
    let mut batches = Vec::new();
    for partition in [0_i64, 1] {
        let mut seq = 0_i64;
        while seq < burst / 2 {
            let mut records = Vec::with_capacity(MAX_BATCH);
            for _ in 0..MAX_BATCH {
                records.push(JsonValue::object([
                    ("payload".into(), JsonValue::String("x".into())),
                    ("producer".into(), JsonValue::String("alice".into())),
                    ("seq".into(), JsonValue::Number(seq)),
                ]));
                seq += 1;
            }
            batches.push(message(vec![
                ("app", JsonValue::String("stream".into())),
                ("op", JsonValue::String("append".into())),
                ("stream", JsonValue::String("orders".into())),
                ("partition", JsonValue::Number(partition)),
                ("records", JsonValue::Array(records)),
            ]));
        }
    }
    let built = build_started.elapsed().as_secs_f64();
    let started = Instant::now();
    for batch in &batches {
        assert!(apply(&mut obj, batch));
    }
    let elapsed = started.elapsed().as_secs_f64();
    let rate = burst as f64 / elapsed;
    println!(
        "app.stream release apply: {burst} events in {elapsed:.6}s ({rate:.0}/s); build {built:.6}s"
    );
    assert!(elapsed < 30.0, "{elapsed}");
    assert!(rate >= 1_000_000.0, "{rate}");
}
