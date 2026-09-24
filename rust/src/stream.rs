//! Append-only event log — SPEC/features/app-stream.md.

use std::collections::{BTreeMap, BTreeSet};

use crate::canonical::{JsonValue, MAX_SAFE_INT};
use crate::object::Protocol;

pub const MAX_STREAMS: usize = 32;
pub const MAX_PARTITIONS: usize = 16;
pub const MAX_PRODUCERS: usize = 32;
pub const MAX_EVENTS: usize = 64;
pub const MAX_GROUPS: usize = 32;
pub const MAX_BROKERS: usize = 8;
pub const MAX_BATCH: usize = 64;
pub const MAX_PAYLOAD: usize = 4096;
pub const MAX_READ: usize = 256;

#[derive(Clone)]
struct Stored {
    producer: String,
    seq: i64,
    payload: String,
}

struct Partition {
    producers: BTreeSet<String>,
    events: Vec<Stored>,
    groups: BTreeMap<String, BTreeMap<String, i64>>,
    trimmed: BTreeMap<String, i64>,
}

impl Partition {
    fn new() -> Self {
        Self {
            producers: BTreeSet::new(),
            events: Vec::new(),
            groups: BTreeMap::new(),
            trimmed: BTreeMap::new(),
        }
    }
}

struct Log {
    retention: usize,
    brokers: BTreeMap<String, bool>,
    partitions: BTreeMap<i64, Partition>,
}

impl Log {
    fn new() -> Self {
        Self {
            retention: MAX_EVENTS,
            brokers: BTreeMap::new(),
            partitions: BTreeMap::new(),
        }
    }

    fn available(&self) -> bool {
        self.brokers.is_empty() || self.brokers.values().any(|up| *up)
    }
}

struct Record {
    producer: String,
    seq: i64,
    payload: String,
}

struct View<'a> {
    producer: &'a str,
    seq: i64,
    payload: &'a str,
}

trait Row {
    fn producer(&self) -> &str;
    fn seq(&self) -> i64;
    fn payload(&self) -> &str;
}

impl Row for Record {
    fn producer(&self) -> &str {
        &self.producer
    }
    fn seq(&self) -> i64 {
        self.seq
    }
    fn payload(&self) -> &str {
        &self.payload
    }
}

impl Row for View<'_> {
    fn producer(&self) -> &str {
        self.producer
    }
    fn seq(&self) -> i64 {
        self.seq
    }
    fn payload(&self) -> &str {
        self.payload
    }
}

pub struct Stream {
    streams: BTreeMap<String, Log>,
}

impl Stream {
    pub fn new() -> Self {
        Self {
            streams: BTreeMap::new(),
        }
    }

    pub fn state_value(&self) -> JsonValue {
        JsonValue::object([("streams".into(), JsonValue::Array(self.stream_list()))])
    }

    pub fn read(
        &self,
        stream: &str,
        partition: &JsonValue,
        after: &JsonValue,
        limit: &JsonValue,
    ) -> Vec<JsonValue> {
        let Some(pid) = partition_id(Some(partition)) else {
            return Vec::new();
        };
        let Some(n) = limit_of(limit) else {
            return Vec::new();
        };
        let Some(log) = self.streams.get(stream) else {
            return Vec::new();
        };
        if !log.available() {
            return Vec::new();
        }
        let Some(part) = log.partitions.get(&pid) else {
            return Vec::new();
        };
        let cursor = match cursor_of(after) {
            Cursor::Start => None,
            Cursor::At(seq, producer) => Some((seq, producer)),
            Cursor::Bad => return Vec::new(),
        };
        let mut events = event_values(&part.events);
        if let Some((seq, producer)) = cursor {
            events.retain(|event| {
                let obj = event.as_object().expect("event object");
                let eseq = obj.get("seq").and_then(JsonValue::as_i64).expect("seq");
                let eprod = obj
                    .get("producer")
                    .and_then(JsonValue::as_str)
                    .expect("producer");
                (eseq, eprod) > (seq, producer.as_str())
            });
        }
        events.truncate(n);
        events
    }

