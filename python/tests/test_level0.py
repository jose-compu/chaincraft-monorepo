"""Level 0 unit tests — one test per normative rule in SPEC/wire-v1.md."""

from __future__ import annotations

import time

import pytest

from chaincraft import canonical, control, crypto, envelope, framing
from chaincraft.canonical import CanonicalError, canonical_json, payload_digest
from chaincraft.dedup import Deduplicator, SeenDigests
from chaincraft.envelope import Envelope, ProtocolError
from chaincraft.discovery import is_connect_allowed, is_resolved_ip_allowed
from chaincraft.framing import FrameReader, FramingError, encode_frame
from chaincraft.mesh import DEFAULT_LISTEN, MAX_PEERS, Mesh, parse_listen

# --- section 1: canonical JSON ---------------------------------------------


class TestCanonicalJson:
    def test_keys_sorted_by_code_point(self):
        assert canonical_json({"b": 1, "a": 2, "C": 3}) == '{"C":3,"a":2,"b":1}'

    def test_no_insignificant_whitespace(self):
        assert canonical_json({"a": [1, 2]}) == '{"a":[1,2]}'

    def test_non_ascii_emitted_literally(self):
        assert canonical_json({"k": "café"}) == '{"k":"café"}'
        assert canonical_json("日本") == '"日本"'

    def test_emoji_survives_round_trip(self):
        text = canonical_json({"e": "😀"})
        assert text == '{"e":"😀"}'
        assert canonical.parse_json(text) == {"e": "😀"}

    def test_short_escapes(self):
        assert canonical_json("\b\t\n\f\r") == '"\\b\\t\\n\\f\\r"'

    def test_quote_and_backslash(self):
        assert canonical_json('a"b\\c') == '"a\\"b\\\\c"'

    def test_other_controls_lowercase_hex(self):
        assert canonical_json("\x00\x1f") == '"\\u0000\\u001f"'

    def test_solidus_not_escaped(self):
        assert canonical_json("a/b") == '"a/b"'

    def test_array_order_significant(self):
        assert canonical_json([3, 1, 2]) == "[3,1,2]"

    def test_literals(self):
        assert canonical_json({"a": True, "b": False, "c": None}) == (
            '{"a":true,"b":false,"c":null}'
        )

    def test_negative_zero_normalized(self):
        assert canonical_json(-0) == "0"

    def test_floats_rejected(self):
        with pytest.raises(CanonicalError, match="floating-point"):
            canonical_json({"x": 1.5})

    def test_integer_out_of_safe_range_rejected(self):
        with pytest.raises(CanonicalError, match="safe range"):
            canonical_json(canonical.MAX_SAFE_INT + 1)
        with pytest.raises(CanonicalError, match="safe range"):
            canonical_json(canonical.MIN_SAFE_INT - 1)

    def test_safe_range_boundaries_accepted(self):
        assert canonical_json(canonical.MAX_SAFE_INT) == "9007199254740991"
        assert canonical_json(canonical.MIN_SAFE_INT) == "-9007199254740991"

    def test_non_string_keys_rejected(self):
        with pytest.raises(CanonicalError, match="keys must be strings"):
            canonical_json({1: "a"})

    def test_unsupported_type_rejected(self):
        with pytest.raises(CanonicalError):
            canonical_json({"x": {1, 2}})

    def test_duplicate_keys_rejected_on_parse(self):
        with pytest.raises(CanonicalError, match="duplicate"):
            canonical.parse_json('{"a":1,"a":2}')

    def test_nan_rejected_on_parse(self):
        with pytest.raises(CanonicalError):
            canonical.parse_json("NaN")

    def test_deep_nesting_rejected(self):
        value = {}
        cursor = value
        for _ in range(200):
            cursor["n"] = {}
            cursor = cursor["n"]
        with pytest.raises(CanonicalError, match="deeply"):
            canonical_json(value)


# --- section 2: payload digest ---------------------------------------------


