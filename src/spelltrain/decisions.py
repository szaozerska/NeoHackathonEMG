"""Causal decision memory for live presentation; does not change fitted models."""
from collections import deque
import math


class DecisionMemory:
    """Smooth probability evidence and require sustained changes (hysteresis).

    Time is the sensor feature clock, so file-delivery bursts don't compress
    many evidence frames into one receipt instant. Ambiguity holds are bounded.
    """
    labels=('none','fist','open')
    def __init__(self,tau=.12,history_seconds=.8):
        self.tau=tau;self.history_seconds=history_seconds;self.reset()

    def reset(self):
        self.label='none';self.probabilities=None;self.last_t=None
        self.pending=None;self.pending_since=None;self.last_support=None
        self.history=deque()

    def feed(self,probabilities,t):
        p={label:float(probabilities.get(label,0.)) for label in self.labels}
        if not math.isfinite(t) or any(not math.isfinite(v) or v<0 for v in p.values()) or sum(p.values())<=0:
            raise ValueError('Bad decision probabilities or timestamp')
        total=sum(p.values());p={k:v/total for k,v in p.items()}
        if self.last_t is not None and (t<=self.last_t or t-self.last_t>.3):self.reset()
        dt=0 if self.last_t is None else t-self.last_t
        if self.probabilities is None:self.probabilities=p
        else:
            alpha=1-math.exp(-dt/self.tau)
            self.probabilities={k:self.probabilities[k]+alpha*(p[k]-self.probabilities[k]) for k in self.labels}
        self.last_t=t;self.history.append((t,p))
        while self.history and t-self.history[0][0]>self.history_seconds:self.history.popleft()
        smooth=self.probabilities;best=max(smooth,key=smooth.get)
        margin=smooth[best]-max(v for k,v in smooth.items() if k!=best)
        if self.last_support is None:self.last_support=t
        if best==self.label and smooth[self.label]>=.48:self.last_support=t
        target=None;dwell=.10
        if best!=self.label:
            if best=='none':
                if smooth['none']>=.62 and margin>=.16:target='none';dwell=.22
            elif smooth[best]>=.60 and margin>=.12:
                target=best;dwell=.08 if best=='open' and self.label=='fist' else .10
        if target is None:
            self.pending=None;self.pending_since=None
        elif target!=self.pending:
            self.pending=target;self.pending_since=t
        elif t-self.pending_since>=dwell:
            self.label=target;self.last_support=t;self.pending=None;self.pending_since=None
        # Never keep an active gesture indefinitely on uncertain evidence.
        if self.label!='none' and t-self.last_support>.75:
            self.label='none';self.pending=None;self.pending_since=None;self.last_support=t
        return self.label


class EffortMemory:
    def __init__(self,tau=.25):self.tau=tau;self.reset()
    def reset(self):self.probabilities=None;self.last_t=None;self.label=None;self.pending=None;self.since=None
    def feed(self,p,t):
        if self.last_t is not None and (t<=self.last_t or t-self.last_t>.3):self.reset()
        if self.probabilities is None:self.probabilities=dict(p)
        else:
            alpha=1-math.exp(-(t-self.last_t)/self.tau)
            self.probabilities={k:self.probabilities[k]+alpha*(p[k]-self.probabilities[k]) for k in p}
        self.last_t=t;best=max(self.probabilities,key=self.probabilities.get)
        if self.label is None:self.label=best
        if best!=self.label and self.probabilities[best]-self.probabilities[self.label]>=.12:
            if best!=self.pending:self.pending=best;self.since=t
            elif t-self.since>=.15:self.label=best;self.pending=None
        else:self.pending=None
        return {'label':self.label,'index':sum(self.probabilities[k]*v for k,v in [('light',0.),('medium',.5),('firm',1.)])}