    fn stream_list(&self) -> Vec<JsonValue> {
        self.streams
            .iter()
            .map(|(name, log)| {
                let partitions = log
                    .partitions
                    .iter()
                    .map(|(pid, part)| partition_value(*pid, part))
                    .collect();
                let replicas = log
                    .brokers
                    .iter()
                    .map(|(broker, up)| {
                        JsonValue::object([
                            ("broker".into(), JsonValue::String(broker.clone())),
                            (
                                "status".into(),
                                JsonValue::String(if *up { "up" } else { "down" }.into()),
                            ),
                        ])
                    })
                    .collect();
                JsonValue::object([
                    ("name".into(), JsonValue::String(name.clone())),
                    ("retention".into(), JsonValue::Number(log.retention as i64)),
                    ("replicas".into(), JsonValue::Array(replicas)),
                    ("partitions".into(), JsonValue::Array(partitions)),
                ])
            })
            .collect()
    }

    fn parse(&self, message: &JsonValue) -> Option<Op> {
        let obj = message.as_object()?;
        if obj.get("app")?.as_str()? != "stream" {
            return None;
        }
        let op = obj.get("op")?.as_str()?;
        let stream = obj.get("stream")?.as_str()?;
        if !valid_name(stream) {
            return None;
        }
        match op {
            "open" | "produce" | "append" | "commit" => {
                self.parse_data(obj, op, stream, partition_id(obj.get("partition"))?)
            }
            "join" => self.parse_join(stream, obj.get("broker")?.as_str()?),
            "fail" => self.parse_fail(stream, obj.get("broker")?.as_str()?),
            "retain" => self.parse_retain(stream, obj.get("keep")?),
            _ => None,
        }
    }

    fn parse_data(
        &self,
        obj: &BTreeMap<String, JsonValue>,
        op: &str,
        stream: &str,
        partition: i64,
    ) -> Option<Op> {
        let log = self.streams.get(stream);
        if log.is_some() && !log.unwrap().available() {
            return None;
        }
        if op == "open" {
            let producer = obj.get("producer")?.as_str()?;
            if !valid_name(producer) {
                return None;
            }
            if log.is_none() && self.streams.len() >= MAX_STREAMS {
                return None;
            }
            let part = log.and_then(|item| item.partitions.get(&partition));
            if log.is_some() && part.is_none() && log.unwrap().partitions.len() >= MAX_PARTITIONS {
                return None;
            }
            if let Some(existing) = part {
                if !existing.producers.contains(producer)
                    && existing.producers.len() >= MAX_PRODUCERS
                {
                    return None;
                }
            }
            return Some(Op::Open {
                stream: stream.to_owned(),
                partition,
                producer: producer.to_owned(),
            });
        }
        let log = log?;
        let part = log.partitions.get(&partition)?;
        if op == "commit" {
            let group = obj.get("group")?.as_str()?;
            let producer = obj.get("producer")?.as_str()?;
            let seq = obj.get("seq")?.as_i64()?;
            if !valid_name(group) || !valid_name(producer) {
                return None;
            }
            if !(0..=MAX_SAFE_INT).contains(&seq) || !part.producers.contains(producer) {
                return None;
            }
            if !prefix_closed(&part.events, &part.trimmed, producer, seq) {
                return None;
            }
            if !part.groups.contains_key(group) && part.groups.len() >= MAX_GROUPS {
                return None;
            }
            return Some(Op::Commit {
                stream: stream.to_owned(),
                partition,
                group: group.to_owned(),
                producer: producer.to_owned(),
                seq,
            });
        }
        let records = records_of(obj, op)?;
        if !records_ok(
            &part.events,
            &part.trimmed,
            &part.producers,
            log.retention,
            &records,
        ) {
            return None;
        }
        Some(Op::Write {
            stream: stream.to_owned(),
            partition,
            records,
        })
    }

