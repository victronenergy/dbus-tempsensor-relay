dbus-tempsensor-relay
==============

[![Build Status](https://travis-ci.com/victronenergy/dbus-tempsensor-relay.svg?branch=master)](https://travis-ci.com/victronenergy/dbus-tempsensor-relay)

Python script that toggles the relay(s) based on the temperature values measured by temperature sensors.

The script supports two conditions per temperature sensor where each one consist on a temperature range (high or low) where the configured relay must be closed.

For example a temperature sensor in the battery cabinet can be used to switch on a fan in case of high temperature or a resistor to keep a Lithium battery above the cut-off temperature:

Condition 1\
Activation temperature: 35ºC\
Deactivation temperature: 25ºC\
Relay: 1


Condition 2\
Activation temperature: 4ºC\
Deactivation temperature: 10ºC\
Relay: 2


Multiple sensors can control the same relay. Relay will keep closed as long as there are one active condition of any sensor.

Any temperature sensor that publishes as `com.victronenergy.temperature.*` with a `/Temperature` path is supported.
