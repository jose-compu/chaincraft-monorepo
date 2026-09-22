//! Topic publish-subscribe — SPEC/features/app-pubsub.md.

use std::collections::{BTreeMap, BTreeSet};

use crate::canonical::{JsonValue, MAX_SAFE_INT};
use crate::object::Protocol;

pub const MAX_ROOMS: usize = 32;
pub const MAX_MEMBERS: usize = 32;
pub const MAX_POSTS: usize = 64;
pub const MAX_TEXT: usize = 1024;

struct Room {
    members: BTreeSet<String>,
    posts: BTreeMap<(String, i64), String>,
}

pub struct PubSub {
    rooms: BTreeMap<String, Room>,
}

impl PubSub {
    pub fn new() -> Self {
        Self {
            rooms: BTreeMap::new(),
        }
    }

    pub fn state_value(&self) -> JsonValue {
        JsonValue::object([("rooms".into(), JsonValue::Array(self.room_list()))])
    }

    fn room_list(&self) -> Vec<JsonValue> {
        self.rooms
            .iter()
            .map(|(name, room)| {
                let mut posts: Vec<(&String, i64, &String)> = room
                    .posts
                    .iter()
                    .map(|((author, seq), text)| (author, *seq, text))
                    .collect();
                posts.sort_by(|a, b| a.1.cmp(&b.1).then_with(|| a.0.cmp(b.0)));
                JsonValue::object([
                    ("name".into(), JsonValue::String(name.clone())),
                    (
                        "members".into(),
                        JsonValue::Array(
                            room.members
                                .iter()
                                .cloned()
                                .map(JsonValue::String)
                                .collect(),
                        ),
                    ),
                    (
                        "posts".into(),
                        JsonValue::Array(
                            posts
                                .into_iter()
                                .map(|(author, seq, text)| {
                                    JsonValue::object([
                                        ("author".into(), JsonValue::String(author.clone())),
                                        ("seq".into(), JsonValue::Number(seq)),
                                        ("text".into(), JsonValue::String(text.clone())),
                                    ])
                                })
                                .collect(),
                        ),
                    ),
                ])
            })
            .collect()
    }

    fn parse(&self, message: &JsonValue) -> Option<Op> {
        let obj = message.as_object()?;
        if obj.get("app")?.as_str()? != "pubsub" {
            return None;
        }
        let op = obj.get("op")?.as_str()?;
        let room = obj.get("room")?.as_str()?;
        let author = obj.get("author")?.as_str()?;
        if !valid_name(room) || !valid_name(author) {
            return None;
        }
        match op {
            "subscribe" => {
                match self.rooms.get(room) {
                    None if self.rooms.len() >= MAX_ROOMS => return None,
                    Some(existing)
                        if !existing.members.contains(author)
                            && existing.members.len() >= MAX_MEMBERS =>
                    {
                        return None;
                    }
                    _ => {}
                }
                Some(Op::Subscribe {
                    room: room.to_owned(),
                    author: author.to_owned(),
                })
            }
            "unsubscribe" => {
                let existing = self.rooms.get(room)?;
                if !existing.members.contains(author) {
                    return None;
                }
                Some(Op::Unsubscribe {
                    room: room.to_owned(),
                    author: author.to_owned(),
                })
            }
            "publish" => {
                let text = obj.get("text")?.as_str()?;
                let seq = obj.get("seq")?.as_i64()?;
                let scalars = text.chars().count();
                if !(1..=MAX_TEXT).contains(&scalars) || !(0..=MAX_SAFE_INT).contains(&seq) {
                    return None;
                }
                let existing = self.rooms.get(room)?;
                if !existing.members.contains(author) {
                    return None;
                }
                if existing.posts.contains_key(&(author.to_owned(), seq))
                    || existing.posts.len() >= MAX_POSTS
                {
                    return None;
                }
                Some(Op::Publish {
                    room: room.to_owned(),
                    author: author.to_owned(),
                    text: text.to_owned(),
                    seq,
                })
            }
            _ => None,
        }
    }
}

impl Default for PubSub {
    fn default() -> Self {
        Self::new()
    }
}

enum Op {
    Subscribe {
        room: String,
        author: String,
    },
    Unsubscribe {
        room: String,
        author: String,
    },
    Publish {
        room: String,
        author: String,
        text: String,
        seq: i64,
    },
}

fn valid_name(value: &str) -> bool {
    (1..=64).contains(&value.len())
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
}

impl Protocol for PubSub {
    fn accept(&self, message: &JsonValue) -> bool {
        self.parse(message).is_some()
    }

    fn receive(&mut self, message: &JsonValue) {
        if let Some(op) = self.parse(message) {
            match op {
                Op::Subscribe { room, author } => {
                    self.rooms
                        .entry(room)
                        .or_insert_with(|| Room {
                            members: BTreeSet::new(),
                            posts: BTreeMap::new(),
                        })
                        .members
                        .insert(author);
                }
                Op::Unsubscribe { room, author } => {
                    if let Some(existing) = self.rooms.get_mut(&room) {
                        existing.members.remove(&author);
                        if existing.members.is_empty() && existing.posts.is_empty() {
                            self.rooms.remove(&room);
                        }
                    }
                }
                Op::Publish {
                    room,
                    author,
                    text,
                    seq,
                } => {
                    if let Some(existing) = self.rooms.get_mut(&room) {
                        existing.posts.insert((author, seq), text);
                    }
                }
            }
        }
    }
}