    fn append_ok(
        &self,
        obj: &BTreeMap<String, JsonValue>,
        op: &str,
        stream: &str,
        partition: i64,
    ) -> bool {
        let Some(log) = self.streams.get(stream) else {
            return false;
        };
        if !log.available() {
            return false;
        }
        let Some(part) = log.partitions.get(&partition) else {
            return false;
        };
        let Some(records) = views_of(obj, op) else {
            return false;
        };
        records_ok(
            &part.events,
            &part.trimmed,
            &part.producers,
            log.retention,
            &records,
        )
    }

    fn parse_join(&self, stream: &str, broker: &str) -> Option<Op> {
        if !valid_name(broker) {
            return None;
        }
        match self.streams.get(stream) {
            None if self.streams.len() >= MAX_STREAMS => None,
            Some(log) if !log.brokers.contains_key(broker) && log.brokers.len() >= MAX_BROKERS => {
                None
            }
            _ => Some(Op::Join {
                stream: stream.to_owned(),
                broker: broker.to_owned(),
            }),
        }
    }

    fn parse_fail(&self, stream: &str, broker: &str) -> Option<Op> {
        if !valid_name(broker) {
            return None;
        }
        let log = self.streams.get(stream)?;
        if !log.brokers.contains_key(broker) {
            return None;
        }
        Some(Op::Fail {
            stream: stream.to_owned(),
            broker: broker.to_owned(),
        })
    }

    fn parse_retain(&self, stream: &str, keep: &JsonValue) -> Option<Op> {
        let keep = keep.as_i64()?;
        if !(1..=MAX_EVENTS as i64).contains(&keep) || !self.streams.contains_key(stream) {
            return None;
        }
        Some(Op::Retain {
            stream: stream.to_owned(),
            keep: keep as usize,
        })
    }
}

impl Default for Stream {
    fn default() -> Self {
        Self::new()
    }
}

enum Op {
    Open {
        stream: String,
        partition: i64,
        producer: String,
    },
    Write {
        stream: String,
        partition: i64,
        records: Vec<Record>,
    },
    Commit {
        stream: String,
        partition: i64,
        group: String,
        producer: String,
        seq: i64,
    },
    Join {
        stream: String,
        broker: String,
    },
    Fail {
        stream: String,
        broker: String,
    },
    Retain {
        stream: String,
        keep: usize,
    },
}

enum Cursor {
    Start,
    At(i64, String),
    Bad,
}

fn valid_name(value: &str) -> bool {
    (1..=64).contains(&value.len())
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
}

fn partition_id(value: Option<&JsonValue>) -> Option<i64> {
    let Some(value) = value else {
        return Some(0);
    };
    let id = value.as_i64()?;
    if (0..MAX_PARTITIONS as i64).contains(&id) {
        Some(id)
    } else {
        None
    }
}

fn limit_of(value: &JsonValue) -> Option<usize> {
    let n = value.as_i64()?;
    if (1..=MAX_READ as i64).contains(&n) {
        Some(n as usize)
    } else {
        None
    }
}

fn cursor_of(after: &JsonValue) -> Cursor {
    if matches!(after, JsonValue::Null) {
        return Cursor::Start;
    }
    let Some(obj) = after.as_object() else {
        return Cursor::Bad;
    };
    let Some(producer) = obj.get("producer").and_then(JsonValue::as_str) else {
        return Cursor::Bad;
    };
    let Some(seq) = obj.get("seq").and_then(JsonValue::as_i64) else {
        return Cursor::Bad;
    };
    if !valid_name(producer) || !(0..=MAX_SAFE_INT).contains(&seq) {
        return Cursor::Bad;
    }
    Cursor::At(seq, producer.to_owned())
}

fn view_of<'a>(
    producer: Option<&'a str>,
    seq: Option<i64>,
    payload: Option<&'a str>,
) -> Option<View<'a>> {
    let producer = producer?;
    let seq = seq?;
    let payload = payload?;
    if !valid_name(producer) || !(0..=MAX_SAFE_INT).contains(&seq) {
        return None;
    }
    let scalars = payload.chars().count();
    if !(1..=MAX_PAYLOAD).contains(&scalars) {
        return None;
    }
    Some(View {
        producer,
        seq,
        payload,
    })
}

