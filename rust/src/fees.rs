//! Fee policy — SPEC/features/fees-policy.md.

use crate::canonical::JsonValue;

pub fn select(candidates: &[JsonValue], limit: i64) -> Result<Vec<String>, String> {
    if limit < 1 {
        return Err("limit must be >= 1".into());
    }
    let mut seen = std::collections::HashSet::new();
    let mut ranked = Vec::new();
    for item in candidates {
        let Some(obj) = item.as_object() else {
            continue;
        };
        let Some(id) = obj.get("id").and_then(JsonValue::as_str) else {
            continue;
        };
        let Some(fee) = obj.get("fee").and_then(JsonValue::as_i64) else {
            continue;
        };
        if id.is_empty() || fee < 0 || !seen.insert(id.to_owned()) {
            continue;
        }
        ranked.push((id.to_owned(), fee));
    }
    ranked.sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
    Ok(ranked
        .into_iter()
        .take(limit as usize)
        .map(|(id, _)| id)
        .collect())
}

pub fn charge(fee: i64, base: i64) -> Result<(i64, i64, i64), String> {
    if fee < 0 || base < 0 {
        return Err("fee and base must be integers >= 0".into());
    }
    let burned = if fee < base { fee } else { base };
    Ok((burned, fee, fee - burned))
}

pub fn estimate(fees: &[i64]) -> Result<i64, String> {
    let mut values = Vec::new();
    for item in fees {
        if *item < 0 {
            return Err("fees must be integers >= 0".into());
        }
        values.push(*item);
    }
    if values.is_empty() {
        return Ok(0);
    }
    values.sort_unstable();
    let mid = values.len() / 2;
    if values.len() % 2 == 1 {
        Ok(values[mid])
    } else {
        Ok((values[mid - 1] + values[mid]) / 2)
    }
}

pub fn next_base_fee(base: i64, parent_count: i64, target: i64) -> Result<i64, String> {
    if base < 0 {
        return Err("base must be >= 0".into());
    }
    if parent_count < 0 {
        return Err("parent_count must be >= 0".into());
    }
    if target < 1 {
        return Err("target must be >= 1".into());
    }
    let denom = target * 8;
    let next = if parent_count >= target {
        base + base * (parent_count - target) / denom
    } else {
        base - base * (target - parent_count) / denom
    };
    Ok(if next < 1 { 1 } else { next })
}
