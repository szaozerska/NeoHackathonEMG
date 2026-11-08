"""Server-side spatial recognition; no game mechanics execute on Quest."""
from __future__ import annotations
from collections import deque
import numpy as np
from scipy.spatial.transform import Rotation
from .common import unit, vector
from .intent import FireballOption

DEFAULT_MOTION = {
    "hip": [-.23, -.38, 0], "hip_radius": .24, "hip_memory": .35,
    "draw_timeout": 1.5, "draw_up": .24, "draw_right": .18,
    "facing_cos": .65, "fingers_up_cos": .65, "shield_reach": .2,
    "push_speed": .9, "push_acceleration": 3., "push_displacement": .025,
    "boost_duration": .25, "boost_cooldown": .45,
    "throw_speed": 1.4, "throw_displacement": .13, "throw_min_hold": .25,
    "fireball_lifetime": 8., "stale": .3, "derivative_window": .12,
    "confidence": .5, "smoothing_tau": .025, "activation_cooldown": .3,
}


def torso_coordinates(value, chest):
    # Unity +X right, +Y up, +Z forward; quaternion order in wire protocol is w,x,y,z.
    q = vector(chest["rot"], 4)
    if np.linalg.norm(q) < .9:
        raise ValueError("Invalid chest rotation")
    rotation = Rotation.from_quat([q[1], q[2], q[3], q[0]])
    return rotation.inv().apply(value)