fn one_record(producer: Option<&str>, seq: Option<i64>, payload: Option<&str>) -> Option<Record> {
    let view = view_of(producer, seq, payload)?;
    Some(Record {
        producer: view.producer.to_owned(),
        seq: view.seq,
        payload: view.payload.to_owned(),
    })
}

fn views_of<'a>(obj: &'a BTreeMap<String, JsonValue>, op: &str) -> Option<Vec<View<'a>>> {
    if op == "produce" {
        let record = view_of(
            obj.get("producer").and_then(JsonValue::as_str),
            obj.get("seq").and_then(JsonValue::as_i64),
            obj.get("payload").and_then(JsonValue::as_str),
        )?;
        return Some(vec![record]);
    }
    let raw = obj.get("records")?.as_array()?;
    if !(1..=MAX_BATCH).contains(&raw.len()) {
        return None;
    }
    let mut records = Vec::with_capacity(raw.len());
    for item in raw {
        let rec = item.as_object()?;
        records.push(view_of(
            rec.get("producer").and_then(JsonValue::as_str),
            rec.get("seq").and_then(JsonValue::as_i64),
            rec.get("payload").and_then(JsonValue::as_str),
        )?);
    }
    Some(records)
}

fn records_of(obj: &BTreeMap<String, JsonValue>, op: &str) -> Option<Vec<Record>> {
    if op == "produce" {
        let record = one_record(
            obj.get("producer").and_then(JsonValue::as_str),
            obj.get("seq").and_then(JsonValue::as_i64),
            obj.get("payload").and_then(JsonValue::as_str),
        )?;
        return Some(vec![record]);
    }
    let raw = obj.get("records")?.as_array()?;
    if !(1..=MAX_BATCH).contains(&raw.len()) {
        return None;
    }
    let mut records = Vec::with_capacity(raw.len());
    for item in raw {
        let rec = item.as_object()?;
        records.push(one_record(
            rec.get("producer").and_then(JsonValue::as_str),
            rec.get("seq").and_then(JsonValue::as_i64),
            rec.get("payload").and_then(JsonValue::as_str),
        )?);
    }
    Some(records)
}

fn drop_oldest(events: &mut Vec<Stored>, trimmed: &mut BTreeMap<String, i64>) {
    // Events stay sorted by (seq, producer), so the oldest record is first.
    let stored = events.remove(0);
    let mark = trimmed.get(&stored.producer).copied().unwrap_or(-1);
    if stored.seq == mark + 1 {
        trimmed.insert(stored.producer, stored.seq);
    }
}

fn trim_to(events: &mut Vec<Stored>, trimmed: &mut BTreeMap<String, i64>, keep: usize) {
    while events.len() > keep {
        drop_oldest(events, trimmed);
    }
}

