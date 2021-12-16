#!/usr/bin/env python3
import os
import sys
import unittest
from time import sleep
import datetime
import calendar
import logging

# our own packages
test_dir = os.path.dirname(__file__)
sys.path.insert(0, test_dir)
sys.path.insert(1, os.path.join(test_dir, '..', 'ext', 'velib_python', 'test'))
sys.path.insert(1, os.path.join(test_dir, '..'))
import dbus_tempsensor_relay
import mock_glib
from mock_dbus_monitor import MockDbusMonitor
from mock_dbus_service import MockDbusService
from mock_settings_device import MockSettingsDevice

dbus_tempsensor_relay.logger = logging.getLogger()

class MockTempRelay(dbus_tempsensor_relay.DBusTempSensorRelay):

	def _create_dbus_monitor(self, *args, **kwargs):
		return MockDbusMonitor(*args, **kwargs)

	def _create_settings(self, *args, **kwargs):
		self._settings = MockSettingsDevice(*args, **kwargs)
		return self._settings

	def _create_dbus_service(self):
		return MockDbusService('com.victronenergy.temprelay')


class TestTempRelayBase(unittest.TestCase):
	def __init__(self, methodName='runTest'):
		unittest.TestCase.__init__(self, methodName)

	def setUp(self):
		mock_glib.timer_manager.reset()
		self._temprelay_ = MockTempRelay()
		self._monitor = self._temprelay_._dbusmonitor

	def _update_values(self, interval=1000):
		if not self._service:
			self._service = self._temprelay_.dbusservice
		mock_glib.timer_manager.add_terminator(interval)
		mock_glib.timer_manager.start()

	def _add_device(self, service, values, connected=True, product_name='dummy', connection='dummy', instance=0):
		values['/Connected'] = 1 if connected else 0
		values['/ProductName'] = product_name
		values['/Mgmt/Connection'] = connection
		values.setdefault('/DeviceInstance', instance)
		self._monitor.add_service(service, values)

	def _remove_device(self, service):
		self._monitor.remove_service(service)

	def _set_setting(self, path, value):
		self._temprelay_._settings[self._temprelay_._settings.get_short_name(path)] = value
	
	def _set_value(self, path, value):
		self._temprelay_.dbusservice.set_value(path, value)

	def _check_values(self, values):
		ok = True
		for k, v in values.items():
			v2 = self._service[k] if k in self._service else None
			if isinstance(v, (int, float)) and v2 is not None:
				d = abs(v - v2)
				if d > 1e-6:
					ok = False
					break
			else:
				if v != v2:
					ok = False
					break
		if ok:
			return
		msg = ''
		for k, v in values.items():
			msg += '{0}:\t{1}'.format(k, v)
			if k in self._service:
				msg += '\t{}'.format(self._service[k])
			msg += '\n'
		self.assertTrue(ok, msg)