class SpellEngine:
    def __init__(self, config=None):
        self.config = DEFAULT_MOTION | (config or {})
        self.option = FireballOption()
        self.sign, self.sign_t = "none", -float("inf")
        self.pose, self.pose_t = None, -float("inf")
        self.mode = "idle"
        self.history = deque()
        self.near_hip = -float("inf")
        self.gripped_at, self.draw_start = None, None
        self.fireball_at = None
        self.boost_until, self.boost_score, self.last_push = -1., 0., -float("inf")
        self.seen = deque(maxlen=256)
        self.last_output = None
        self.metrics = None
        self.activation_after = -float("inf")
        self.frame_id = None
        self.effort_index, self.effort_t = 0., -float("inf")

    def _event(self, name, t, **fields):
        return {"type": "spell", "event": name, "t": float(t), "hand": "right", **fields}

    def expire(self, t):
        out = [self._event(v['event'], t, **{k:x for k,x in v.items() if k not in ('event','t')}) for v in self.option.expire(t)]
        if t - self.effort_t > self.config["stale"]:
            self.effort_index = 0.
        if t - self.sign_t > self.config["stale"]:
            self.sign = "none"
            if self.option.phase != "idle":
                self.option.reset()
                out.append(self._event("fireball_cancel",t,reason="stale_emg"))
                if self.mode == "fireball":self.mode = "idle"
            if self.mode == "shield":
                out.append(self._event("shield_dismiss", t, reason="stale_emg"))
                self.mode = "idle"
            if self.mode == "sword":
                out.append(self._event("sword_dismiss", t, reason="stale_emg"))
                self.mode = "idle"
        if t - self.pose_t > self.config["stale"]:
            self.history.clear()
            self.near_hip, self.gripped_at, self.draw_start = -float("inf"), None, None
            self.boost_until = -1.
            if self.mode == "shield":
                out.append(self._event("shield_dismiss", t, reason="stale_tracking"))
                self.mode = "idle"
        return out

    def state(self, label, t, confidence=1.):
        out = self.expire(t)
        if confidence < self.config['confidence']:
            label = 'none'
        self.sign, self.sign_t = label, t
        for event in self.option.state(label,t):
            out.append(self._event(event['event'],t,**{k:v for k,v in event.items() if k not in ('event','t')}))
            if event['event']=='fireball_cancel' and self.mode=='fireball':self.mode='idle'
        if self.mode == 'sword' and label != 'fist':
            self.mode = 'idle'
            out.append(self._event('sword_dismiss', t, reason='opened' if label == 'open' else 'lost_fist'))
        if self.mode == 'shield' and label != 'open':
            self.mode = 'idle'
            out.append(self._event('shield_dismiss', t, reason='lost_open_hand'))
        if label == 'fist' and self.mode == 'idle':
            self.mode = 'sword'
            fields = {'origin': self.pose['world'], 'rotation': self.pose['rotation']} if self.pose and t-self.pose_t <= self.config['stale'] else {}
            out.append(self._event('sword_cast', t, **fields))
        return out

    def effort(self, value, t):
        """Calibrated relative activation, supplied by a separate effort model."""
        out = self.expire(t)
        if not np.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('Effort must be finite and between zero and one')
        self.effort_index, self.effort_t = float(value), t
        if self.mode == 'shield':
            out.append(self._event('shield_strength', t, strength=self.effort_index))
        return out

    def snap(self, t, event_id):
        out = self.expire(t)
        self.sign_t=max(self.sign_t,t)  # A snap is fresh band evidence even before the next state window.
        events=self.option.snap(t,event_id)
        for event in events:
            if self.mode in ('sword','shield'):out.append(self._event(self.mode+'_dismiss',t,reason='snap_equips'))
            self.mode='fireball';self.fireball_at=t;self.history.clear()
            out.append(self._event(event['event'],t,committed=False))
            out.append(self._event('fireball_spawn',t,prepared=True,committed=False))
        return out

    def pose_sample(self, packet, t, sample_t=None):
        out = self.expire(t)
        self.metrics = None
        frame_id = packet.get("frame_id", "default")
        if frame_id != self.frame_id:
            self.history.clear()
            self.near_hip, self.gripped_at, self.draw_start = -float("inf"), None, None
            self.boost_until = -1.
            self.frame_id = frame_id
        sample_t = t if sample_t is None else sample_t
        c = self.config
        try:
            hand, chest = packet["hand"], packet["chest"]
            if not hand["valid"] or not chest["valid"] or min(hand["confidence"], chest["confidence"]) < c["confidence"]:
                raise ValueError("Invalid tracking")
            world = vector(hand["pos"])
            relative = world - vector(chest["pos"])
            local = torso_coordinates(relative, chest)
            facing = unit(packet.get("opponent_direction", [0, 0, 1]))
            palm = unit(hand["palm_normal"])
        except (KeyError, TypeError, ValueError):
            self.history.clear()
            self.pose = None
            self.near_hip, self.gripped_at, self.draw_start = -float("inf"), None, None
            self.boost_until = -1.
            if self.mode == "shield":
                out.append(self._event("shield_dismiss", t, reason="invalid_tracking"))
                self.mode = "idle"
            return out
        if self.history and (sample_t <= self.history[-1][0] or sample_t - self.history[-1][0] > .12):
            self.history.clear()
            self.gripped_at, self.draw_start = None, None
        if self.history:
            dt = sample_t - self.history[-1][0]
            alpha = 1 - np.exp(-dt/c["smoothing_tau"])
            smooth = self.history[-1][1] + alpha*(relative - self.history[-1][1])
        else:
            smooth = relative.copy()
        self.history.append((sample_t, smooth, world))
        while self.history and sample_t - self.history[0][0] > c["derivative_window"]:
            self.history.popleft()
        self.pose = {"world": world.tolist(), "local": local.tolist(), "rotation": hand["rot"]}
        self.pose_t = t
        fingers = hand.get('finger_direction')
        try:
            fingers_up = fingers is not None and float(unit(fingers) @ np.array([0., 1., 0.])) >= c['fingers_up_cos']
        except (TypeError, ValueError):
            fingers_up = False
        palm_facing = float(palm @ facing) >= c['facing_cos']
        # Reach is a torso-relative proxy; elbow straightness is not measured by this schema.
        extended = float(relative @ facing) >= c['shield_reach']
        shield_pose = self.sign == 'open' and fingers_up and palm_facing and extended
        if shield_pose and self.mode=='fireball':
            for event in self.option.shield(t,confirmed=True):
                out.append(self._event('fireball_cancel',t,reason='shield'))
                self.mode='idle';self.history.clear()
        if self.mode == 'shield' and not shield_pose:
            self.mode = 'idle'
            out.append(self._event('shield_dismiss', t, reason='pose_ended'))
        if self.mode == 'idle' and self.option.phase=='idle' and shield_pose and t >= self.activation_after:
            self.mode = 'shield'
            out.append(self._event('shield_guard', t, origin=world.tolist(), rotation=hand['rot'],
                                   strength=self.effort_index))
        elif self.mode == 'shield':
            out.append(self._event('shield_pose', t, origin=world.tolist(), rotation=hand['rot'],
                                   strength=self.effort_index))
        if len(self.history) < 4 or sample_t - self.history[0][0] < .04:
            return out
        ts = np.array([h[0] - sample_t for h in self.history])
        positions = np.array([h[1] for h in self.history])
        world_positions = np.array([h[2] for h in self.history])
        fit = np.column_stack([np.ones(len(ts)), ts, .5*ts**2])
        coefficients = np.linalg.lstsq(fit, positions, rcond=None)[0]
        velocity, acceleration = coefficients[1], coefficients[2]
        self.metrics = {'t': sample_t, 'speed': float(np.linalg.norm(velocity)),
                        'travel': float(np.linalg.norm(positions[-1] - positions[0])),
                        'local': local.tolist()}
        if self.mode == "fireball" and self.option.phase=="ready" and self.sign=="open" and t-self.sign_t<=c["stale"] and t - self.fireball_at >= c["throw_min_hold"]:
            speed = float(velocity @ facing)
            travel = float((positions[-1] - positions[0]) @ facing)
            if speed >= c["throw_speed"] and travel >= c["throw_displacement"]:
                world_v = np.linalg.lstsq(fit, world_positions, rcond=None)[0][1]
                if np.linalg.norm(world_v) > .1:
                    self.option.commit(t,tracked_forward_throw=True,open_hand=True)
                    self.mode = "idle"
                    self.activation_after = t + c["activation_cooldown"]
                    self.history.clear()
                    out.append(self._event("fireball_throw", t, committed=True, origin=world.tolist(), direction=unit(world_v).tolist(),
                                           velocity=(unit(world_v)*min(np.linalg.norm(world_v), 12)).tolist()))
        return out
