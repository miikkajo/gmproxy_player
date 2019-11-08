# gmproxy_player
## player for my gmusicproxy hassio addon

inspired by https://github.com/tprelog/homeassistant-gmusic_player

goal is to simplify player itself and move all logic to gmusicproxy addon

for now it's missing google music playlist and stations, but those are easy to implement.

mainly created for my own use, i'm old school music user, i like to listen music by albums. 
therefor i find using playlists annoying, specially when they have 1000 song limits (grr).

this is for now just mockup but as (if) a have more time in my hands, it will (may) evolve...

Track queue is located in my gmusicproxy addon as json file, and player only moves track index and 
requests current_track from it.

Addon has simple playlist generator, you can generate queue for artists, album,
or All Albums in library.

In future i might add ability to save playlists in gmusicproxy 

## Installation

copy custom_components/gmproxy_player/ to homeassistant/custom_components/gmproxy_player/ directory 
(create directory if missing)

copy packages/gmproxy_player.yaml to homeassistant/packages/gmproxy_player.yaml
(create directory if missing)

In lovelace add Entities card with entities:
  input_select.gmproxy_player_speakers
  input_select.gmproxy_player_play_mode
 
Speakers is list of mediaplayers detected, and selected will be used as gmproxy_player output

in packages/gmproxy_player.yaml, configure url for gmusicproxy,
i'll try to wrap up somekind of detection for it but for now, it must be configured:

media_player:
  - platform: gmproxy_player
    gmproxyurl: 'http://192.168.1.2:9999'

