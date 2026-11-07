import pytest

from spellgame import protocol as p
from spellgame.sim import standing_pose


def test_pose_round_trip_keeps_joints_and_optional_velocity():
    pose = standing_pose("P1", 1.5)
    pose.joints["r_hand"].vel = [0.0, 0.0, 3.0]

    decoded = p.decode(p.encode(pose))

    assert isinstance(decoded, p.Pose)
    assert decoded.player_id == "P1"
    assert set(decoded.joints) == set(p.JOINT_NAMES)
    assert decoded.joints["r_hand"].vel == [0.0, 0.0, 3.0]
    assert decoded.joints["head"].vel is None


def test_pose_from_unity_client_skips_null_joints_and_ignores_extra_fields():
    line = (
        '{"type":"pose","player_id":"P1","t":2.0,"joints":{"head":{"pos":[0,1.6,0],"rot":[1,0,0,0],"extra":1},'
        '"hips":null}}'
    )
    decoded = p.decode(line)
    assert isinstance(decoded, p.Pose)
    assert list(decoded.joints) == ["head"]


def test_wire_format_uses_type_field_and_snake_case():
    line = p.encode(p.Damage(target_id="P2", source_id="P1", amount=20.0, hp_after=80.0))
    assert line == '{"type":"damage","target_id":"P2","source_id":"P1","amount":20.0,"hp_after":80.0}'


def test_state_round_trip():
    state = p.State(
        tick=3,
        players=[p.PlayerSnapshot("P1", 100.0, True, True, "none", "fireball")],
        projectiles=[p.ProjectileSnapshot(1, "fireball", "P1", [0, 1, 2], [0, 0, 10])],
    )
    assert p.decode(p.encode(state)) == state


@pytest.mark.parametrize("line", ["not json", "[1]", '{"type":"nope"}', '{"type":"welcome"}'])
def test_bad_messages_raise_protocol_error(line):
    with pytest.raises(p.ProtocolError):
        p.decode(line)


def test_hello_round_trip_keeps_device_and_accepts_unity_nulls():
    hello = p.Hello(role=p.Role.VR, device=p.DeviceInfo(name="Quest", model="Oculus Quest", id="abc"))
    assert p.decode(p.encode(hello)) == hello

    decoded = p.decode('{"type":"hello","role":"vr","device":{"name":"Quest","model":null,"id":null}}')
    assert isinstance(decoded, p.Hello)
    assert decoded.device == p.DeviceInfo(name="Quest")
    assert p.decode('{"type":"hello","role":"classifier"}') == p.Hello(role=p.Role.CLASSIFIER)
