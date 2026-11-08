"""Auditable band/host timing and Kinesis-compatible forearm telemetry."""
from collections import deque
import math


class SensorTiming:
    def __init__(self):
        self.epoch=0;self.stream=None;self.connection=None;self.hand=None;self.reset()

    def reset(self):
        self.epoch+=1;self.baseline=None;self.last_host=None;self.last_band=None
        self.samples={};self.latest={};self.pose=None;self.kind_last_band={}

    def identity(self,stream=None,connection=None,hand=None):
        changed=(stream is not None and self.stream is not None and stream!=self.stream) or (
            connection is not None and self.connection is not None and connection!=self.connection)
        if changed:self.reset()
        if stream is not None:self.stream=stream
        if connection is not None:self.connection=connection
        if hand in ('left','right'):self.hand=hand

    def observe(self,kind,band_us,host,received,values=None):
        if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (band_us,host,received)):return None
        band=band_us/1e6
        previous_band=self.kind_last_band.get(kind)
        if previous_band is not None and band<previous_band-1:self.reset()
        self.kind_last_band[kind]=band
        offset=host-band
        # Port of Kinesis ArrivalDelay: relative excess delay, not absolute transit.
        self.baseline=offset if self.baseline is None else min(self.baseline+max(0,host-self.last_host)*.0005,offset)
        self.last_host,self.last_band=host,band
        row={'clock_epoch':self.epoch,'band_timestamp_us':band_us,'kinesis_received_host_uptime':host,
            'python_received_host_uptime':received,'kinesis_to_python_seconds':received-host,
            'band_to_host_offset_estimate_seconds':self.baseline,
            'mapped_band_host_uptime_estimate':band+self.baseline,
            'arrival_delay_excess_estimate_seconds':max(0,offset-self.baseline),
            'delay_basis':'excess over lowest observed band/host offset; absolute radio latency unknown'}
        points=self.samples.setdefault(kind,deque(maxlen=2048));points.append((band,host))
        self.latest[kind]=row
        if kind=='orientation' and self.hand in ('left','right') and isinstance(values,(list,tuple)) and len(values)==4:
            if all(isinstance(v,(int,float)) and math.isfinite(v) for v in values):
                norm=sum(v*v for v in values)
                if .9<=norm<=1.1:
                    w,x,y,z=(v/math.sqrt(norm) for v in values);sign=-1 if self.hand=='left' else 1
                    fx,fy,fz=2*(x*y-w*z)*sign,(1-2*(x*x+z*z))*sign,2*(y*z+w*x)*sign
                    self.pose={'forearm_elevation_degrees':math.degrees(math.asin(max(-1,min(1,fz)))),
                        'forearm_compass_degrees':math.degrees(math.atan2(fy,fx)) if math.hypot(fx,fy)>1e-6 else None,
                        'hand':self.hand,'host_uptime':host,'compass_is_absolute_north':False,
                        'convention':'Kinesis ForearmAim: wxyz, world +z up, right forearm +body-y; left sign reversed'}
                    row.update({k:self.pose[k] for k in ('forearm_elevation_degrees','forearm_compass_degrees')})
        return row

    def status(self,now):
        rates={};host_rates={}
        for kind,points in self.samples.items():
            recent=[(band,host) for band,host in points if now-host<=2]
            span=recent[-1][0]-recent[0][0] if len(recent)>1 else 0
            rates[kind]=(len(recent)-1)/span if span>0 else None
            host_span=recent[-1][1]-recent[0][1] if len(recent)>1 else 0
            host_rates[kind]=(len(recent)-1)/host_span if host_span>0 else None
        latest=max(self.latest.values(),key=lambda row:row['kinesis_received_host_uptime']) if self.latest else None
        return {'clock_epoch':self.epoch,'delivered_sensor_hz':rates,
            'host_delivery_hz':host_rates,
            'arrival_delay_excess_estimate_seconds':latest['arrival_delay_excess_estimate_seconds'] if latest and now-latest['kinesis_received_host_uptime']<2 else None,
            'kinesis_to_python_seconds':latest['kinesis_to_python_seconds'] if latest and now-latest['kinesis_received_host_uptime']<2 else None,
            'forearm':self.pose if self.pose and now-self.pose['host_uptime']<2 else None,
            'absolute_radio_latency_known':False,'emg_timestamp_policy':'native batch timestamp preserved; 16 samples at 2048 Hz, within-batch timestamp convention has not been hardware calibrated'}