class TestPayloadDigest:
    def test_digest_is_64_lowercase_hex(self):
        d = payload_digest({"a": 1})
        assert len(d) == 64
        assert d == d.lower()

    def test_key_order_does_not_change_digest(self):
        assert payload_digest({"a": 1, "b": 2}) == payload_digest({"b": 2, "a": 1})

    def test_empty_object_digest_is_stable(self):
        # sha256 of "{}"
        assert payload_digest({}) == (
            "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
        )

    def test_different_payloads_differ(self):
        assert payload_digest({"a": 1}) != payload_digest({"a": 2})


# --- section 3: envelope ----------------------------------------------------


class TestEnvelope:
    def test_build_computes_digest(self):
        env = Envelope.build("app.test", {"n": 1}, ts=1757430000000)
        assert env.id == payload_digest({"n": 1})
        assert env.v == 1

    def test_field_order_on_the_wire(self):
        env = Envelope.build("app.test", {"n": 1}, ts=1757430000000)
        assert env.to_json() == (
            '{"data":{"n":1},"id":"%s","ts":1757430000000,"type":"app.test","v":1}'
            % env.id
        )

    def test_round_trip(self):
        env = Envelope.build("app.test", {"n": 1}, ts=1757430000000)
        parsed = Envelope.parse(env.to_json(), now_ms=1757430000000)
        assert parsed == env

    def test_parse_accepts_bytes(self):
        env = Envelope.build("app.test", {"n": 1}, ts=1757430000000)
        assert Envelope.parse(env.to_bytes(), now_ms=1757430000000) == env

    def test_unknown_field_rejected(self):
        with pytest.raises(ProtocolError, match="unknown envelope fields"):
            Envelope.parse(
                '{"data":{},"extra":1,"id":"%s","ts":0,"type":"app.t","v":1}'
                % payload_digest({}),
                now_ms=0,
            )

    def test_missing_field_rejected(self):
        with pytest.raises(ProtocolError, match="missing envelope fields"):
            Envelope.parse('{"data":{},"ts":0,"type":"app.t","v":1}', now_ms=0)

    def test_wrong_version_rejected(self):
        with pytest.raises(ProtocolError, match="unsupported protocol version"):
            Envelope.parse(
                '{"data":{},"id":"%s","ts":0,"type":"app.t","v":2}'
                % payload_digest({}),
                now_ms=0,
            )

    def test_digest_mismatch_rejected(self):
        with pytest.raises(ProtocolError, match="does not match"):
            Envelope.parse(
                '{"data":{"n":1},"id":"%s","ts":0,"type":"app.t","v":1}' % ("0" * 64),
                now_ms=0,
            )

    def test_uppercase_id_rejected(self):
        digest = payload_digest({}).upper()
        with pytest.raises(ProtocolError, match="lowercase hex"):
            Envelope.parse(
                '{"data":{},"id":"%s","ts":0,"type":"app.t","v":1}' % digest, now_ms=0
            )

    @pytest.mark.parametrize("bad", ["", "App.Test", "a" * 65, "app test", "app/test"])
    def test_invalid_type_rejected(self, bad):
        with pytest.raises(ProtocolError, match="invalid type"):
            Envelope.build(bad, {})

    def test_future_timestamp_rejected(self):
        env = Envelope.build("app.test", {}, ts=1_000_000_000)
        with pytest.raises(ProtocolError, match="future"):
            Envelope.parse(env.to_json(), now_ms=0)

    def test_old_timestamp_accepted(self):
        env = Envelope.build("app.test", {}, ts=1)
        assert Envelope.parse(env.to_json(), now_ms=10**12).ts == 1

    def test_float_payload_rejected(self):
        with pytest.raises(ProtocolError, match="floating-point"):
            Envelope.build("app.test", {"x": 1.5})

    def test_pk_without_sig_rejected(self):
        digest = payload_digest({})
        with pytest.raises(ProtocolError, match="require sig"):
            Envelope.parse(
                '{"data":{},"id":"%s","pk":"%s","ts":0,"type":"app.t","v":1}'
                % (digest, "ab" * 32),
                now_ms=0,
            )

    def test_control_detection(self):
        assert control.hello("py/1.0").is_control()
        assert control.hello("py/1.0").path() == "control"
        link = Envelope.build("link.room.ping", {})
        assert link.is_control()
        assert link.path() == "control"
        gossip = Envelope.build("app.test", {})
        assert not gossip.is_control()
        assert gossip.path() == "gossip"

    def test_broadcast_and_send_stay_on_their_paths(self):
        mesh = Mesh()
        with pytest.raises(ProtocolError, match="gossip"):
            mesh.broadcast("link.room.ping", {})
        with pytest.raises(ProtocolError, match="control"):
            mesh.send("127.0.0.1:1", "app.pubsub", {})
        with pytest.raises(ProtocolError, match="no such link"):
            mesh.send("127.0.0.1:9", "link.room.ping", {})

    def test_reserialization_preserves_digest(self):
        """A relay may rebuild the envelope without breaking downstream dedup."""
        original = Envelope.build("app.test", {"z": 1, "a": [1, 2]}, ts=1757430000000)
        relayed = Envelope.parse(original.to_json(), now_ms=1757430000000)
        rebuilt = Envelope.build("app.test", relayed.data, ts=relayed.ts)
        assert rebuilt.id == original.id
        assert rebuilt.to_json() == original.to_json()


