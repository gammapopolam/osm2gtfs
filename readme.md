# OSM2GTFS - a simple scripts to get GTFS from OSM

Some scripts to get GTFS from OSM in area id. Make sure that routes are in [OSM PTv2 schema](https://wiki.openstreetmap.org/wiki/Public_transport):

- each route has an `public_transport:version=2`, `ref`, `name`  tag
- in each route relation the participants ordered like:
```
stop_entry_only: stop_position
platform_entry_only: platform
stop: stop_position
platform: platform
...
stop_exit_only: stop_position
platform_exit_only: platform
   : road segment 1 by trip continuality
   : road segment 2 by trip continuality
...
   : road segment N by trip continuality
```

How it works:
1. Get all routes of specified type within area relation id from OSM by overpass-turbo API
2. If subway or commuter specified, get platforms of each route. Else - get stop_positions
3. Rebuild responses to json by schema below

# osm_grabber
Download the script into your working directory:
```python
from osm_grabber import OSM_Grabber
# Available types are bus, tram, trolleybus, subway, commuter 
# Each type of transport should be initialized separately 
# Enable stop2stop connections if you want to get L-space
trips, stops = OSM_Grabber(type='bus', network=None, operator=None, area=1430616).fetch(s2s=True)
# or save json's in directory
OSM_Grabber(type='bus', network=None, operator=None, area=1430616).fetch(s2s=True, out_dir='kja')
```

By default it highlights potentially invalid route relation ids if there could be mismatches between stops and platforms counts

The JSON Schema of `trips`:
```
[
        {
            'stop_sequence': list, 
            'shape': wkt, 
            'colour': str, 
            'ref': str, 
            'route_id': <relation id>,
            'route_name': str
        }
]
```

The JSON Schema of `stops`:
```
[
        {
            'stop_id': <nwr id>, 
            'stop_name': str, 
            'stop_shape': wkt, 
            'wheelchair': str yes/no
        }
]
```
The JSON Schema of `s2s`:
```
[
    {
        'from': <stop id>,
        'to': <stop_id>,
        'shape': wkt,
        'length': float,
        'trip_ref': str,
        'trip_id': <relation id>
    }
]
```
These JSON's can be simply rebuilded into [networkx](https://github.com/networkx/networkx) DiGraph, because `stops` and `s2s` can be implemented as L-space of transit network.
# osm2gtfs

TBA