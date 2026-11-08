"""Band equipment memory. Snapping equips; Quest alone confirms deployment."""
from collections import deque


class FireballOption:
    def __init__(self,open_timeout=None):
        self.open_timeout=None;self.seen=deque(maxlen=256);self.reset()
    def reset(self):
        self.phase='idle';self.snap_t=None;self.ready_t=None;self.last_sign='none'
    def expire(self,t):
        return []  # Equipment does not expire merely because time passes.
    def snap(self,t,event_id,fist_confirmed=False):
        if event_id in self.seen:return []
        self.seen.append(event_id)
        self.phase='ready';self.snap_t=self.ready_t=t
        return [{'event':'fireball_equipped','t':t,'committed':False}]
    def state(self,label,t,fist_confirmed=True,open_confirmed=True):
        self.last_sign=label
        if label=='fist' and fist_confirmed and self.phase=='ready' and t>self.snap_t:
            self.phase='idle';self.snap_t=self.ready_t=None
            return [{'event':'fireball_cancel','reason':'fist','t':t}]
        return []
    def shield(self,t,confirmed=False):
        if confirmed and self.phase=='ready' and t>self.snap_t:
            self.phase='idle';self.snap_t=self.ready_t=None
            return [{'event':'fireball_cancel','reason':'shield','t':t}]
        return []
    def commit(self,t,*,tracked_forward_throw=False,open_hand=False):
        if self.phase=='ready' and tracked_forward_throw and open_hand:
            self.phase='idle';self.snap_t=self.ready_t=None
            return [{'event':'fireball_commit','t':t}]
        return []