fn records_ok<'a, R: Row>(
    events: &'a [Stored],
    trimmed: &'a BTreeMap<String, i64>,
    producers: &BTreeSet<String>,
    retention: usize,
    records: &'a [R],
) -> bool {
    // `events` stays sorted by (seq, producer). Dropping the oldest live
    // record only advances this index. `added` is the same order.
    let mut live_start = 0;
    let mut added: Vec<View<'a>> = Vec::new();
    let mut marks: Vec<(&'a str, i64)> = trimmed
        .iter()
        .map(|(name, seq)| (name.as_str(), *seq))
        .collect();
    let mut len = events.len();
    for record in records {
        if !producers.contains(record.producer()) {
            return false;
        }
        let mark = marks
            .iter()
            .find(|(name, _)| *name == record.producer())
            .map(|(_, seq)| *seq)
            .unwrap_or(-1);
        if record.seq() <= mark {
            return false;
        }
        let row = View {
            producer: record.producer(),
            seq: record.seq(),
            payload: record.payload(),
        };
        let live = &events[live_start..];
        let idx = live.partition_point(|event| {
            (event.seq, event.producer.as_str()) < (row.seq, row.producer)
        });
        if idx < live.len() && live[idx].seq == row.seq && live[idx].producer == row.producer {
            if live[idx].payload != row.payload {
                return false;
            }
            continue;
        }
        let aidx =
            added.partition_point(|item| (item.seq, item.producer) < (row.seq, row.producer));
        if aidx < added.len() && added[aidx].seq == row.seq && added[aidx].producer == row.producer
        {
            if added[aidx].payload != row.payload {
                return false;
            }
            continue;
        }
        if len >= MAX_EVENTS {
            return false;
        }
        added.insert(aidx, row);
        len += 1;
        while len > retention {
            let drop_added = match (events.get(live_start), added.first()) {
                (None, Some(_)) => true,
                (Some(event), Some(extra)) => {
                    (extra.seq, extra.producer) < (event.seq, event.producer.as_str())
                }
                (Some(_), None) => false,
                (None, None) => return false,
            };
            if drop_added {
                let pending = added.remove(0);
                note_mark(&mut marks, pending.producer, pending.seq);
            } else {
                let event = &events[live_start];
                let producer = event.producer.as_str();
                let seq = event.seq;
                live_start += 1;
                note_mark(&mut marks, producer, seq);
            }
            len -= 1;
        }
    }
    true
}

fn note_mark<'a>(marks: &mut Vec<(&'a str, i64)>, producer: &'a str, seq: i64) {
    let mark = marks
        .iter()
        .find(|(name, _)| *name == producer)
        .map(|(_, value)| *value)
        .unwrap_or(-1);
    if seq != mark + 1 {
        return;
    }
    if let Some(slot) = marks.iter_mut().find(|(name, _)| *name == producer) {
        slot.1 = seq;
    } else {
        marks.push((producer, seq));
    }
}

fn mutate_records(
    events: &mut Vec<Stored>,
    trimmed: &mut BTreeMap<String, i64>,
    producers: &BTreeSet<String>,
    retention: usize,
    records: Vec<Record>,
) -> bool {
    for record in records {
        if !producers.contains(&record.producer) {
            return false;
        }
        let mark = trimmed.get(&record.producer).copied().unwrap_or(-1);
        if record.seq <= mark {
            return false;
        }
        if let Some(prior) = events
            .iter()
            .find(|event| event.producer == record.producer && event.seq == record.seq)
        {
            if prior.payload != record.payload {
                return false;
            }
            continue;
        }
        if events.len() >= MAX_EVENTS {
            return false;
        }
        let stored = Stored {
            producer: record.producer,
            seq: record.seq,
            payload: record.payload,
        };
        let idx = events.partition_point(|event| {
            (event.seq, event.producer.as_str()) < (stored.seq, stored.producer.as_str())
        });
        events.insert(idx, stored);
        trim_to(events, trimmed, retention);
    }
    true
}

fn prefix_closed(
    events: &[Stored],
    trimmed: &BTreeMap<String, i64>,
    producer: &str,
    seq: i64,
) -> bool {
    // Count stored records. Walking mark+1..=seq hangs on a large sparse seq.
    if !events
        .iter()
        .any(|event| event.producer == producer && event.seq == seq)
    {
        return false;
    }
    let mark = trimmed.get(producer).copied().unwrap_or(-1);
    if seq <= mark {
        return false;
    }
    let found = events
        .iter()
        .filter(|event| event.producer == producer && event.seq > mark && event.seq <= seq)
        .count();
    let Some(need) = seq.checked_sub(mark) else {
        return false;
    };
    i64::try_from(found).ok() == Some(need)
}

fn event_values(events: &[Stored]) -> Vec<JsonValue> {
    events
        .iter()
        .map(|event| {
            JsonValue::object([
                ("producer".into(), JsonValue::String(event.producer.clone())),
                ("seq".into(), JsonValue::Number(event.seq)),
                ("payload".into(), JsonValue::String(event.payload.clone())),
            ])
        })
        .collect()
}