class TestTempRelay(TestTempRelayBase):
	def __init__(self, methodName='runTest'):
		TestTempRelayBase.__init__(self, methodName)

	def setUp(self):
		TestTempRelayBase.setUp(self)

		self._add_device('com.victronenergy.system',
			product_name='SystemCalc',
			values={
				'/Relay/0/State': 0,
				'/Relay/1/State': 0
				})

		self._add_device('com.victronenergy.settings',
			values={
				'/Settings/Relay/Function': 0,
				'/Settings/Relay/1/Function': 1
			})

		self._add_device('com.victronenergy.temperature.adc_builtin0_6',
			values={
				'/Temperature': 15,
			})

		# DBus service is not created till Settings/Relay/Function is 1
		self._service = self._temprelay_.dbusservice


	def test_conditions(self):
		self._monitor.set_value('com.victronenergy.system', '/Relay/0/State', 0)
		self._monitor.set_value('com.victronenergy.system', '/Relay/1/State', 0)
		self._monitor.set_value('com.victronenergy.settings', '/Settings/Relay/Function', 4)
		self._monitor.set_value('com.victronenergy.settings', '/Settings/Relay/1/Function', 4)

		self._monitor.set_value('com.victronenergy.temperature.adc_builtin0_6', '/Temperature', 32)
				
		self._set_setting('/Settings/TempSensorRelay/adc_builtin0_6/Enabled', 1) # Disabled = 0, Enabled = 1
		self._update_values()

		self._set_value('/Sensor/adc_builtin0_6/0/Relay', 0)
		self._set_value('/Sensor/adc_builtin0_6/0/SetValue', 30)
		self._set_value('/Sensor/adc_builtin0_6/0/ClearValue', 25)

		self._set_value('/Sensor/adc_builtin0_6/1/Relay', 1)
		self._set_value('/Sensor/adc_builtin0_6/1/SetValue', 5)
		self._set_value('/Sensor/adc_builtin0_6/1/ClearValue', 10)

		self._update_values()

		self._check_values({
			'/Sensor/adc_builtin0_6/0/State': 1,
			'/Sensor/adc_builtin0_6/1/State': 0
			})

		self._monitor.set_value('com.victronenergy.temperature.adc_builtin0_6', '/Temperature', 21)
		self._update_values()
		self._check_values({
			'/Sensor/adc_builtin0_6/0/State': 0,
			'/Sensor/adc_builtin0_6/1/State': 0
			})

		self._monitor.set_value('com.victronenergy.temperature.adc_builtin0_6', '/Temperature', 4)
		self._update_values()
		self._check_values({
			'/Sensor/adc_builtin0_6/0/State': 0,
			'/Sensor/adc_builtin0_6/1/State': 1
			})

		self._monitor.set_value('com.victronenergy.temperature.adc_builtin0_6', '/Temperature', 8)
		self._update_values()
		self._check_values({
			'/Sensor/adc_builtin0_6/0/State': 0,
			'/Sensor/adc_builtin0_6/1/State': 1
			})

		self._monitor.set_value('com.victronenergy.temperature.adc_builtin0_6', '/Temperature', 10)
		self._update_values()
		self._check_values({
			'/Sensor/adc_builtin0_6/0/State': 0,
			'/Sensor/adc_builtin0_6/1/State': 0
			})
	
	def test_add_tempesensor(self):
		self._update_values()
		self._monitor.set_value('com.victronenergy.settings', '/Settings/Relay/1/Function', 4)

		self._add_device('com.victronenergy.temperature.ruuvi_c66a72222d16',
			values={
				'/Temperature': 15,
			})
		self._update_values()
		self._set_value('/Sensor/ruuvi_c66a72222d16/1/Relay', 1)
		self._set_value('/Sensor/ruuvi_c66a72222d16/1/SetValue', 16)
		self._set_value('/Sensor/ruuvi_c66a72222d16/1/ClearValue', 25)
		self._update_values()
		self._set_setting('/Settings/TempSensorRelay/ruuvi_c66a72222d16/Enabled', 0)
		self._check_values({
			'/Sensor/adc_builtin0_6/0/State': 0,
			'/Sensor/adc_builtin0_6/1/State': 0
			})
		self._set_setting('/Settings/TempSensorRelay/ruuvi_c66a72222d16/Enabled', 1)
		self._update_values()
		self._check_values({
			'/Sensor/ruuvi_c66a72222d16/0/State': 0,
			'/Sensor/ruuvi_c66a72222d16/1/State': 1
			})
	
	def test_swap_relays(self):
		self._monitor.set_value('com.victronenergy.settings', '/Settings/Relay/Function', 4)
		self._monitor.set_value('com.victronenergy.settings', '/Settings/Relay/1/Function', 4)
		self._monitor.set_value('com.victronenergy.temperature.adc_builtin0_6', '/Temperature', 32)
		self._set_setting('/Settings/TempSensorRelay/adc_builtin0_6/Enabled', 1) # Disabled = 0, Enabled = 1
		self._update_values()

		self._set_value('/Sensor/adc_builtin0_6/0/Relay', 0)
		self._set_value('/Sensor/adc_builtin0_6/0/SetValue', 32)
		self._set_value('/Sensor/adc_builtin0_6/0/ClearValue', 25)

		self._update_values()


		relay0_state = self._monitor.get_value('com.victronenergy.system', '/Relay/0/State')
		relay1_state = self._monitor.get_value('com.victronenergy.system', '/Relay/1/State')

		self._check_values({
			'/Sensor/adc_builtin0_6/0/State': 1,
			'/Sensor/adc_builtin0_6/1/State': 0
			})
		self.assertTrue(relay0_state == 1)
		self.assertTrue(relay1_state == 0)
		
		self._set_value('/Sensor/adc_builtin0_6/0/Relay', 1)
		self._update_values()

		relay0_state = self._monitor.get_value('com.victronenergy.system', '/Relay/0/State')
		relay1_state = self._monitor.get_value('com.victronenergy.system', '/Relay/1/State')

		self._check_values({
			'/Sensor/adc_builtin0_6/0/State': 1,
			'/Sensor/adc_builtin0_6/1/State': 0
			})
		self.assertTrue(relay0_state == 0)
		self.assertTrue(relay1_state == 1)

	def test_function_disable(self):
		self._monitor.set_value('com.victronenergy.system', '/Relay/0/State', 0)
		self._monitor.set_value('com.victronenergy.system', '/Relay/1/State', 0)
		self._monitor.set_value('com.victronenergy.settings', '/Settings/Relay/Function', 4)
		self._monitor.set_value('com.victronenergy.settings', '/Settings/Relay/1/Function', 4)

		self._monitor.set_value('com.victronenergy.temperature.adc_builtin0_6', '/Temperature', 32)
				
		self._set_setting('/Settings/TempSensorRelay/adc_builtin0_6/Enabled', 1) # Disabled = 0, Enabled = 1
		self._update_values()

		self._set_value('/Sensor/adc_builtin0_6/0/Relay', 0)
		self._set_value('/Sensor/adc_builtin0_6/0/SetValue', 30)
		self._set_value('/Sensor/adc_builtin0_6/0/ClearValue', 25)

		self._set_value('/Sensor/adc_builtin0_6/1/Relay', 1)
		self._set_value('/Sensor/adc_builtin0_6/1/SetValue', 5)
		self._set_value('/Sensor/adc_builtin0_6/1/ClearValue', 10)

		self._update_values()

		self._check_values({
			'/Sensor/adc_builtin0_6/0/State': 1,
			'/Sensor/adc_builtin0_6/1/State': 0
			})

		self._set_setting('/Settings/TempSensorRelay/adc_builtin0_6/Enabled', 0) # Disabled = 0, Enabled = 1
		self._update_values()
		self._check_values({
			'/Sensor/adc_builtin0_6/0/State': 0,
			'/Sensor/adc_builtin0_6/1/State': 0
			})

		# Five minutes
		for i in range(0, 301):
			self._update_values()
		
		self._check_values({
			'/Sensor/adc_builtin0_6/0/State': 0,
			'/Sensor/adc_builtin0_6/1/State': 0
			})

	def test_invalid_measuerement(self):
		self._monitor.set_value('com.victronenergy.system', '/Relay/0/State', 0)
		self._monitor.set_value('com.victronenergy.system', '/Relay/1/State', 0)
		self._monitor.set_value('com.victronenergy.settings', '/Settings/Relay/Function', 4)
		self._monitor.set_value('com.victronenergy.settings', '/Settings/Relay/1/Function', 4)

		self._monitor.set_value('com.victronenergy.temperature.adc_builtin0_6', '/Temperature', 32)
				
		self._set_setting('/Settings/TempSensorRelay/adc_builtin0_6/Enabled', 1) # Disabled = 0, Enabled = 1
		self._update_values()

		self._set_value('/Sensor/adc_builtin0_6/0/Relay', 0)
		self._set_value('/Sensor/adc_builtin0_6/0/SetValue', 30)
		self._set_value('/Sensor/adc_builtin0_6/0/ClearValue', 25)

		self._set_value('/Sensor/adc_builtin0_6/1/Relay', 1)
		self._set_value('/Sensor/adc_builtin0_6/1/SetValue', 5)
		self._set_value('/Sensor/adc_builtin0_6/1/ClearValue', 10)

		self._update_values()

		self._check_values({
			'/Sensor/adc_builtin0_6/0/State': 1,
			'/Sensor/adc_builtin0_6/1/State': 0
			})

		# Invalid measurement
		self._monitor.set_value('com.victronenergy.temperature.adc_builtin0_6', '/Temperature', None)

		# During 300 retries (~5 minutes) condition is not evaluated and the state prior to the invalid
		# measurement is kept
		for i in range(0, 299):
			self._update_values()
			self._check_values({
				'/Sensor/adc_builtin0_6/0/State': 1,
				'/Sensor/adc_builtin0_6/1/State': 0
				})
		
		# After five minutes, the relay is released
		self._update_values()
		self._check_values({
				'/Sensor/adc_builtin0_6/0/State': 0,
				'/Sensor/adc_builtin0_6/1/State': 0
				})
		
		# Once measurement is valid again, condition evaluation is restarted
		self._monitor.set_value('com.victronenergy.temperature.adc_builtin0_6', '/Temperature', 32)
		self._update_values()
		self._check_values({
			'/Sensor/adc_builtin0_6/0/State': 1,
			'/Sensor/adc_builtin0_6/1/State': 0
			})
		
		# Intermitent invalid values, only after 300 retries in a row, condition must reset
		self._monitor.set_value('com.victronenergy.temperature.adc_builtin0_6', '/Temperature', None)
		for i in range(0, 200):
			self._update_values()
			self._check_values({
				'/Sensor/adc_builtin0_6/0/State': 1,
				'/Sensor/adc_builtin0_6/1/State': 0
				})

		self._monitor.set_value('com.victronenergy.temperature.adc_builtin0_6', '/Temperature', 32)
		self._update_values()
		self._check_values({
			'/Sensor/adc_builtin0_6/0/State': 1,
			'/Sensor/adc_builtin0_6/1/State': 0
			})
		self._monitor.set_value('com.victronenergy.temperature.adc_builtin0_6', '/Temperature', None)
		for i in range(0, 200):
			self._update_values()
			self._check_values({
				'/Sensor/adc_builtin0_6/0/State': 1,
				'/Sensor/adc_builtin0_6/1/State': 0
				})

	def test_same_relay_conditions(self):
		self._monitor.set_value('com.victronenergy.system', '/Relay/0/State', 0)
		self._monitor.set_value('com.victronenergy.system', '/Relay/1/State', 0)
		self._monitor.set_value('com.victronenergy.settings', '/Settings/Relay/Function', 4)
		self._monitor.set_value('com.victronenergy.settings', '/Settings/Relay/1/Function', 4)

		self._monitor.set_value('com.victronenergy.temperature.adc_builtin0_6', '/Temperature', 32)
				
		self._set_setting('/Settings/TempSensorRelay/adc_builtin0_6/Enabled', 1) # Disabled = 0, Enabled = 1
		self._update_values()

		self._set_value('/Sensor/adc_builtin0_6/0/Relay', 0)
		self._set_value('/Sensor/adc_builtin0_6/0/SetValue', 30)
		self._set_value('/Sensor/adc_builtin0_6/0/ClearValue', 25)

		self._set_value('/Sensor/adc_builtin0_6/1/Relay', 0)
		self._set_value('/Sensor/adc_builtin0_6/1/SetValue', 5)
		self._set_value('/Sensor/adc_builtin0_6/1/ClearValue', 10)

		# Condition 0 and relay 0 must be active
		self._update_values()
		relay0_state = self._monitor.get_value('com.victronenergy.system', '/Relay/0/State')
		relay1_state = self._monitor.get_value('com.victronenergy.system', '/Relay/1/State')
		self._check_values({
			'/Sensor/adc_builtin0_6/0/State': 1,
			'/Sensor/adc_builtin0_6/1/State': 0
			})
		self.assertTrue(relay0_state == 1)
		self.assertTrue(relay1_state == 0)

		# Condition 1 and relay 0 must be active
		self._monitor.set_value('com.victronenergy.temperature.adc_builtin0_6', '/Temperature', 4)
		self._update_values()
		relay0_state = self._monitor.get_value('com.victronenergy.system', '/Relay/0/State')
		relay1_state = self._monitor.get_value('com.victronenergy.system', '/Relay/1/State')
		self.assertTrue(relay0_state == 1)
		self.assertTrue(relay1_state == 0)

		self._check_values({
			'/Sensor/adc_builtin0_6/0/State': 0,
			'/Sensor/adc_builtin0_6/1/State': 1
			})

		# Condition 0 and 1 must be inactive and relay 0 open
		self._monitor.set_value('com.victronenergy.temperature.adc_builtin0_6', '/Temperature', 11)
		self._update_values()
		relay0_state = self._monitor.get_value('com.victronenergy.system', '/Relay/0/State')
		relay1_state = self._monitor.get_value('com.victronenergy.system', '/Relay/1/State')
		self.assertTrue(relay0_state == 0)
		self.assertTrue(relay1_state == 0)
		self._check_values({
			'/Sensor/adc_builtin0_6/0/State': 0,
			'/Sensor/adc_builtin0_6/1/State': 0
			})


if __name__ == '__main__':
	# patch dbus_generator with mock glib
	dbus_tempsensor_relay.GLib = mock_glib
	unittest.main()