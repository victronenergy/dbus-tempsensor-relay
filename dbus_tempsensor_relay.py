#!/usr/bin/python3 -u
# -*- coding: utf-8 -*-

from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
from enum import Enum
import dbus
import dbus.service
import os
import argparse
import sys
import os
import re

# Victron packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), './ext/velib_python'))
from vedbus import VeDbusService
from vedbus import VeDbusItemImport
from ve_utils import exit_on_error
from dbusmonitor import DbusMonitor
from settingsdevice import SettingsDevice
from logger import setup_logging

softwareVersion = '1.3'

READ_RETRIES = 300

class DBusTempSensorRelay:
	def __init__(self):
		self.relay_state_import = None
		self.bus = dbus.SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else dbus.SystemBus()
		self.dbusservice = None
		self.evaluationpending = True

		dummy = {'code': None, 'whenToLog': 'configChange', 'accessLevel': None}
		dbus_tree = {
				'com.victronenergy.settings': { # Not our settings
					'/Settings/Relay/Function': dummy,
					'/Settings/Relay/1/Function': dummy
				},
				'com.victronenergy.system': {
					'/Relay/0/State': dummy,
					'/Relay/1/State': dummy
				},
				'com.victronenergy.temperature': {
					'/Connected': dummy,
					'/ProductName': dummy,
					'/Temperature': dummy,
					'/Mgmt/Connection': dummy
				}
			}

		self._dbusmonitor = self._create_dbus_monitor(dbus_tree, valueChangedCallback=self._dbus_value_changed,
				deviceAddedCallback=self._device_added, deviceRemovedCallback=self._device_removed)

		self._statusList = {}
		self._relaysList = {
			'com.victronenergy.settings/Settings/Relay/Function': {
				'state': 'com.victronenergy.system/Relay/0/State',
				'configured': False
			},
			'com.victronenergy.settings/Settings/Relay/1/Function': {
				'state': 'com.victronenergy.system/Relay/1/State',
				'configured': False
			}
		}

		# Connect to localsettings
		supportedSettings={
				'mode': ['/Settings/TempSensorRelay/Mode', 0, 0, 100]  # Auto = 0, On = 1, Off = 2
			}
		self.settings = self._create_settings(supportedSettings, self._handle_changed_setting)
		GLib.timeout_add(1000, exit_on_error, self._handletimertick)

	def _update_relays_config(self):
		for i in self._relaysList:
			self._relay_configuration_changed(i, self._check_relay_function(i))

	def _release_relays(self):
		for i in self._relaysList:
			self._switchRelay(self._relaysList[i]['state'], 0)

	def _create_settings(self, *args, **kwargs):
		return SettingsDevice(self.bus, *args, timeout=10, **kwargs)

	def _create_dbus_monitor(self, *args, **kwargs):
		return DbusMonitor(*args, **kwargs)

	def _create_dbus_service(self):
		dbusservice = VeDbusService("com.victronenergy.temprelay")
		dbusservice.add_mandatory_paths(
			processname=__file__,
			processversion=softwareVersion,
			connection='temprelay',
			deviceinstance=0,
			productid=None,
			productname=None,
			firmwareversion=None,
			hardwareversion=None,
			connected=1)
		return dbusservice

	def _evaluate_if_we_are_needed(self):
		if self._relays_configured():
			if self.dbusservice is None:
				logger.info('Action! Going on dbus and taking control of the relay.')
				self.dbusservice = self._create_dbus_service()
				self.dbusservice.add_path('/State', value=0)
				self.dbusservice.add_path('/AvailableTemperatureServices', value=None)
				self.dbusservice.add_path('/Sensor', value=None)
				self._update_relays_config()
				self._get_sensors()
		else:
			if self.dbusservice is not None:
				self._release_relays()
				self.dbusservice.__del__()
				self.dbusservice = None
				self._statusList = {}
				self.relay_state_import = None
				logger.info('No relay is set to temperature funtion: make sure the relay is released and going off dbus')
		self.evaluationpending = False

	def _handletimertick(self):
		if self.evaluationpending:
			self._evaluate_if_we_are_needed()
			return True

		if self.dbusservice == None:
			return True

		try:
			for sensorId in self._statusList:
				# Update temperatures
				self._checkTemp(self._getService(sensorId))
				# Update conditions
				self._checkValues(self._getService(sensorId))
			self._checkRelay()

		except:
			import traceback
			traceback.print_exc()
			sys.exit(1)
		return True

	def _path_to_setting(self, path):
		p = path.replace('/Sensor/', '')
		if len(p.split('/')) > 2:
			s = 'c{1}{2}_{0}'.format(*p.split('/'))
		else:
			s = '{1}_{0}'.format(*p.split('/'))
		return s

	def _setting_to_path(self, setting):
		c = re.match(r'^c[0-9]+', setting).group(0).replace('c', '')
		a = [setting.split('_', 1)[1], c, re.sub(r'^c[0-9]+','', setting).split('_')[0]]
		return '{0}/{1}/{2}'.format(*a)

	def _handle_changed_setting(self, setting, oldvalue, newvalue):

		if re.match(r'^c[0-9]+', setting):
			self.dbusservice['/Sensor/' + self._setting_to_path(setting)] = newvalue

		if 'c0Relay' in setting or 'c1Relay' in setting:
			sensor = setting.split("_", 1)[1]
			condition = setting[1]
			logger.info('Sensor %s condition %s is now driving relay %s', sensor, condition, newvalue )

		if 'enable_' in setting:
			service = setting.split("_", 1)[1]
			logger.info('Temperature relay function for service %s: %s.', service, ('Enabled' if newvalue == 1 else 'Disabled'))
			if newvalue == 1:
				self._add_sensor_to_service(service)

	def _check_relay_function(self, relay):
		return self._dbusmonitor.get_value(relay.split('/')[0], '/' + relay.split('/', 1)[1]) == 4

	def _relay_configuration_changed(self, relay, enabled):
		if not enabled:
			if (self._relaysList[relay]['configured']):
				self._switchRelay(self._relaysList[relay]['state'], 0)
			self._relaysList[relay]['configured'] = False
		else:
			self._relaysList[relay]['configured'] = True
		self._evaluate_if_we_are_needed()

	def _relays_configured(self):
		for i in self._relaysList:
			if self._check_relay_function(i):
				return True

	def _get_relay_config_path(self, instance):
		# "Instaces" elay 0 and 1 refer to the built-in relays
		service = ""
		if instance == 0:
			service = "com.victronenergy.settings/Settings/Relay/Function"
		elif instance == 1:
			service = "com.victronenergy.settings/Settings/Relay/1/Function"
		return service

	# Find temperature sensor services
	def _get_sensors(self):
		for service in self._dbusmonitor.get_service_list(classfilter='com.victronenergy.temperature'):
			if 'com.victronenergy.temperature' in service:
				self._addTempService(self._getSensorId(service))

	def _addTempService(self, serviceName):
		settings = {}
		deviceSettingsBase = {
			'Enabled_{0}': ['/Settings/TempSensorRelay/{0}/Enabled', 0, 0, 2],  # Disabled = 0, Enabled = 1
			'c0Relay_{0}': ['/Settings/TempSensorRelay/{0}/0/Relay', -1, -1, 100],
			'c0SetValue_{0}': ['/Settings/TempSensorRelay/{0}/0/SetValue', 0, -100, 100],  
			'c0ClearValue_{0}': ['/Settings/TempSensorRelay/{0}/0/ClearValue', 0, -100, 100],
			'c1Relay_{0}': ['/Settings/TempSensorRelay/{0}/1/Relay', -1, -1, 100],
			'c1SetValue_{0}': ['/Settings/TempSensorRelay/{0}/1/SetValue', 0, -100, 100],  
			'c1ClearValue_{0}': ['/Settings/TempSensorRelay/{0}/1/ClearValue', 0, -100, 100]
		}
		for s in deviceSettingsBase:
			v = deviceSettingsBase[s][:]  # Copy
			v[0] = v[0].format(serviceName)
			settings[s.format(serviceName)] = v
		self.settings.addSettings(settings)

		if serviceName not in self._statusList:
			self._statusList[serviceName] = {
				'enabled': False,
				'c0Active': False,
				'c1Active': False,
				'attempts': 0,
				'temperature': None,
				'c0Relay': '',
				'c1Relay': ''
			}
			self._add_sensor_to_service(serviceName)

	def _add_sensor_to_service(self, sensor):
		settings = ['SetValue', 'ClearValue', 'Relay']
		sensorprefix = '/Sensor/' + sensor
		if self.dbusservice != None and (sensorprefix + "/Enabled") not in self.dbusservice:
			enabledval = self.settings[self._path_to_setting(sensorprefix + '/Enabled')]
			self.dbusservice.add_path(sensorprefix + '/Enabled', None, writeable=True, onchangecallback=self._handleServiceValueChange)
			self.dbusservice[sensorprefix + '/Enabled'] = enabledval
			self.dbusservice.add_path(sensorprefix + '/ServiceName', None)
			self.dbusservice[sensorprefix + '/ServiceName'] = self._getService(sensor)

			for i in range(0, 2):
				p = sensorprefix + '/'  + str(i) + '/'
				self.dbusservice.add_path(p + 'State', 0)
				for k in settings:
					val = self.settings[self._path_to_setting(p + k)]
					self.dbusservice.add_path(p + k, None, writeable=True, onchangecallback=self._handleServiceValueChange)
					self.dbusservice[p + k] = val


	def _handleServiceValueChange(self, path, newvalue):
		if '/Sensor/' not in path:
			return True
		self.settings[self._path_to_setting(path)] = int(newvalue)
		return True

	def _dbus_value_changed(self, dbusServiceName, dbusPath, options, changes, deviceInstance):
		if dbusServiceName == 'com.victronenergy.settings':
			if dbusServiceName + dbusPath in self._relaysList and changes != None:
				value =  int(changes['Value']) if not isinstance(changes, int) else changes
				logger.info('Function changed for relay %s: %s', dbusServiceName + dbusPath, value)
				self._relay_configuration_changed(dbusServiceName + dbusPath, value == 4) # Function 4 -> Temp sensor
				self.evaluationpending = True
		return

	def _device_removed(self, dbusservicename, instance):
		if 'com.victronenergy.temperature' in dbusservicename:
			sId = self._getSensorId(dbusservicename)
			if sId in self._statusList:
				logger.info('Service %s is no longer available, removing it...', dbusservicename)
				del self._statusList[sId]
				self._remove_sensor_form_dbus_service(sId)

	def _device_added(self, dbusservicename, instance):
		logger.info('Device added: %s', dbusservicename)
		if self.dbusservice == None:
			return
		if 'com.victronenergy.temperature' in dbusservicename:
			self._evaluate_if_we_are_needed()
			self._addTempService(self._getSensorId(dbusservicename))

	def _remove_sensor_form_dbus_service(self, sensor):
		items = ['SetValue', 'ClearValue', 'Relay', 'State']
		sp = '/Sensor/' + sensor
		self.dbusservice.__delitem__(sp + '/ServiceName')
		self.dbusservice.__delitem__(sp + '/Enabled')
		for i in range(0, 2):
			p = sp + '/'  + str(i) + '/'
			for k in items:
				self.dbusservice.__delitem__(p + k)

	def _checkTemp(self, service):
		sensorId = self._getSensorId(service)
		temperature = self._dbusmonitor.get_value(service, "/Temperature")
		self._statusList[sensorId]['temperature'] = temperature
		# In case of invalid temperature values keep track or retries
		if temperature is None:
			self._statusList[sensorId]['attempts'] += 1

	def _getSetting(self, setting, service):
		srvc = self._getSensorId(service)
		service = self._getSensorId(srvc)
		return self.settings[setting + "_" + srvc]

	def _checkValues(self, service):
		sensorId = self._getSensorId(service)
		c0Relay = self._get_relay_config_path(self._getSetting('c0Relay', service))
		c1Relay = self._get_relay_config_path(self._getSetting('c1Relay', service))
		mode = self._getSetting('Enabled', service)
		temperature = self._statusList[sensorId]['temperature']
		serviceStatus = self._statusList[sensorId]
		evaluate = True
		attempts = serviceStatus['attempts']

		# Update which relay belongs to each condition
		if serviceStatus['c0Relay'] != c0Relay:
			serviceStatus['c0Relay'] = str(c0Relay)

		if serviceStatus['c1Relay'] != c1Relay:
			serviceStatus['c1Relay'] = str(c1Relay)

		if mode == 0:
			if serviceStatus['c0Active'] or serviceStatus['c1Active']:
				logger.info('Relay driving for service %s has been disabled, releasing relays', service)
			serviceStatus['c0Active'] = 0
			serviceStatus['c1Active'] = 0
			return

		if attempts > 0 and attempts < READ_RETRIES:
			if temperature is not None:
				serviceStatus['attempts'] = 0
				logger.info('Value of %s temperature is valid again, resuming evaluation', service)
			if attempts > 0 and attempts < READ_RETRIES and attempts % 10 == 0:
				logger.info('Error reading %s temperature, retriying... [%s / %s]',
				service, attempts, READ_RETRIES)
			# Nothing to do, return and wait till the next read
			return
		elif attempts > 0 and attempts == READ_RETRIES:
			if temperature is not None:
				serviceStatus['attempts'] = 0
				logger.info('Value of %s temperature is valid again, resuming evaluation', service)
			else:
				logger.info('Error reading %s temperature after %s attepmts. Disabling relay driving for this condition.',
				service, attempts)
				serviceStatus['c0Active'] = 0
				serviceStatus['c1Active'] = 0
				return

		if c0Relay and c0Relay != "-1" and evaluate:
			c0Set = self._getSetting('c0SetValue', service)
			c0Clear = self._getSetting('c0ClearValue', service)
			inRange = self._inRange(c0Set, c0Clear, temperature, serviceStatus['c0Active'])
			serviceStatus['c0Active'] =  inRange and self._relaysList[c0Relay]['configured']

		if c1Relay and c1Relay != "-1" and evaluate:
			c1Set = self._getSetting('c1SetValue', service)
			c1Clear = self._getSetting('c1ClearValue', service)
			inRange = self._inRange(c1Set, c1Clear, temperature, serviceStatus['c1Active'])
			serviceStatus['c1Active'] =  inRange and self._relaysList[c1Relay]['configured']

	def _inRange(self, setVal, clearVal, val, active):
		if val == None:
			return False

		if setVal > clearVal:
			return val >= setVal or (active and val > clearVal)
		else:
			return val <= setVal or (active and val < clearVal)

	def _getSensorId(self, service):
		if 'com.victronenergy.temperature.' in service:
			return service.split('com.victronenergy.temperature.')[1]
		return service

	def _getService(self, sensorId):
		if 'com.victronenergy.temperature.' not in sensorId:
			return 'com.victronenergy.temperature.' + sensorId
		return sensorId

	def _checkRelay(self):
		relays = {}

		for k in self._relaysList:
			relays[k] = False

		# Determine the what the relays status should be based on active conditions
		for sensor in self._statusList:
			c0Relay = self._statusList[sensor]['c0Relay']
			c0Active = self._statusList[sensor]['c0Active']
			c1Relay = self._statusList[sensor]['c1Relay']
			c1Active = self._statusList[sensor]['c1Active']

			if (c0Relay):
				relays[c0Relay] |= c0Active

			if (c1Relay):
				relays[c1Relay] |= c1Active

			sensorspath = '/Sensor/' + sensor
			# Set the condition status in the service
			if self.dbusservice and sensorspath:
				self.dbusservice[sensorspath + "/0/State"] = c0Active
				self.dbusservice[sensorspath + "/1/State"] = c1Active

		# Activate or deactivate relays
		for confservice, state in relays.items():
			if (self._relaysList[confservice]['configured']):
				self._switchRelay(self._relaysList[confservice]['state'], state)

	def _switchRelay(self, relay, state):
		relayState = bool(self._dbusmonitor.get_value(relay.split('/')[0], '/' + relay.split('/', 1)[1]))
		if relayState != state:
			logger.info('Switching relay %s: %s', relay, "Activated" if state else "Deactivated")
			try:
				self._dbusmonitor.set_value(relay.split('/')[0], '/' + relay.split('/', 1)[1], dbus.Int32(state, variant_level=1))
			except:
				logger.info('Error setting relay state')


if __name__ == '__main__':
	# Argument parsing
	parser = argparse.ArgumentParser(
		description='Close and open relay based on temperature sensors values'
	)

	parser.add_argument('-d', '--debug', help='set logging level to debug',
						action='store_true')
	args = parser.parse_args()
	logger = setup_logging(args.debug)

	print ('-------- dbus_tempsensor_relay, v' + softwareVersion + ' is starting up --------')

	# Have a mainloop, so we can send/receive asynchronous calls to and from dbus
	DBusGMainLoop(set_as_default=True)

	dbus_temp_relay = DBusTempSensorRelay()

	# Start and run the mainloop
	mainloop = GLib.MainLoop()
	mainloop.run()