fn partition_value(pid: i64, part: &Partition) -> JsonValue {
    let groups = part
        .groups
        .iter()
        .map(|(group, cursors)| {
            JsonValue::object([
                ("name".into(), JsonValue::String(group.clone())),
                (
                    "cursors".into(),
                    JsonValue::Array(
                        cursors
                            .iter()
                            .map(|(producer, seq)| {
                                JsonValue::object([
                                    ("producer".into(), JsonValue::String(producer.clone())),
                                    ("seq".into(), JsonValue::Number(*seq)),
                                ])
                            })
                            .collect(),
                    ),
                ),
            ])
        })
        .collect();
    let trimmed = part
        .trimmed
        .iter()
        .map(|(producer, seq)| {
            JsonValue::object([
                ("producer".into(), JsonValue::String(producer.clone())),
                ("seq".into(), JsonValue::Number(*seq)),
            ])
        })
        .collect();
    JsonValue::object([
        ("partition".into(), JsonValue::Number(pid)),
        (
            "producers".into(),
            JsonValue::Array(
                part.producers
                    .iter()
                    .cloned()
                    .map(JsonValue::String)
                    .collect(),
            ),
        ),
        (
            "events".into(),
            JsonValue::Array(event_values(&part.events)),
        ),
        ("groups".into(), JsonValue::Array(groups)),
        ("trimmed".into(), JsonValue::Array(trimmed)),
    ])
}

fn message_parts(message: &JsonValue) -> Option<(&BTreeMap<String, JsonValue>, &str, &str)> {
    let obj = message.as_object()?;
    if obj.get("app")?.as_str()? != "stream" {
        return None;
    }
    let op = obj.get("op")?.as_str()?;
    let stream = obj.get("stream")?.as_str()?;
    if !valid_name(stream) {
        return None;
    }
    Some((obj, op, stream))
}

impl Protocol for Stream {
    fn accept(&self, message: &JsonValue) -> bool {
        if let Some((obj, op, stream)) = message_parts(message) {
            if op == "produce" || op == "append" {
                return match partition_id(obj.get("partition")) {
                    Some(partition) => self.append_ok(obj, op, stream, partition),
                    None => false,
                };
            }
        }
        self.parse(message).is_some()
    }

    fn receive(&mut self, message: &JsonValue) {
        let Some(op) = self.parse(message) else {
            return;
        };
        match op {
            Op::Open {
                stream,
                partition,
                producer,
            } => {
                self.streams
                    .entry(stream)
                    .or_insert_with(Log::new)
                    .partitions
                    .entry(partition)
                    .or_insert_with(Partition::new)
                    .producers
                    .insert(producer);
            }
            Op::Write {
                stream,
                partition,
                records,
            } => {
                if let Some(log) = self.streams.get_mut(&stream) {
                    let retention = log.retention;
                    if let Some(part) = log.partitions.get_mut(&partition) {
                        mutate_records(
                            &mut part.events,
                            &mut part.trimmed,
                            &part.producers,
                            retention,
                            records,
                        );
                    }
                }
            }
            Op::Commit {
                stream,
                partition,
                group,
                producer,
                seq,
            } => {
                if let Some(part) = self
                    .streams
                    .get_mut(&stream)
                    .and_then(|log| log.partitions.get_mut(&partition))
                {
                    let cursors = part.groups.entry(group).or_default();
                    match cursors.get(&producer) {
                        Some(current) if *current >= seq => {}
                        _ => {
                            cursors.insert(producer, seq);
                        }
                    }
                }
            }
            Op::Join { stream, broker } => {
                self.streams
                    .entry(stream)
                    .or_insert_with(Log::new)
                    .brokers
                    .insert(broker, true);
            }
            Op::Fail { stream, broker } => {
                if let Some(log) = self.streams.get_mut(&stream) {
                    log.brokers.insert(broker, false);
                }
            }
            Op::Retain { stream, keep } => {
                if let Some(log) = self.streams.get_mut(&stream) {
                    log.retention = keep;
                    for part in log.partitions.values_mut() {
                        trim_to(&mut part.events, &mut part.trimmed, keep);
                    }
                }
            }
        }
    }
}