# --- section 4: framing -----------------------------------------------------


class TestFraming:
    def test_length_prefix_is_big_endian_u32(self):
        assert encode_frame(b"hi") == b"\x00\x00\x00\x02hi"

    def test_zero_length_rejected(self):
        with pytest.raises(FramingError, match="zero-length"):
            encode_frame(b"")

    def test_oversize_rejected(self):
        with pytest.raises(FramingError, match="exceeds"):
            encode_frame(b"x" * (framing.MAX_FRAME_BYTES + 1))

    def test_reader_reassembles_split_frame(self):
        frame = encode_frame(b"hello world")
        reader = FrameReader()
        assert reader.feed(frame[:3]) == []
        assert reader.feed(frame[3:7]) == []
        assert reader.feed(frame[7:]) == [b"hello world"]

    def test_reader_handles_multiple_frames_in_one_chunk(self):
        chunk = encode_frame(b"one") + encode_frame(b"two") + encode_frame(b"three")
        assert FrameReader().feed(chunk) == [b"one", b"two", b"three"]

    def test_reader_handles_byte_at_a_time(self):
        frame = encode_frame(b"drip")
        reader = FrameReader()
        received = []
        for i in range(len(frame)):
            received.extend(reader.feed(frame[i : i + 1]))
        assert received == [b"drip"]

    def test_reader_rejects_oversize_declaration_without_body(self):
        reader = FrameReader()
        with pytest.raises(FramingError, match="exceeds"):
            reader.feed((framing.MAX_FRAME_BYTES + 1).to_bytes(4, "big"))

    def test_reader_rejects_zero_length(self):
        with pytest.raises(FramingError, match="zero-length"):
            FrameReader().feed(b"\x00\x00\x00\x00")

    def test_pending_reports_partial_buffer(self):
        reader = FrameReader()
        reader.feed(b"\x00\x00\x00\x05ab")
        assert reader.pending == 6


# --- section 5: control messages -------------------------------------------


class TestControl:
    def test_hello_round_trip(self):
        env = control.hello("py-chaincraft/1.0.0", listen="10.0.0.2:9735")
        parsed = control.parse_hello(Envelope.parse(env.to_json()))
        assert parsed["impl"] == "py-chaincraft/1.0.0"
        assert parsed["listen"] == "10.0.0.2:9735"
        assert parsed["v"] == 1

    def test_hello_caps_sorted(self):
        env = control.hello("py/1.0", caps=["udp", "gossip"])
        assert env.data["caps"] == ["gossip", "udp"]

    def test_hello_unknown_caps_ignored_not_rejected(self):
        env = control.hello("py/1.0", caps=["gossip", "quantum-teleport"])
        parsed = control.parse_hello(env)
        assert parsed["caps"] == ["gossip"]
        assert parsed["unknown_caps"] == ["quantum-teleport"]

    def test_hello_version_mismatch_rejected(self):
        env = Envelope.build(control.HELLO, {"v": 99, "impl": "x/1", "caps": []})
        with pytest.raises(ProtocolError, match="peer speaks protocol v99"):
            control.parse_hello(env)

    def test_all_control_types_parse_as_envelopes(self):
        envelopes = [
            control.hello("py/1.0"),
            control.peers_request(),
            control.peers(["1.2.3.4:9735"]),
            control.digest_request("Ledger"),
            control.digest("Ledger", "ab" * 32, ["cd" * 32]),
            control.messages_request("Ledger", "ab" * 32),
            control.messages("Ledger", [Envelope.build("app.t", {"n": 1})]),
        ]
        for env in envelopes:
            assert env.type in control.CONTROL_TYPES
            assert Envelope.parse(env.to_json()).id == env.id


