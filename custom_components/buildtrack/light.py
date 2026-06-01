async def async_update(self):
    _LOGGER.warning(
        "BUILTRACK THERMOSTAT async_update CALLED | %s | id=%s",
        self._attr_name,
        self._entity_id,
    )

    payload = {
        "entityId": self._entity_id,
        "entityKey": self._entity_key,
    }

    _LOGGER.warning(
        "BUILTRACK THERMOSTAT READ API CALL | %s | payload=%s",
        self._attr_name,
        payload,
    )

    try:
        data = await self._api.call(
            endpoint="/readDeviceData",
            method="POST",
            payload=payload,
        )
    except Exception as err:
        _LOGGER.exception(
            "BUILTRACK THERMOSTAT READ API ERROR | %s | error=%s",
            self._attr_name,
            err,
        )
        return

    _LOGGER.warning(
        "BUILTRACK THERMOSTAT READ API RESPONSE | %s | raw=%s | type=%s",
        self._attr_name,
        data,
        type(data),
    )

    if not data:
        _LOGGER.warning(
            "BUILTRACK THERMOSTAT READ EMPTY RESPONSE | %s",
            self._attr_name,
        )
        return

    # Handle nested response if API returns {"data": {...}}
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data.get("data")

    if not isinstance(data, dict):
        _LOGGER.warning(
            "BUILTRACK THERMOSTAT INVALID RESPONSE FORMAT | %s | data=%s",
            self._attr_name,
            data,
        )
        return

    state = str(
        data.get("state")
        or data.get("status")
        or data.get("power")
        or data.get("switch")
        or data.get("value")
        or ""
    ).strip().lower()

    speed = (
        data.get("speed")
        or data.get("fanSpeed")
        or data.get("fan_speed")
        or data.get("level")
    )

    target_temp = (
        data.get("temperature")
        or data.get("targetTemperature")
        or data.get("target_temperature")
        or data.get("setTemperature")
        or data.get("set_temperature")
        or data.get("temp")
    )

    current_temp = (
        data.get("currentTemperature")
        or data.get("current_temperature")
        or data.get("roomTemperature")
        or data.get("room_temperature")
    )

    _LOGGER.warning(
        "BUILTRACK THERMOSTAT PARSED DATA | %s | state=%s | speed=%s | target_temp=%s | current_temp=%s",
        self._attr_name,
        state,
        speed,
        target_temp,
        current_temp,
    )

    if state in ["on", "1", "true", "yes", "open"]:
        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_mode = HVACMode.COOL

        if self._attr_hvac_mode == HVACMode.HEAT:
            self._attr_hvac_action = HVACAction.HEATING
        else:
            self._attr_hvac_action = HVACAction.COOLING

    elif state in ["off", "0", "false", "no", "close", "closed"]:
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_hvac_action = HVACAction.OFF

    elif not state and speed is None and target_temp is None and current_temp is None:
        _LOGGER.warning(
            "BUILTRACK THERMOSTAT UNKNOWN RESPONSE FORMAT | %s | data=%s",
            self._attr_name,
            data,
        )
        return

    if speed is not None:
        speed_str = str(speed).strip().lower()

        if speed_str in ["low", "medium", "high"]:
            self._attr_fan_mode = speed_str
        else:
            try:
                speed_int = int(float(speed))

                if speed_int <= 33:
                    self._attr_fan_mode = "low"
                elif speed_int <= 66:
                    self._attr_fan_mode = "medium"
                else:
                    self._attr_fan_mode = "high"

            except Exception as err:
                _LOGGER.warning(
                    "BUILTRACK THERMOSTAT SPEED PARSE ERROR | %s | speed=%s | error=%s",
                    self._attr_name,
                    speed,
                    err,
                )

    if target_temp is not None:
        try:
            self._attr_target_temperature = float(target_temp)
        except Exception as err:
            _LOGGER.warning(
                "BUILTRACK THERMOSTAT TARGET TEMP PARSE ERROR | %s | temp=%s | error=%s",
                self._attr_name,
                target_temp,
                err,
            )

    if current_temp is not None:
        try:
            self._attr_current_temperature = float(current_temp)
        except Exception as err:
            _LOGGER.warning(
                "BUILTRACK THERMOSTAT CURRENT TEMP PARSE ERROR | %s | temp=%s | error=%s",
                self._attr_name,
                current_temp,
                err,
            )

    self.async_write_ha_state()

    _LOGGER.warning(
        "BUILTRACK THERMOSTAT FINAL HA STATE WRITE | %s | hvac_mode=%s | hvac_action=%s | fan=%s | target_temp=%s | current_temp=%s",
        self._attr_name,
        self._attr_hvac_mode,
        self._attr_hvac_action,
        self._attr_fan_mode,
        self._attr_target_temperature,
        self._attr_current_temperature,
    )
