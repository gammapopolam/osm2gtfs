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
# osm_grabber
Download the script into your working directory:
```python
from osm_grabber import OSM_Grabber
# Available types are bus, tram, trolleybus, subway, commuter 
# Each type of transport should be initialized separately 
trips, stops = OSM_Grabber(type='bus', network=None, operator=None, area=1430616).fetch()
# or save json's in directory
OSM_Grabber(type='bus', network=None, operator=None, area=1430616).fetch(out_dir='kja')
```

The JSON Schema of `trips`:
```
{
    <relation id>: 
        {
            'platform_sequence': list, 
            'shape': wkt, 
            'colour': str, 
            'ref': str, 
            'route_id': <relation id>,
            'route_name': str
        }
}
```

The JSON Schema of `stops`:
```
[
        {
            'stop_id': <nwr id>, 
            'stop_name': str, 
            'stop_shape': wkt, 
            'wheelchair': str yes/no, 
        }
]

```
These JSON's can be simply rebuilded into [networkx](https://github.com/networkx/networkx) DiGraph, because `stops` and `trips` can be implemented as L-space of transit network 
# osm2gtfs

TBA