# --- section 6: signatures --------------------------------------------------


class TestSignatures:
    SECKEY = bytes.fromhex(
        "0000000000000000000000000000000000000000000000000000000000000003"
    )

    def test_schnorr_sign_and_verify(self):
        env = Envelope.build("app.test", {"n": 1}, ts=1757430000000)
        signed = env.signed(crypto.SCHNORR, self.SECKEY)
        assert signed.alg == "schnorr"
        assert len(signed.sig) == 128
        assert len(signed.pk) == 64
        assert signed.verify()

    def test_signed_envelope_round_trips(self):
        env = Envelope.build("app.test", {"n": 1}, ts=1757430000000)
        signed = env.signed(crypto.SCHNORR, self.SECKEY)
        parsed = Envelope.parse(signed.to_json(), now_ms=1757430000000)
        assert parsed == signed
        assert parsed.verify()

    def test_tampered_payload_fails_digest_before_signature(self):
        env = Envelope.build("app.test", {"n": 1}, ts=1757430000000)
        signed = env.signed(crypto.SCHNORR, self.SECKEY)
        tampered = signed.to_json().replace('"n":1', '"n":2')
        with pytest.raises(ProtocolError, match="does not match"):
            Envelope.parse(tampered, now_ms=1757430000000)

    def test_wrong_key_fails_verification(self):
        env = Envelope.build("app.test", {"n": 1}, ts=1757430000000)
        signed = env.signed(crypto.SCHNORR, self.SECKEY)
        other = Envelope(
            type=signed.type,
            data=signed.data,
            id=signed.id,
            ts=signed.ts,
            sig=signed.sig,
            pk="ab" * 32,
            alg="schnorr",
        )
        assert other.verify() is False

    def test_bip340_vector(self):
        """BIP-340 test vector index 0 — pins the pure-Python implementation."""
        seckey = bytes.fromhex(
            "0000000000000000000000000000000000000000000000000000000000000003"
        )
        pubkey = bytes.fromhex(
            "F9308A019258C31049344F85F89D5229B531C845836F99B08601F113BCE036F9"
        )
        aux = bytes(32)
        msg = bytes(32)
        expected = bytes.fromhex(
            "E907831F80848D1069A5371B402410364BDF1C5F8307B0084C55F1CE2DCA8215"
            "25F66A4A85EA8B71E482A74F382D2CE5EBEEE8FDB2172F477DF4900D310536C0"
        )
        assert crypto.public_key(crypto.SCHNORR, seckey) == pubkey
        assert crypto._schnorr_sign(msg, seckey, aux) == expected
        assert crypto.verify(crypto.SCHNORR, msg, expected, pubkey)

    def test_verify_never_raises_on_garbage(self):
        assert crypto.verify(crypto.SCHNORR, b"short", b"x" * 64, b"y" * 32) is False
        assert crypto.verify(crypto.SCHNORR, b"m" * 32, b"short", b"y" * 32) is False
        assert crypto.verify("nonsense", b"m" * 32, b"s" * 64, b"p" * 32) is False

    @pytest.mark.skipif(
        not crypto.ed25519_available(), reason="cryptography not installed"
    )
    def test_ed25519_sign_and_verify(self):
        env = Envelope.build("app.test", {"n": 1}, ts=1757430000000)
        signed = env.signed(crypto.ED25519, bytes(range(32)))
        assert signed.alg == "ed25519"
        assert signed.verify()


# --- section 7: deduplication ----------------------------------------------


