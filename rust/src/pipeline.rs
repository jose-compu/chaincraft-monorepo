//! The apply pipeline — SPEC/semantics-v1.md §3.

use std::collections::BTreeMap;

use crate::canonical::JsonValue;
use crate::memento::StateMemento;
use crate::object::ApplicationObject;

#[derive(Debug)]
pub struct ApplyResult {
    pub accepted: bool,
    pub rejected_by: Option<String>,
    pub mementos: BTreeMap<String, StateMemento>,
    pub should_persist: bool,
}

/// Objects in registration order, with the validate-all-then-apply pipeline.
pub struct ObjectRegistry {
    entries: Vec<(String, Box<dyn ApplicationObject>)>,
}

impl ObjectRegistry {
    pub fn new() -> Self {
        Self {
            entries: Vec::new(),
        }
    }

    pub fn register(&mut self, name: impl Into<String>, object: Box<dyn ApplicationObject>) {
        let name = name.into();
        if self.entries.iter().any(|(n, _)| n == &name) {
            panic!("object already registered: {name}");
        }
        self.entries.push((name, object));
    }

    pub fn names(&self) -> Vec<String> {
        self.entries.iter().map(|(n, _)| n.clone()).collect()
    }

    pub fn get(&self, name: &str) -> Option<&dyn ApplicationObject> {
        self.entries
            .iter()
            .find(|(n, _)| n == name)
            .map(|(_, obj)| obj.as_ref())
    }

    pub fn get_mut(&mut self, name: &str) -> Option<&mut dyn ApplicationObject> {
        self.entries
            .iter_mut()
            .find(|(n, _)| n == name)
            .map(|(_, obj)| obj.as_mut())
    }

    pub fn apply(&mut self, message: &JsonValue) -> ApplyResult {
        for (name, object) in &self.entries {
            if !object.is_valid(message) {
                return ApplyResult {
                    accepted: false,
                    rejected_by: Some(name.clone()),
                    mementos: BTreeMap::new(),
                    should_persist: false,
                };
            }
        }

        let mut mementos = BTreeMap::new();
        let mut threaded: Option<StateMemento> = None;
        for (name, object) in &mut self.entries {
            let returned = object.add_message(message, threaded.as_ref());
            let next = returned.unwrap_or_else(|| object.emit_state_memento());
            threaded = Some(next.clone());
            mementos.insert(name.clone(), next);
        }

        ApplyResult {
            accepted: true,
            rejected_by: None,
            mementos,
            should_persist: true,
        }
    }
}

impl Default for ObjectRegistry {
    fn default() -> Self {
        Self::new()
    }
}
