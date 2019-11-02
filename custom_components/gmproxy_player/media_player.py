"""
Attempting to support Google Music as a media player
"""
import asyncio
import logging
import time
import random
import pickle
import os.path
import requests
import json
import re
from datetime import timedelta
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.condition import state
from homeassistant.helpers.event import track_state_change
from homeassistant.helpers.event import call_later
import homeassistant.helpers.entity_component as ec
from homeassistant.helpers.event import track_time_interval
import homeassistant.components.input_select as input_select

from homeassistant.const import (
    ATTR_ENTITY_ID, EVENT_HOMEASSISTANT_START,
    STATE_PLAYING, STATE_PAUSED, STATE_OFF, STATE_IDLE)

from homeassistant.components.media_player import (
    MediaPlayerDevice, PLATFORM_SCHEMA, SERVICE_TURN_ON, SERVICE_TURN_OFF,
    SERVICE_PLAY_MEDIA, SERVICE_MEDIA_PAUSE, ATTR_MEDIA_VOLUME_LEVEL,
    SERVICE_VOLUME_UP, SERVICE_VOLUME_DOWN, SERVICE_VOLUME_SET,
    ATTR_MEDIA_CONTENT_ID, ATTR_MEDIA_CONTENT_TYPE, DOMAIN as DOMAIN_MP)

from homeassistant.components.media_player.const import (
    MEDIA_TYPE_MUSIC, SUPPORT_STOP, SUPPORT_PLAY, SUPPORT_PAUSE,
    SUPPORT_PLAY_MEDIA, SUPPORT_PREVIOUS_TRACK, SUPPORT_NEXT_TRACK,
    SUPPORT_VOLUME_MUTE, SUPPORT_VOLUME_SET, SUPPORT_VOLUME_STEP,
    SUPPORT_TURN_ON, SUPPORT_TURN_OFF, SUPPORT_SELECT_SOURCE)

# The domain of your component. Should be equal to the name of your component.
DOMAIN = 'gmproxy_player'

SUPPORT_GMPROXY_PLAYER = SUPPORT_TURN_ON | SUPPORT_TURN_OFF | SUPPORT_PLAY_MEDIA | \
    SUPPORT_PLAY | SUPPORT_PAUSE | SUPPORT_STOP | SUPPORT_SELECT_SOURCE | \
    SUPPORT_VOLUME_SET | SUPPORT_VOLUME_STEP | SUPPORT_VOLUME_MUTE | \
    SUPPORT_PREVIOUS_TRACK | SUPPORT_NEXT_TRACK

CONF_SPEAKERS = 'media_player'
CONF_PLAY_MODE = 'play_mode'
CONF_GMPROXYURL = 'gmproxyurl'

DEFAULT_SPEAKERS = 'not_set'
DEFAULT_PLAY_MODE = 'Normal'
DEFAULT_GMPROXYURL = 'http://localhost:9999'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Optional(CONF_SPEAKERS, default=DEFAULT_SPEAKERS): cv.string,
        vol.Optional(CONF_PLAY_MODE, default=DEFAULT_PLAY_MODE): cv.string,
        vol.Optional(CONF_GMPROXYURL, default=DEFAULT_GMPROXYURL): cv.string,
    })
}, extra=vol.ALLOW_EXTRA)

# Shortcut for the logger
_LOGGER = logging.getLogger(__name__)

def setup_platform(hass, config, add_devices, discovery_info=None):
    add_devices([GMProxyComponent(hass, config)])
    return True

