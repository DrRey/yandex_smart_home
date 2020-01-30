"""Implement the Yandex Smart Home capabilities."""
import logging

from homeassistant.components import (
    climate,
    cover,
    group,
    fan,
    input_boolean,
    input_number,
    media_player,
    light,
    scene,
    script,
    switch,
    vacuum,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SERVICE_VOLUME_MUTE,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import DOMAIN as HA_DOMAIN
from homeassistant.util import color as color_util

from .const import (
    ERR_INVALID_VALUE,
    ERR_NOT_SUPPORTED_IN_CURRENT_MODE,
    CONF_CHANNEL_SET_VIA_MEDIA_CONTENT_ID, CONF_RELATIVE_VOLUME_ONLY)
from .error import SmartHomeError

_LOGGER = logging.getLogger(__name__)

PREFIX_CAPABILITIES = 'devices.capabilities.'
CAPABILITIES_ONOFF = PREFIX_CAPABILITIES + 'on_off'
CAPABILITIES_TOGGLE = PREFIX_CAPABILITIES + 'toggle'
CAPABILITIES_RANGE = PREFIX_CAPABILITIES + 'range'
CAPABILITIES_MODE = PREFIX_CAPABILITIES + 'mode'
CAPABILITIES_COLOR_SETTING = PREFIX_CAPABILITIES + 'color_setting'

CAPABILITIES = []


def register_capability(capability):
    """Decorate a function to register a capability."""
    CAPABILITIES.append(capability)
    return capability


class _Capability:
    """Represents a Capability."""

    type = ''
    instance = ''
    retrievable = True

    def __init__(self, hass, state, entity_config):
        """Initialize a trait for a state."""
        self.hass = hass
        self.state = state
        self.entity_config = entity_config

    def description(self):
        """Return description for a devices request."""
        response = {
            'type': self.type,
            'retrievable': self.retrievable,
        }
        parameters = self.parameters()
        if parameters is not None:
            response['parameters'] = parameters

        return response

    def get_state(self):
        """Return the state of this capability for this entity."""
        return {
            'type': self.type,
            'state':  {
                'instance': self.instance,
                'value': self.get_value()
            }
        }

    def parameters(self):
        """Return parameters for a devices request."""
        raise NotImplementedError

    def get_value(self):
        """Return the state value of this capability for this entity."""
        raise NotImplementedError

    async def set_state(self, data, state):
        """Set device state."""
        raise NotImplementedError


@register_capability
class OnOffCapability(_Capability):
    """On_off to offer basic on and off functionality.

    https://yandex.ru/dev/dialogs/alice/doc/smart-home/concepts/on_off-docpage/
    """

    type = CAPABILITIES_ONOFF
    instance = 'on'

    def __init__(self, hass, state, config):
        super().__init__(hass, state, config)
        self.retrievable = state.domain != scene.DOMAIN and state.domain != \
            script.DOMAIN

    @staticmethod
    def supported(domain, features, entity_config):
        """Test if state is supported."""
        return domain in (
            cover.DOMAIN,
            group.DOMAIN,
            input_boolean.DOMAIN,
            switch.DOMAIN,
            fan.DOMAIN,
            light.DOMAIN,
            media_player.DOMAIN,
            climate.DOMAIN,
            scene.DOMAIN,
            script.DOMAIN,
        ) or (vacuum.DOMAIN
               and ((features & vacuum.SUPPORT_START
                     and (features & vacuum.SUPPORT_RETURN_HOME
                          or features & vacuum.SUPPORT_STOP)
                     ) or (features & vacuum.SUPPORT_TURN_ON
                           and features & vacuum.SUPPORT_TURN_OFF
                           )))

    def parameters(self):
        """Return parameters for a devices request."""
        return None

    def get_value(self):
        """Return the state value of this capability for this entity."""
        if self.state.domain == cover.DOMAIN:
            return self.state.state == cover.STATE_OPEN
        elif self.state.domain == vacuum.DOMAIN:
            return self.state.state == STATE_ON or self.state.state == \
                   vacuum.STATE_CLEANING
        elif self.state.domain == climate.DOMAIN:
            return self.state.state != climate.HVAC_MODE_OFF
        else:
            return self.state.state != STATE_OFF

    async def set_state(self, data, state):
        """Set device state."""
        domain = self.state.domain

        if type(state['value']) is not bool:
            raise SmartHomeError(ERR_INVALID_VALUE, "Value is not boolean")

        service_domain = domain
        if domain == group.DOMAIN:
            service_domain = HA_DOMAIN
            service = SERVICE_TURN_ON if state['value'] else SERVICE_TURN_OFF
        elif domain == cover.DOMAIN:
            service = SERVICE_OPEN_COVER if state['value'] else \
                SERVICE_CLOSE_COVER
        elif domain == vacuum.DOMAIN:
            features = self.state.attributes.get(ATTR_SUPPORTED_FEATURES)
            if state['value']:
                if features & vacuum.SUPPORT_START:
                    service = vacuum.SERVICE_START
                else:
                    service = SERVICE_TURN_ON
            else:
                if features & vacuum.SUPPORT_RETURN_HOME:
                    service = vacuum.SERVICE_RETURN_TO_BASE
                elif features & vacuum.SUPPORT_STOP:
                    service = vacuum.SERVICE_STOP
                else:
                    service = SERVICE_TURN_OFF
        elif self.state.domain == scene.DOMAIN or self.state.domain == \
                script.DOMAIN:
            service = SERVICE_TURN_ON
        else:
            service = SERVICE_TURN_ON if state['value'] else SERVICE_TURN_OFF

        await self.hass.services.async_call(service_domain, service, {
            ATTR_ENTITY_ID: self.state.entity_id
        }, blocking=self.state.domain != script.DOMAIN, context=data.context)


@register_capability
class ToggleCapability(_Capability):
    """Mute and unmute functionality.

    https://yandex.ru/dev/dialogs/alice/doc/smart-home/concepts/toggle-docpage/
    """

    type = CAPABILITIES_TOGGLE
    instance = 'mute'

    @staticmethod
    def supported(domain, features, entity_config):
        """Test if state is supported."""
        return domain == media_player.DOMAIN and features & \
            media_player.SUPPORT_VOLUME_MUTE

    def parameters(self):
        """Return parameters for a devices request."""
        return {
            'instance': self.instance
        }

    def get_value(self):
        """Return the state value of this capability for this entity."""
        muted = self.state.attributes.get(media_player.ATTR_MEDIA_VOLUME_MUTED)

        return bool(muted)

    async def set_state(self, data, state):
        """Set device state."""
        if type(state['value']) is not bool:
            raise SmartHomeError(ERR_INVALID_VALUE, "Value is not boolean")

        muted = self.state.attributes.get(media_player.ATTR_MEDIA_VOLUME_MUTED)
        if muted is None:
            raise SmartHomeError(ERR_NOT_SUPPORTED_IN_CURRENT_MODE,
                                 "Device probably turned off")

        await self.hass.services.async_call(
            self.state.domain,
            SERVICE_VOLUME_MUTE, {
                ATTR_ENTITY_ID: self.state.entity_id,
                media_player.ATTR_MEDIA_VOLUME_MUTED: state['value']
            }, blocking=True, context=data.context)


class _ModeCapability(_Capability):
    """Base class of capabilities with mode functionality like thermostat mode
    or fan speed.

    https://yandex.ru/dev/dialogs/alice/doc/smart-home/concepts/mode-docpage/
    """

    type = CAPABILITIES_MODE


@register_capability
class ThermostatCapability(_ModeCapability):
    """Thermostat functionality"""

    instance = 'thermostat'

    climate_map = {
        climate.const.HVAC_MODE_HEAT: 'heat',
        climate.const.HVAC_MODE_COOL: 'cool',
        climate.const.HVAC_MODE_AUTO: 'auto',
        climate.const.HVAC_MODE_DRY: 'dry',
        climate.const.HVAC_MODE_FAN_ONLY: 'fan_only'
    }

    @staticmethod
    def supported(domain, features, entity_config):
        """Test if state is supported."""
        return domain == climate.DOMAIN

    def parameters(self):
        """Return parameters for a devices request."""
        operation_list = self.state.attributes.get(climate.ATTR_HVAC_MODES)
        modes = []
        for operation in operation_list:
            if operation in self.climate_map:
                modes.append({'value': self.climate_map[operation]})

        return {
            'instance': self.instance,
            'modes': modes,
            'ordered': False
        }

    def get_value(self):
        """Return the state value of this capability for this entity."""
        operation = self.state.attributes.get(climate.ATTR_HVAC_MODE)

        if operation is not None and operation in self.climate_map:
            return self.climate_map[operation]

        return 'auto'

    async def set_state(self, data, state):
        """Set device state."""
        value = None
        for climate_value, yandex_value in self.climate_map.items():
            if yandex_value == state['value']:
                value = climate_value
                break

        if value is None:
            raise SmartHomeError(ERR_INVALID_VALUE, "Unacceptable value")

        await self.hass.services.async_call(
            climate.DOMAIN,
            climate.SERVICE_SET_HVAC_MODE, {
                ATTR_ENTITY_ID: self.state.entity_id,
                climate.ATTR_HVAC_MODE: value
            }, blocking=True, context=data.context)


@register_capability
class FanSpeedCapability(_ModeCapability):
    """Fan speed functionality."""

    instance = 'fan_speed'

    values = {
        'auto': ['auto'],
        'low': ['low', 'min', 'silent'],
        'medium': ['medium', 'middle'],
        'high': ['high', 'max', 'strong', 'favorite'],
    }

    @staticmethod
    def supported(domain, features, entity_config):
        """Test if state is supported."""
        if domain == climate.DOMAIN:
            return features & climate.SUPPORT_FAN_MODE
        elif domain == fan.DOMAIN:
            return features & fan.SUPPORT_SET_SPEED
        return False

    def parameters(self):
        """Return parameters for a devices request."""
        if self.state.domain == climate.DOMAIN:
            speed_list = self.state.attributes.get(climate.ATTR_FAN_MODES)
        elif self.state.domain == fan.DOMAIN:
            speed_list = self.state.attributes.get(fan.ATTR_SPEED_LIST)
        else:
            speed_list = []

        speeds = []
        added = []
        for ha_value in speed_list:
            value = self.get_yandex_value_by_ha_value(ha_value)
            if value is not None and value not in added:
                speeds.append({'value': value})
                added.append(value)

        return {
            'instance': self.instance,
            'modes': speeds,
            'ordered': True
        }

    def get_yandex_value_by_ha_value(self, ha_value):
        for yandex_value, names in self.values.items():
            for name in names:
                if ha_value.lower().find(name) != -1:
                    return yandex_value
        return None

    def get_ha_by_yandex_value(self, yandex_value):
        if self.state.domain == climate.DOMAIN:
            speed_list = self.state.attributes.get(climate.ATTR_FAN_MODES)
        elif self.state.domain == fan.DOMAIN:
            speed_list = self.state.attributes.get(fan.ATTR_SPEED_LIST)
        else:
            speed_list = []

        for ha_value in speed_list:
            if yandex_value in self.values:
                for name in self.values[yandex_value]:
                    if ha_value.lower().find(name) != -1:
                        return ha_value
        return None

    def get_value(self):
        """Return the state value of this capability for this entity."""
        if self.state.domain == climate.DOMAIN:
            ha_value = self.state.attributes.get(climate.ATTR_FAN_MODE)
        elif self.state.domain == fan.DOMAIN:
            ha_value = self.state.attributes.get(fan.ATTR_SPEED)
        else:
            ha_value = None

        if ha_value is not None:
            yandex_value = self.get_yandex_value_by_ha_value(ha_value)
            if yandex_value is not None:
                return yandex_value

        return 'auto'

    async def set_state(self, data, state):
        """Set device state."""
        value = self.get_ha_by_yandex_value(state['value'])

        if value is None:
            raise SmartHomeError(ERR_INVALID_VALUE, "Unsupported value")

        if self.state.domain == climate.DOMAIN:
            service = climate.SERVICE_SET_FAN_MODE
            attr = climate.ATTR_FAN_MODE
        elif self.state.domain == fan.DOMAIN:
            service = fan.SERVICE_SET_SPEED
            attr = fan.ATTR_SPEED
        else:
            raise SmartHomeError(ERR_INVALID_VALUE, "Unsupported domain")

        await self.hass.services.async_call(
            self.state.domain,
            service, {
                ATTR_ENTITY_ID: self.state.entity_id,
                attr: value
            }, blocking=True, context=data.context)


class _RangeCapability(_Capability):
    """Base class of capabilities with range functionality like volume or
    brightness.

    https://yandex.ru/dev/dialogs/alice/doc/smart-home/concepts/range-docpage/
    """

    type = CAPABILITIES_RANGE


@register_capability
class TemperatureCapability(_RangeCapability):
    """Set temperature functionality."""

    instance = 'temperature'

    @staticmethod
    def supported(domain, features, entity_config):
        """Test if state is supported."""
        return domain == climate.DOMAIN and features & \
            climate.const.SUPPORT_TARGET_TEMPERATURE

    def parameters(self):
        """Return parameters for a devices request."""
        min_temp = self.state.attributes.get(climate.ATTR_MIN_TEMP)
        max_temp = self.state.attributes.get(climate.ATTR_MAX_TEMP)
        return {
            'instance': self.instance,
            'unit': 'unit.temperature.celsius',
            'range': {
                'min': min_temp,
                'max': max_temp,
                'precision': 0.5
            }
        }

    def get_value(self):
        """Return the state value of this capability for this entity."""
        temperature = self.state.attributes.get(climate.ATTR_TEMPERATURE)
        if temperature is None:
            return 0
        else:
            return float(temperature)

    async def set_state(self, data, state):
        """Set device state."""
        await self.hass.services.async_call(
            climate.DOMAIN,
            climate.SERVICE_SET_TEMPERATURE, {
                ATTR_ENTITY_ID: self.state.entity_id,
                climate.ATTR_TEMPERATURE: state['value']
            }, blocking=True, context=data.context)


@register_capability
class BrightnessCapability(_RangeCapability):
    """Set brightness functionality."""

    instance = 'brightness'

    @staticmethod
    def supported(domain, features, entity_config):
        """Test if state is supported."""
        return domain == light.DOMAIN and features & light.SUPPORT_BRIGHTNESS

    def parameters(self):
        """Return parameters for a devices request."""
        return {
            'instance': self.instance,
            'unit': 'unit.percent',
            'range': {
                'min': 0,
                'max': 100,
                'precision': 1
            }
        }

    def get_value(self):
        """Return the state value of this capability for this entity."""
        brightness = self.state.attributes.get(light.ATTR_BRIGHTNESS)
        if brightness is None:
            return 0
        else:
            return int(100 * (brightness / 255))

    async def set_state(self, data, state):
        """Set device state."""
        await self.hass.services.async_call(
            light.DOMAIN,
            light.SERVICE_TURN_ON, {
                ATTR_ENTITY_ID: self.state.entity_id,
                light.ATTR_BRIGHTNESS_PCT: state['value']
            }, blocking=True, context=data.context)


@register_capability
class VolumeCapability(_RangeCapability):
    """Set volume functionality."""

    instance = 'volume'
    retrievable = False

    def __init__(self, hass, state, config):
        super().__init__(hass, state, config)
        features = self.state.attributes.get(ATTR_SUPPORTED_FEATURES, 0)
        self.retrievable = features & media_player.SUPPORT_VOLUME_SET != 0

    @staticmethod
    def supported(domain, features, entity_config):
        """Test if state is supported."""
        return domain == media_player.DOMAIN and features & \
            media_player.SUPPORT_VOLUME_STEP

    def parameters(self):
        """Return parameters for a devices request."""
        if self.is_relative_volume_only():
            return {
                'instance': self.instance
            }
        else:
            return {
                'instance': self.instance,
                'random_access': True,
                'range': {
                    'max': 100,
                    'min': 0,
                    'precision': 1
                }
            }

    def is_relative_volume_only(self):
        _LOGGER.debug("CONF_RELATIVE_VOLUME_ONLY: %r" % self.entity_config.get(
            CONF_RELATIVE_VOLUME_ONLY))
        return not self.retrievable or self.entity_config.get(
            CONF_RELATIVE_VOLUME_ONLY)

    def get_value(self):
        """Return the state value of this capability for this entity."""
        level = self.state.attributes.get(
            media_player.ATTR_MEDIA_VOLUME_LEVEL)
        if level is None:
            return 0
        else:
            return int(level * 100)

    async def set_state(self, data, state):
        """Set device state."""
        if self.is_relative_volume_only():
            if state['value'] > 0:
                service = media_player.SERVICE_VOLUME_UP
            else:
                service = media_player.SERVICE_VOLUME_DOWN
            await self.hass.services.async_call(
                media_player.DOMAIN,
                service, {
                    ATTR_ENTITY_ID: self.state.entity_id
                }, blocking=True, context=data.context)
        else:
            await self.hass.services.async_call(
                media_player.DOMAIN,
                media_player.SERVICE_VOLUME_SET, {
                    ATTR_ENTITY_ID: self.state.entity_id,
                    media_player.const.ATTR_MEDIA_VOLUME_LEVEL:
                        state['value'] / 100,
                }, blocking=True, context=data.context)


@register_capability
class ChannelCapability(_RangeCapability):
    """Set channel functionality."""

    instance = 'channel'

    def __init__(self, hass, state, config):
        super().__init__(hass, state, config)
        features = self.state.attributes.get(ATTR_SUPPORTED_FEATURES, 0)
        self.retrievable = features & media_player.SUPPORT_PLAY_MEDIA != 0 and \
            self.entity_config.get(CONF_CHANNEL_SET_VIA_MEDIA_CONTENT_ID)

    @staticmethod
    def supported(domain, features, entity_config):
        """Test if state is supported."""
        return domain == media_player.DOMAIN and (
                (features & media_player.SUPPORT_PLAY_MEDIA and
                    entity_config.get(CONF_CHANNEL_SET_VIA_MEDIA_CONTENT_ID)) or (
                    features & media_player.SUPPORT_PREVIOUS_TRACK
                    and features & media_player.SUPPORT_NEXT_TRACK)
        )

    def parameters(self):
        """Return parameters for a devices request."""
        if self.retrievable:
            return {
                'instance': self.instance,
                'random_access': True,
                'range': {
                    'max': 999,
                    'min': 0,
                    'precision': 1
                }
            }
        else:
            return {
                'instance': self.instance,
                'random_access': False
            }

    def get_value(self):
        """Return the state value of this capability for this entity."""
        if self.retrievable or self.state.attributes.get(
                media_player.ATTR_MEDIA_CONTENT_TYPE) \
                != media_player.const.MEDIA_TYPE_CHANNEL:
            return 0
        try:
            return int(self.state.attributes.get(
                media_player.ATTR_MEDIA_CONTENT_ID))
        except ValueError:
            return 0
        except TypeError:
            return 0

    async def set_state(self, data, state):
        """Set device state."""
        if 'relative' in state and state['relative']:
            if state['value'] > 0:
                service = media_player.SERVICE_MEDIA_NEXT_TRACK
            else:
                service = media_player.SERVICE_MEDIA_PREVIOUS_TRACK
            await self.hass.services.async_call(
                media_player.DOMAIN,
                service, {
                    ATTR_ENTITY_ID: self.state.entity_id
                }, blocking=True, context=data.context)
        else:
            await self.hass.services.async_call(
                media_player.DOMAIN,
                media_player.SERVICE_PLAY_MEDIA, {
                    ATTR_ENTITY_ID: self.state.entity_id,
                    media_player.const.ATTR_MEDIA_CONTENT_ID: state['value'],
                    media_player.const.ATTR_MEDIA_CONTENT_TYPE:
                        media_player.const.MEDIA_TYPE_CHANNEL,
                }, blocking=True, context=data.context)

@register_capability
class InputNumberCapability(_RangeCapability):
    """Set input_number functionality."""

    instance = 'temperature'

    @staticmethod
    def supported(domain, features):
        """Test if state is supported."""
        return domain == input_number.DOMAIN

    def parameters(self):
        """Return parameters for a devices request."""
        min_value = self.state.attributes.get(input_number.ATTR_MIN)
        max_value = self.state.attributes.get(input_number.ATTR_MAX)
        value_perсision = self.state.attributes.get(input_number.ATTR_STEP)
        return {
            'instance': self.instance,
            'unit': 'unit.temperature.celsius',
            'range': {
                'min': min_value,
                'max': max_value,
                'precision': value_perсision
            }
        }

    def get_value(self):
        """Return the state value of this capability for this entity."""
        value = self.state.attributes.get(input_number.ATTR_VALUE)
        if value is None:
            return 0
        else:
            return int(value)

    async def set_state(self, data, state):
        """Set device state."""
        await self.hass.services.async_call(
            input_number.DOMAIN,
            input_number.SERVICE_SET_VALUE, {
                ATTR_ENTITY_ID: self.state.entity_id,
                input_number.ATTR_VALUE: state['value']
            }, blocking=True, context=data.context)

class _ColorSettingCapability(_Capability):
    """Base color setting functionality.

    https://yandex.ru/dev/dialogs/alice/doc/smart-home/concepts/color_setting-docpage/
    """

    type = CAPABILITIES_COLOR_SETTING

    def parameters(self):
        """Return parameters for a devices request."""
        result = {}

        features = self.state.attributes.get(ATTR_SUPPORTED_FEATURES, 0)

        if features & light.SUPPORT_COLOR:
            result['color_model'] = 'rgb'

        if features & light.SUPPORT_COLOR_TEMP:
            max_temp = self.state.attributes[light.ATTR_MIN_MIREDS]
            min_temp = self.state.attributes[light.ATTR_MAX_MIREDS]
            result['temperature_k'] = {
                'min': color_util.color_temperature_mired_to_kelvin(min_temp),
                'max': color_util.color_temperature_mired_to_kelvin(max_temp)
            }

        return result


@register_capability
class RgbCapability(_ColorSettingCapability):
    """RGB color functionality."""

    instance = 'rgb'

    @staticmethod
    def supported(domain, features, entity_config):
        """Test if state is supported."""
        return domain == light.DOMAIN and features & light.SUPPORT_COLOR

    def get_value(self):
        """Return the state value of this capability for this entity."""
        color = self.state.attributes.get(light.ATTR_RGB_COLOR)
        if color is None:
            return 0

        rgb = color[0]
        rgb = (rgb << 8) + color[1]
        rgb = (rgb << 8) + color[2]

        return rgb

    async def set_state(self, data, state):
        """Set device state."""
        red = (state['value'] >> 16) & 0xFF
        green = (state['value'] >> 8) & 0xFF
        blue = state['value'] & 0xFF

        await self.hass.services.async_call(
            light.DOMAIN,
            light.SERVICE_TURN_ON, {
                ATTR_ENTITY_ID: self.state.entity_id,
                light.ATTR_RGB_COLOR: (red, green, blue)
            }, blocking=True, context=data.context)


@register_capability
class TemperatureKCapability(_ColorSettingCapability):
    """Color temperature functionality."""

    instance = 'temperature_k'

    @staticmethod
    def supported(domain, features, entity_config):
        """Test if state is supported."""
        return domain == light.DOMAIN and features & light.SUPPORT_COLOR_TEMP

    def get_value(self):
        """Return the state value of this capability for this entity."""
        kelvin = self.state.attributes.get(light.ATTR_COLOR_TEMP)
        if kelvin is None:
            return 0

        return color_util.color_temperature_mired_to_kelvin(kelvin)

    async def set_state(self, data, state):
        """Set device state."""
        await self.hass.services.async_call(
            light.DOMAIN,
            light.SERVICE_TURN_ON, {
                ATTR_ENTITY_ID: self.state.entity_id,
                light.ATTR_KELVIN: state['value']
            }, blocking=True, context=data.context)
