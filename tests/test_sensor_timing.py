import math

import pytest

from spelltrain.sensor_timing import SensorTiming


def test_band_clock_mapping_and_relative_backlog_keep_ipc_delay_separate():
    timing=SensorTiming()
    first=timing.observe('gyro',1_000_000,101,101.003)
    assert first['mapped_band_host_uptime_estimate']==101
    second=timing.observe('gyro',2_000_000,102.2,102.207)
    assert second['arrival_delay_excess_estimate_seconds']==pytest.approx(.1994)
    assert second['kinesis_to_python_seconds']==pytest.approx(.007)
    # A delayed sample from another sensor is not evidence of a restarted clock.
    epoch=timing.epoch
    delayed=timing.observe('orientation',500_000,102.21,102.212,[1,0,0,0])
    assert timing.epoch==epoch and delayed['arrival_delay_excess_estimate_seconds']>1


def test_native_wxyz_forearm_angles_match_kinesis_and_compass_is_relative():
    timing=SensorTiming();timing.identity(hand='right')
    timing.observe('orientation',0,10,10,[1,0,0,0])
    pose=timing.status(10)['forearm']
    assert pose['forearm_elevation_degrees']==0 and pose['forearm_compass_degrees']==90
    q=[math.sqrt(.5),math.sqrt(.5),0,0]
    timing.observe('orientation',1000,10.001,10.001,q)
    pose=timing.status(10.001)['forearm']
    assert pose['forearm_elevation_degrees']==pytest.approx(90) and pose['forearm_compass_degrees'] is None
    assert not pose['compass_is_absolute_north']
    timing.identity(hand='left');timing.observe('orientation',2000,10.002,10.002,[1,0,0,0])
    assert timing.status(10.002)['forearm']['forearm_compass_degrees']==-90


def test_measured_hz_and_connection_epochs_reset_instead_of_mixing_clocks():
    timing=SensorTiming();timing.identity(stream='a',connection='band-a',hand='right')
    for i in range(129):timing.observe('gyro',i*1e6/128,100+i/128,100+i/128)
    assert timing.status(101)['delivered_sensor_hz']['gyro']==pytest.approx(128)
    epoch=timing.epoch;timing.identity(connection='band-b')
    assert timing.epoch==epoch+1 and timing.status(101)['delivered_sensor_hz']=={}
    assert timing.status(101)['arrival_delay_excess_estimate_seconds'] is None


def test_missing_orientation_or_unknown_wrist_does_not_invent_angles():
    timing=SensorTiming();timing.observe('emg',0,100,100)
    assert timing.status(100)['forearm'] is None
    timing.observe('orientation',0,100,100,[1,0,0,0])
    assert timing.status(100)['forearm'] is None