class GMProxyComponent(MediaPlayerDevice):
    def __init__(self, hass, config):
        self.hass = hass
        self._name = "gmproxy_player"
        self._media_player = "input_select." + config.get(CONF_SPEAKERS, DEFAULT_SPEAKERS)
        self._play_mode = "input_select." + config.get(CONF_PLAY_MODE, DEFAULT_PLAY_MODE)
        self._gmproxyurl = config.get(CONF_GMPROXYURL, DEFAULT_GMPROXYURL)
        hass.bus.listen_once(EVENT_HOMEASSISTANT_START, self._update_media_players)

        ## search for speakers, wait 15 sec to get them discovered first 
        call_later(self.hass, 15, self._update_media_players)
        ## after first search, period of 60 sec should be fine
        SCAN_INTERVAL = timedelta(seconds=60)
        track_time_interval(self.hass, self._update_media_players, SCAN_INTERVAL)
        self._unsub_speaker_change = None
        self._unsub_speaker_change = track_state_change(self.hass, self._media_player, self._speaker_change)
        self._speaker = None  ## current speaker entity_id
        self._attributes = {}
        
        self._unsub_speaker_tracker = None
        self._playing = False
        self._current_track = None
        self._state = STATE_OFF
        self._volume = 0.0
        self._is_mute = False
        self._track_name = None
        self._track_artist = None
        self._track_album_name = None
        self._track_album_cover = None
        self._track_artist_cover = None
        self._attributes['_player_state'] = STATE_OFF

    @property
    def name(self):
        return self._name

    @property
    def icon(self):
        return 'mdi:music-circle'

    @property 
    def supported_features(self):
        return SUPPORT_GMPROXY_PLAYER

    @property
    def should_poll(self):
        return False

    @property
    def state(self):
        return self._state

    @property
    def device_state_attributes(self):
        return self._attributes

    @property
    def is_volume_muted(self):
        return self._is_mute

    @property
    def is_on(self):
        return self._playing

    @property
    def media_content_type(self):
        return MEDIA_TYPE_MUSIC

    @property
    def media_title(self):
        return self._track_name

    @property
    def media_artist(self):
        return self._track_artist

    @property
    def media_album_name(self):
        return self._track_album_name

    @property
    def media_image_url(self):
        return self._track_album_cover

    @property
    def media_image_remotely_accessible(self):
        return True

    @property
    def volume_level(self):
      return self._volume

    def turn_on(self, *args, **kwargs):
        _LOGGER.info("turn_on")
        """ Turn on the selected media_player from input_select """
        select_speaker = self.hass.states.get(self._media_player)
        self._speaker = "media_player.{}".format(select_speaker.state)
        speaker_state = self.hass.states.get(self._speaker)
        if speaker_state == None:
            self._speaker = None
            return
        
        _LOGGER.info("turn on speaker %s",self._speaker)
        
        if speaker_state.state == STATE_OFF or speaker_state.state == STATE_IDLE:
            self._turn_on_media_player(data={ATTR_ENTITY_ID: self._speaker})
        elif speaker_state.state != STATE_OFF:
            self._turn_off_media_player(data={ATTR_ENTITY_ID: self._speaker})
            self._unsub_speaker_tracker()            
            call_later(self.hass, 1, self.turn_on)

    def _turn_on_media_player(self, data=None):
        _LOGGER.info("turn_on_mediaplayer")

        if self._current_track == None:
            url = "{}/current_track".format(self._gmproxyurl)
            self._current_track = json.loads(requests.get(url).content)

        if self._current_track == None:
            return

        if data is None:
            data = {ATTR_ENTITY_ID: self._speaker}
        self._state = STATE_IDLE 
        self.schedule_update_ha_state()
        self.hass.services.call(DOMAIN_MP, 'turn_on', data)

    def turn_off(self, entity_id=None, old_state=None, new_state=None, **kwargs):
        _LOGGER.info("turn_off")
        """ Turn off the selected media_player """
        self._playing = False
        self._track_name = None
        self._track_artist = None
        self._track_album_name = None
        self._track_album_cover = None

        data = {ATTR_ENTITY_ID: self._speaker}
        self._turn_off_media_player(data)

    def _turn_off_media_player(self, data=None):
        _LOGGER.info("turn_off_mediaplayer")
        """Fire the off action."""
        self._playing = False
        self._state = STATE_OFF
        self._attributes['_player_state'] = STATE_OFF
        self.schedule_update_ha_state()
        if data is None:
            data = {ATTR_ENTITY_ID: self._speaker}
        self.hass.services.call(DOMAIN_MP, 'turn_off', data)

    def _update_media_players(self,now=None):
        entities = []
        if self._unsub_speaker_change:
            self._unsub_speaker_change()
        state = self.hass.states.get(self._media_player)
        if state == None:
            return
        _LOGGER.info("state of speakers: (%s)", state.state)
        for entity_state in self.hass.states.async_all():
            m = re.match(r"^media_player\.(?P<name>.*)",entity_state.entity_id)
            if m:
                if m.group('name') != self._name:
                    entities.append(m.group('name'))
        if not entities:
            return 
        self.hass.services.call(input_select.DOMAIN, input_select.SERVICE_SET_OPTIONS, {"options": list(entities), "entity_id": self._media_player})
        self.hass.services.call(input_select.DOMAIN, input_select.SERVICE_SELECT_OPTION, {"option": state.state, "entity_id": self._media_player})
        self._unsub_speaker_change = track_state_change(self.hass, self._media_player, self._speaker_change)

        
    def _speaker_change(self, entity_id=None, old_state=None, new_state=None):
        if new_state == None:
            return
        speaker = self.hass.states.get("media_player.{}".format(new_state.state))
        if speaker == None:
            return
        self._speaker = speaker.entity_id
        _LOGGER.info("speaker  %s",self._speaker)

    def _sync_player(self, entity_id=None, old_state=None, new_state=None):
        _LOGGER.debug("sync entity: {} old_state: {} new_state: {}".format(entity_id,old_state.state,new_state.state))
        _LOGGER.debug("sync entity: self._state: {}".format(self._state))

        if old_state.state == STATE_PLAYING and new_state.state == STATE_IDLE:
            _LOGGER.debug("send play")
            self._unsub_speaker_tracker()
            self.media_next_track()
            return

        speaker = self.hass.states.get(self._speaker)
        self._attributes['_player_friendly'] = speaker.attributes['friendly_name'] if 'friendly_name' in speaker.attributes else None 
        self._attributes['_player_state']    = speaker.state

        if speaker.state == 'off':
            self._state = STATE_OFF
            self.turn_off()

        self._volume = round(speaker.attributes['volume_level'],2) if 'volume_level' in speaker.attributes else None
        self.schedule_update_ha_state()
 
    def _play(self):
        return

    def media_play(self, entity_id=None, old_state=None, new_state=None, **kwargs):
        #self._state = STATE_PLAYING
        """Send play command."""
        if self._state == STATE_PAUSED:
            self._state = STATE_PLAYING
            self.schedule_update_ha_state()
            data = {ATTR_ENTITY_ID: self._speaker}
            self.hass.services.call(DOMAIN_MP, 'media_play', data)
        else:
            try:
                _url = "{}/get_song?id={}".format(self._gmproxyurl,self._current_track['id'])
                _LOGGER.info("stream url: (%s)", _url)
                self._state = STATE_PLAYING
            except:
                _LOGGER.error("Failed to get URL for track: (%s)", self._current_track)
                self._turn_off_media_player() 
            
            self.update_media_info()

            data = {
                ATTR_MEDIA_CONTENT_ID: _url,
                ATTR_MEDIA_CONTENT_TYPE: "audio/mp3",
                ATTR_ENTITY_ID: self._speaker
                }
            self.hass.services.call(DOMAIN_MP, SERVICE_PLAY_MEDIA, data)
            self._unsub_speaker_tracker = track_state_change(self.hass, self._speaker, self._sync_player)

    def media_pause(self, **kwargs):
        """ Send media pause command to media player """
        self._state = STATE_PAUSED
        self.schedule_update_ha_state()
        data = {ATTR_ENTITY_ID: self._speaker}
        self.hass.services.call(DOMAIN_MP, 'media_pause', data)

    def media_play_pause(self, **kwargs):
        """Simulate play pause media player."""
        if self._state == STATE_PLAYING:
            self.media_pause()
        else:
            self.media_play()

    def update_media_info(self):
        if self._current_track == None:
            self._track_name = None
            self._track_artist = None
            self._track_album_name = None  
            self._track_album_cover = None
            self._track_artist_cover = None
        else:
            self._track_name         = self._current_track['title'] if 'title' in self._current_track else None
            self._track_artist       = self._current_track['artist'] if 'artist' in self._current_track else None
            self._track_album_name   = self._current_track['album'] if 'album' in self._current_track else None
            self._track_album_cover  = self._current_track['albumArtRef'][0]['url'] if 'albumArtRef' in self._current_track else None
            self._track_artist_cover = self._current_track['artistArtRef'][0]['url'] if 'artistArtRef' in self._current_track else None
        self.schedule_update_ha_state()        

    def media_previous_track(self, **kwargs):
        """Send the previous track command."""
        url = "{}/prev_track".format(self._gmproxyurl)
        self._current_track = json.loads(requests.get(url).content)
        self.update_media_info()
        if self._state == STATE_PLAYING:
            self.media_play()

    def media_next_track(self, **kwargs):
        """Send next track command."""
        url = "{}/next_track".format(self._gmproxyurl)
        self._current_track = json.loads(requests.get(url).content)
        self.update_media_info()
        if self._state == STATE_PLAYING:
            self.media_play()

    def media_stop(self, **kwargs):
        """Send stop command."""
        data = {ATTR_ENTITY_ID: self._speaker}
        self.hass.services.call(DOMAIN_MP, 'media_stop', data)

    def set_volume_level(self, volume):
        """Set volume level."""
        self._volume = round(volume,2)
        data = {ATTR_ENTITY_ID: self._speaker, 'volume_level': self._volume}
        self.hass.services.call(DOMAIN_MP, 'volume_set', data)
        self.schedule_update_ha_state()

    def volume_up(self, **kwargs):
        """Volume up the media player."""
        newvolume = min(self._volume + 0.05, 1)
        self.set_volume_level(newvolume)

    def volume_down(self, **kwargs):
        """Volume down media player."""
        newvolume = max(self._volume - 0.05, 0.01)
        self.set_volume_level(newvolume)

    def mute_volume(self, mute):
        """Send mute command."""
        self._is_mute = True if not self._is_mute else False
        self.schedule_update_ha_state()
        data = {ATTR_ENTITY_ID: self._speaker, "is_volume_muted": self._is_mute}
        self.hass.services.call(DOMAIN_MP,'volume_mute',data)
