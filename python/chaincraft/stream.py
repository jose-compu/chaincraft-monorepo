"""Append-only event log — SPEC/features/app-stream.md."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .canonical import MAX_SAFE_INT
from .object import SharedObject

__all__ = [
    "MAX_BATCH",
    "MAX_BROKERS",
    "MAX_EVENTS",
    "MAX_GROUPS",
    "MAX_PARTITIONS",
    "MAX_PAYLOAD",
    "MAX_PRODUCERS",
    "MAX_READ",
    "MAX_STREAMS",
    "Stream",
]

MAX_STREAMS = 32
MAX_PARTITIONS = 16
MAX_PRODUCERS = 32
MAX_EVENTS = 64
MAX_GROUPS = 32
MAX_BROKERS = 8
MAX_BATCH = 64
MAX_PAYLOAD = 4096
MAX_READ = 256

_NAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_Record = Tuple[str, int, str]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and value is not True and value is not False


def _name(value: Any) -> bool:
    return isinstance(value, str) and _NAME.fullmatch(value) is not None


def _drop_oldest(events: Dict[Tuple[str, int], str], trimmed: Dict[str, int]) -> None:
    producer, seq = min(events, key=lambda key: (key[1], key[0]))
    del events[(producer, seq)]
    mark = trimmed.get(producer, -1)
    if seq == mark + 1:
        trimmed[producer] = seq


def _trim_to(
    events: Dict[Tuple[str, int], str], trimmed: Dict[str, int], keep: int
) -> None:
    while len(events) > keep:
        _drop_oldest(events, trimmed)


def _mutate_records(
    events: Dict[Tuple[str, int], str],
    trimmed: Dict[str, int],
    producers: set[str],
    retention: int,
    records: List[_Record],
) -> bool:
    for producer, seq, payload in records:
        if producer not in producers:
            return False
        mark = trimmed.get(producer, -1)
        if seq <= mark:
            return False
        key = (producer, seq)
        prior = events.get(key)
        if prior is not None:
            if prior != payload:
                return False
            continue
        if len(events) >= MAX_EVENTS:
            return False
        events[key] = payload
        _trim_to(events, trimmed, retention)
    return True


def _prefix_closed(
    events: Dict[Tuple[str, int], str], trimmed: Dict[str, int], producer: str, seq: int
) -> bool:
    # Count stored records. Walking mark+1..=seq hangs on a large sparse seq.
    if (producer, seq) not in events:
        return False
    mark = trimmed.get(producer, -1)
    if seq <= mark:
        return False
    found = sum(1 for (who, n) in events if who == producer and mark < n <= seq)
    return found == seq - mark


class _Partition:
    def __init__(self) -> None:
        self.producers: set[str] = set()
        self.events: Dict[Tuple[str, int], str] = {}
        self.groups: Dict[str, Dict[str, int]] = {}
        self.trimmed: Dict[str, int] = {}


class _Log:
    def __init__(self) -> None:
        self.retention = MAX_EVENTS
        self.brokers: Dict[str, bool] = {}
        self.partitions: Dict[int, _Partition] = {}

    def available(self) -> bool:
        if not self.brokers:
            return True
        return any(self.brokers.values())


class Stream(SharedObject):
    def __init__(self) -> None:
        self._streams: Dict[str, _Log] = {}

    def is_valid(self, message: Any) -> bool:
        return self._parse(message) is not None

    def receive(self, message: Any) -> None:
        parsed = self._parse(message)
        if parsed is None:
            return
        op = parsed[0]
        if op == "open":
            _, stream_name, partition, producer = parsed
            log = self._streams.setdefault(stream_name, _Log())
            part = log.partitions.setdefault(partition, _Partition())
            part.producers.add(producer)
        elif op in ("produce", "append"):
            _, stream_name, partition, records = parsed
            log = self._streams[stream_name]
            part = log.partitions[partition]
            events = dict(part.events)
            trimmed = dict(part.trimmed)
            _mutate_records(events, trimmed, part.producers, log.retention, records)
            part.events = events
            part.trimmed = trimmed
        elif op == "commit":
            _, stream_name, partition, group, producer, seq = parsed
            part = self._streams[stream_name].partitions[partition]
            cursors = part.groups.setdefault(group, {})
            current = cursors.get(producer)
            if current is None or seq > current:
                cursors[producer] = seq
        elif op == "join":
            _, stream_name, broker = parsed
            log = self._streams.setdefault(stream_name, _Log())
            log.brokers[broker] = True
        elif op == "fail":
            _, stream_name, broker = parsed
            self._streams[stream_name].brokers[broker] = False
        else:
            _, stream_name, keep = parsed
            log = self._streams[stream_name]
            log.retention = keep
            for part in log.partitions.values():
                events = dict(part.events)
                trimmed = dict(part.trimmed)
                _trim_to(events, trimmed, keep)
                part.events = events
                part.trimmed = trimmed

    def state(self) -> Dict[str, Any]:
        return {"streams": self._stream_list()}

    def read(
        self, stream: Any, partition: Any, after: Any, limit: Any
    ) -> List[Dict[str, Any]]:
        if not isinstance(stream, str):
            return []
        if not _is_int(partition) or not (0 <= partition < MAX_PARTITIONS):
            return []
        if not _is_int(limit) or not (1 <= limit <= MAX_READ):
            return []
        log = self._streams.get(stream)
        if log is None or not log.available():
            return []
        part = log.partitions.get(partition)
        if part is None:
            return []
        cursor = _cursor(after)
        if cursor is False:
            return []
        events = [
            {"producer": producer, "seq": seq, "payload": payload}
            for (producer, seq), payload in part.events.items()
        ]
        events.sort(key=lambda event: (event["seq"], event["producer"]))
        if cursor is not None:
            cseq, cprod = cursor
            events = [
                event
                for event in events
                if (event["seq"], event["producer"]) > (cseq, cprod)
            ]
        return events[:limit]

    def _stream_list(self) -> list:
        streams = []
        for name in sorted(self._streams):
            log = self._streams[name]
            partitions = []
            for pid in sorted(log.partitions):
                part = log.partitions[pid]
                events = [
                    {"producer": producer, "seq": seq, "payload": payload}
                    for (producer, seq), payload in part.events.items()
                ]
                events.sort(key=lambda event: (event["seq"], event["producer"]))
                groups = []
                for group_name in sorted(part.groups):
                    cursors = [
                        {"producer": producer, "seq": seq}
                        for producer, seq in sorted(part.groups[group_name].items())
                    ]
                    groups.append({"name": group_name, "cursors": cursors})
                trimmed = [
                    {"producer": producer, "seq": seq}
                    for producer, seq in sorted(part.trimmed.items())
                ]
                partitions.append(
                    {
                        "partition": pid,
                        "producers": sorted(part.producers),
                        "events": events,
                        "groups": groups,
                        "trimmed": trimmed,
                    }
                )
            replicas = [
                {"broker": broker, "status": "up" if up else "down"}
                for broker, up in sorted(log.brokers.items())
            ]
            streams.append(
                {
                    "name": name,
                    "retention": log.retention,
                    "replicas": replicas,
                    "partitions": partitions,
                }
            )
        return streams

    def _parse(self, message: Any) -> Optional[tuple]:
        if not isinstance(message, dict) or message.get("app") != "stream":
            return None
        op = message.get("op")
        stream = message.get("stream")
        if not _name(stream):
            return None
        if op in ("open", "produce", "append", "commit"):
            partition = _partition(message)
            if partition is None:
                return None
            return self._parse_data(message, op, stream, partition)
        if op == "join":
            return self._parse_join(stream, message.get("broker"))
        if op == "fail":
            return self._parse_fail(stream, message.get("broker"))
        if op == "retain":
            return self._parse_retain(stream, message.get("keep"))
        return None

    def _parse_data(
        self, message: Dict[str, Any], op: str, stream: str, partition: int
    ) -> Optional[tuple]:
        log = self._streams.get(stream)
        if log is not None and not log.available():
            return None
        if op == "open":
            producer = message.get("producer")
            if not _name(producer):
                return None
            if log is None and len(self._streams) >= MAX_STREAMS:
                return None
            part = None if log is None else log.partitions.get(partition)
            if (
                log is not None
                and part is None
                and len(log.partitions) >= MAX_PARTITIONS
            ):
                return None
            if (
                part is not None
                and producer not in part.producers
                and len(part.producers) >= MAX_PRODUCERS
            ):
                return None
            return ("open", stream, partition, producer)
        if log is None:
            return None
        part = log.partitions.get(partition)
        if part is None:
            return None
        if op == "commit":
            group = message.get("group")
            producer = message.get("producer")
            seq = message.get("seq")
            if not _name(group) or not _name(producer):
                return None
            if not _is_int(seq) or not (0 <= seq <= MAX_SAFE_INT):
                return None
            if producer not in part.producers:
                return None
            if not _prefix_closed(part.events, part.trimmed, producer, seq):
                return None
            if group not in part.groups and len(part.groups) >= MAX_GROUPS:
                return None
            return ("commit", stream, partition, group, producer, seq)
        records = _records_of(message, op)
        if records is None:
            return None
        events = dict(part.events)
        trimmed = dict(part.trimmed)
        if not _mutate_records(events, trimmed, part.producers, log.retention, records):
            return None
        return (op, stream, partition, records)

    def _parse_join(self, stream: str, broker: Any) -> Optional[tuple]:
        if not _name(broker):
            return None
        log = self._streams.get(stream)
        if log is None and len(self._streams) >= MAX_STREAMS:
            return None
        if (
            log is not None
            and broker not in log.brokers
            and len(log.brokers) >= MAX_BROKERS
        ):
            return None
        return ("join", stream, broker)

    def _parse_fail(self, stream: str, broker: Any) -> Optional[tuple]:
        if not _name(broker):
            return None
        log = self._streams.get(stream)
        if log is None or broker not in log.brokers:
            return None
        return ("fail", stream, broker)

    def _parse_retain(self, stream: str, keep: Any) -> Optional[tuple]:
        if not _is_int(keep) or not (1 <= keep <= MAX_EVENTS):
            return None
        if stream not in self._streams:
            return None
        return ("retain", stream, keep)


def _partition(message: Dict[str, Any]) -> Optional[int]:
    if "partition" not in message:
        return 0
    value = message.get("partition")
    if not _is_int(value) or not (0 <= value < MAX_PARTITIONS):
        return None
    return value


def _cursor(after: Any) -> Any:
    if after is None:
        return None
    if not isinstance(after, dict):
        return False
    producer = after.get("producer")
    seq = after.get("seq")
    if not _name(producer) or not _is_int(seq) or not (0 <= seq <= MAX_SAFE_INT):
        return False
    return (seq, producer)


def _one_record(producer: Any, seq: Any, payload: Any) -> Optional[_Record]:
    if not _name(producer):
        return None
    if not isinstance(payload, str) or not (1 <= len(payload) <= MAX_PAYLOAD):
        return None
    if not _is_int(seq) or not (0 <= seq <= MAX_SAFE_INT):
        return None
    return (producer, seq, payload)


def _records_of(message: Dict[str, Any], op: str) -> Optional[List[_Record]]:
    if op == "produce":
        record = _one_record(
            message.get("producer"), message.get("seq"), message.get("payload")
        )
        if record is None:
            return None
        return [record]
    raw = message.get("records")
    if not isinstance(raw, list) or not (1 <= len(raw) <= MAX_BATCH):
        return None
    records = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        record = _one_record(item.get("producer"), item.get("seq"), item.get("payload"))
        if record is None:
            return None
        records.append(record)
    return records