class TestDeduplication:
    def test_identical_payloads_share_a_digest(self):
        a = Envelope.build("app.test", {"n": 1}, ts=1)
        b = Envelope.build("app.test", {"n": 1}, ts=999)
        assert a.id == b.id, "digest must ignore ts so relays dedup consistently"

    def test_nonce_distinguishes_otherwise_equal_payloads(self):
        a = Envelope.build("app.test", {"n": 1, "nonce": "a"})
        b = Envelope.build("app.test", {"n": 1, "nonce": "b"})
        assert a.id != b.id

    def test_repeat_delivery_is_suppressed(self):
        dedup = Deduplicator()
        env = Envelope.build("app.test", {"n": 1})
        assert dedup.should_process(env) is True
        assert dedup.should_process(env) is False, "this terminates a gossip loop"

    def test_control_messages_are_never_recorded_or_relayed(self):
        dedup = Deduplicator()
        hello = control.hello("py-chaincraft/1.0.0")
        assert dedup.should_process(hello) is True
        assert dedup.should_process(hello) is True, "ctl.* is point-to-point"
        assert dedup.should_relay(hello) is False
        assert len(dedup.seen) == 0

    def test_eviction_is_fifo_and_reseeing_does_not_refresh(self):
        seen = SeenDigests(capacity=2)
        assert seen.add("a") is True
        assert seen.add("b") is True
        assert seen.add("a") is False, "already present"
        # If re-seeing had refreshed "a", "c" would evict "b" instead.
        assert seen.add("c") is True
        assert "a" not in seen
        assert "b" in seen and "c" in seen
        assert len(seen) == 2

    def test_capacity_must_be_positive(self):
        with pytest.raises(ValueError):
            SeenDigests(capacity=0)


class TestConnectPolicy:
    def test_loopback_rfc1918_and_public_allowed(self):
        assert is_connect_allowed("127.0.0.1:21000")
        assert is_connect_allowed("10.0.0.2:9735")
        assert is_connect_allowed("192.168.1.8:8080")
        assert is_connect_allowed("172.16.0.1:1")
        assert is_connect_allowed("localhost:9735")
        assert is_connect_allowed("node-a.local:8080")
        assert is_connect_allowed("8.8.8.8:53")
        assert is_connect_allowed("example.com:443")
        assert is_resolved_ip_allowed("1.1.1.1")

    def test_unspecified_link_local_and_multicast_refused(self):
        assert not is_connect_allowed("169.254.169.254:80")
        assert not is_connect_allowed("0.0.0.0:21000")
        assert not is_connect_allowed("224.0.0.1:9735")
        assert not is_connect_allowed("255.255.255.255:1")
        assert not is_resolved_ip_allowed("0.0.0.0")
        assert not is_resolved_ip_allowed("224.0.0.1")


class TestListen:
    def test_default_is_all_interfaces_9735(self):
        assert DEFAULT_LISTEN == "0.0.0.0:9735"
        assert parse_listen() == ("0.0.0.0", 9735)
        assert parse_listen("") == ("0.0.0.0", 9735)
        assert MAX_PEERS == 256

    def test_ephemeral_and_explicit(self):
        assert parse_listen("127.0.0.1:0") == ("127.0.0.1", 0)
        assert parse_listen("127.0.0.1:9736") == ("127.0.0.1", 9736)

    def test_rejects_bad_listen(self):
        with pytest.raises(ValueError):
            parse_listen("9735")
        with pytest.raises(ValueError):
            parse_listen("127.0.0.1:65536")


class TestTwoNodeMesh:
    def test_two_local_sockets_gossip_hello(self):
        got = []
        a = Mesh(on_app=lambda t, d: got.append((t, d)))
        b = Mesh()
        try:
            addr_a = a.start("127.0.0.1", 0)
            b.start("127.0.0.1", 0)
            b.connect(addr_a)
            digest = b.broadcast("app.hello", {"message": "Hello, Chaincraft!"})
            deadline = time.time() + 2
            while time.time() < deadline and not got:
                time.sleep(0.05)
            assert got == [("app.hello", {"message": "Hello, Chaincraft!"})]
            assert digest in a.ids()
            assert digest in b.ids()
        finally:
            a.close()
            b.close()
