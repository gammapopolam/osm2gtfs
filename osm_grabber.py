# -*- coding: utf-8 -*-
import geopandas as gpd
import pandas as pd
import shapely
import json
import requests
import time
import math
from tqdm import tqdm
import pyproj

class OSM_Grabber:
    def __init__(self, type='bus', network=None, operator=None, area=None):
        # types of routes: bus, tram, trolleybus, subway, commuter
        # network (Московский транспорт)
        # operator (ГУП "Мосгортранс")
        # area - area id
        self.overpass_url="https://overpass-api.de/api/interpreter"
        self.type=type
        self.area=3600000000 + area
        if self.type!='commuter':
            base_query=f'[out:json][timeout:25];area({self.area})->.searchArea;nwr["route"={self.type}]'
        else:
            base_query=f'[out:json][timeout:25];area({self.area})->.searchArea;nwr["route"="train"]["service"="commuter"]'

        if network is not None:
            base_query+=f'["network"="{network}"]'
        if operator is not None:
            base_query+=f'["operator"="{operator}"]'
        base_query+='(area.searchArea);out geom;'
        self.query=base_query
        #print(self.overpass_url+'?data='+self.query)
    def fetch(self, s2s=True, out_dir=None):
        response = requests.get(self.overpass_url, params={'data': self.query})

        if response.status_code==400:
            raise ValueError('There is a problem with your request.\nThe problem may be the search area. Try to use (<relid>) with polygon relid from OSM')
        elif response.status_code==200:
            data = response.json()
            self.valid, self.invalid = self.check_ptv2(data)
            self.trips, self.stops = self.rebuild_data(self.valid)
            if s2s==True:
                self.s2s=self.create_s2s_connections(self.trips, self.stops)
            
            if out_dir is not None:
                with open(f'{out_dir}/{self.type}_trips.json', 'w', encoding='utf-8') as f:
                    json.dump(self.trips, f, ensure_ascii=False)
                with open(f'{out_dir}/{self.type}_stops.json', 'w', encoding='utf-8') as f:
                    json.dump(self.stops, f, ensure_ascii=False)
                if s2s==True:
                    with open(f'{out_dir}/{self.type}_s2s.json', 'w', encoding='utf-8') as f:
                        json.dump(self.s2s, f, ensure_ascii=False)
            if s2s==True:
                return self.trips, self.stops, self.s2s
    def check_ptv2(self, data):
        valid=[]
        invalid=[]
        for i in range(len(data['elements'])):
            elem=data['elements'][i]
            continue_stop_pl=0
            #print(elem.keys())
            if 'route' in elem['tags'].keys() and 'ref' in elem['tags'].keys() and 'name' in elem['tags'].keys():
                members=elem['members']
                count_stop = sum(1 for item in members if item.get('role') == 'stop')
                count_stop_entry_only=sum(1 for item in members if item.get('role') == 'stop_entry_only')
                count_stop_exit_only=sum(1 for item in members if item.get('role') == 'stop_exit_only')
                count_pl = sum(1 for item in members if item.get('role') == 'platform')
                count_pl_entry_only=sum(1 for item in members if item.get('role') == 'platform_entry_only')
                count_pl_exit_only=sum(1 for item in members if item.get('role') == 'platform_exit_only')

                if count_stop==count_pl and count_stop_entry_only==count_pl_entry_only and count_stop_exit_only==count_pl_exit_only:
                    print(elem['tags']['ref'], elem['id'], 'Valid counts', count_stop_entry_only, count_pl_entry_only, count_stop, count_pl, count_stop_exit_only, count_pl_exit_only)
                else:
                    print(elem['tags']['ref'], elem['id'], 'Invalid counts', count_stop_entry_only, '=', count_pl_entry_only, count_stop, '=', count_pl, count_stop_exit_only, '=', count_pl_exit_only)
                    continue_stop_pl=1
                for j in range(len(members)-1, 2):
                    m_c, m_n = members[j], members[j+1] # current, next
                    if m_c['role']!='':
                        if m_c['role']=='stop_entry_only' and m_n['role']=='platform_entry_only':
                            pass
                        else:
                            print('Warning: something with entry only')
                        if m_c['role']=='stop' and m_n['role']=='platform':
                            pass
                        else:
                            print('Error: platform is not after stop')
                            continue_stop_pl=1
                        if m_c['role']=='stop_exit_only' and m_n['role']=='stop_exit_only':
                            pass
                        else:
                            print('Warning: something with exit only')
                    else: break
            if continue_stop_pl==0:
                valid.append(elem)
            else:
                invalid.append(elem)
        print('Total valid: ', len(valid))
        print('Total invalid: ', len(invalid))
        print('Total: ', len(data['elements']))
        return valid, invalid
    
    def rebuild_data(self, data):
        refs=[]
        trips=[]
        stop2stop={}
        for elem in data:
            if 'route' in elem['tags'].keys():
                #print(elem['tags']['name'], end=' ')
                if 'name' in elem['tags'].keys():
                    trip_name=elem['tags']['name']
                else:
                    trip_name='UNKNOWN'
                if 'colour' in elem['tags'].keys():
                    trip_colour=elem['tags']['colour']
                else:
                    trip_colour=''
                if 'ref' in elem['tags'].keys():
                    trip_ref=elem['tags']['ref']
                else:
                    trip_ref='UNKNOWN'
                
                trip_stop_sequence=[]
                trip_shape=[]
                members=elem['members']
                
                for member in members:
                    if member['role']=='stop_entry_only' or member['role']=='stop' or member['role']=='stop_exit_only':
                        trip_stop_sequence.append(str(member['ref']))
                        if str(member['ref']) not in refs:
                            refs.append(str(member['ref']))
                    elif member['role']=='' and member['type']=='way':
                        trip_shape.append(member)
                trip_shape_g=self.build_shape(trip_shape)
                if self.type=='bus':
                    shape_merged=self.merge_shape_simple(trip_shape_g)
                else:
                    shape_merged=shapely.ops.linemerge(trip_shape_g)
                route_id=elem['id']
                trips.append({'stop_sequence': trip_stop_sequence, 'shape': shape_merged.wkt, 'colour': trip_colour, 'ref': trip_ref, 'route_id': route_id, 'route_name': trip_name})
        refs=list(set(refs))
        stops=self.fetch_stops(refs)
        return trips, stops
    def build_shape(self, shape):
        geom=[]
        for way in shape:
            geometry=way['geometry']
            coords=[[p['lon'], p['lat']] for p in geometry]
            geom.append(shapely.geometry.LineString(coords))
        geoms=shapely.geometry.MultiLineString(geom)
        return geoms
    def fetch_stops(self, stops):
        stops_info=[]
        platform_query=lambda ref: f'''
        [out:json][timeout:25];
        area({self.area})->.searchArea;
        nwr({ref})["public_transport"="stop_position"];
        out geom;'''
        data=[]
        for i in range(0, len(stops), 100):
            partial=stops[i:i+100]
            ref='id:'+','.join(partial)
            print(f'partial {i}:{i+100}', end=' ')
            time.sleep(1)
            response = requests.get(self.overpass_url, params={'data': platform_query(ref)})
            print(response.status_code)
            partial_data=response.json()['elements']
            data.extend(partial_data)
        for el in data:
            if 'tags' in el.keys():
                if 'public_transport' in el['tags'].keys():
                    if 'name' in el['tags'].keys():
                        name=el['tags']['name']
                    # need refactor bc previously there was platforms 
                    if 'lon' in el.keys():
                        # platform is point
                        geom=shapely.geometry.Point(el['lon'], el['lat'])
                    elif 'geometry' in el.keys():
                        #platform is way
                        ps=[]
                        for g in el['geometry']:
                            ps.append([g['lon'], g['lat']])
                        geom=shapely.geometry.MultiPoint(ps).centroid
                    else:
                        #platform is multipolygon
                        members=el['members']
                        ps=[]
                        for member in members:
                            for g in member['geometry']:
                                ps.append([g['lon'], g['lat']])
                        geom=shapely.geometry.MultiPoint(ps).centroid
                    if 'wheelchair' in el['tags'].keys():
                        wheelchair=el['tags']['wheelchair']
                    else:
                        wheelchair='no'
                stops_info.append({'stop_id': el['id'], 'stop_name': name, 'stop_shape': geom.wkt, 'wheelchair': wheelchair}) #!!
        return stops_info
    def wgs84toutm(self, geom, utmzone='EPSG:32637'):
        wgs84 = pyproj.CRS('EPSG:4326')
        utm = pyproj.CRS('EPSG:32637')
        project = pyproj.Transformer.from_crs(wgs84, utm, always_xy=True).transform
        return shapely.ops.transform(project, geom)
    def utmtowgs84(self, geom, utmzone='EPSG:32637'):
        wgs84 = pyproj.CRS('EPSG:4326')
        utm = pyproj.CRS('EPSG:32637')
        project = pyproj.Transformer.from_crs(utm, wgs84, always_xy=True).transform
        return shapely.ops.transform(project, geom)
    def get_shapes_of_stop_sequence(self, seq):
        seq_shapes=[]
        for stop in self.stops:
            if stop['stop_id'] in seq:
                seq_shapes.append(shapely.from_wkt(stop['stop_shape']))
        return seq_shapes
    def create_s2s_connections(self, trips, stops):
        self.stop2stop=[]
        #for trip_id in tqdm(list(trips.keys()), ncols=100, ascii=True, desc='Total'):
        for trip in tqdm(trips, ncols=100, ascii=True, desc='s2s connections'):
            trip_s_sequence=trip['stop_sequence']
            shape_geom=self.wgs84toutm(shapely.wkt.loads(trip['shape']))
            trip_s_sequence_shapes=self.get_shapes_of_stop_sequence(trip_s_sequence)
            shape_geom_ext=self.insert_stops_into_route(shape_geom, trip_s_sequence_shapes)
            for i in range(len(trip_s_sequence)-1):
                stop_1 = self.wgs84toutm(shapely.wkt.loads(list(filter(lambda x : str(x['stop_id'])==trip_s_sequence[i], self.stops))[0]['stop_shape']))
                stop_2 = self.wgs84toutm(shapely.wkt.loads(list(filter(lambda x : str(x['stop_id'])==trip_s_sequence[i+1], self.stops))[0]['stop_shape']))
                segment=self.cut_shape_by_stops(shape_geom_ext, stop_1, stop_2)
                dist=segment.length
                self.stop2stop.append({'from': trip_s_sequence[i], 'to': trip_s_sequence[i+1], 'shape': self.utmtowgs84(segment).wkt, 'length': dist, 'trip_ref': trip['ref'], 'trip_id': trip['route_id']})
        return self.stop2stop
    def cut_shape_by_stops(self, shape, stop_1, stop_2):
        i_s, i_e = 0, 0
        for i in range(len(list(shape.coords))):
            v=list(shape.coords)[i]
            if shapely.geometry.Point(v).equals(stop_1):
                i_s=i
            if shapely.geometry.Point(v).equals(stop_2):
                i_e=i
        return shapely.geometry.LineString(list(shape.coords)[i_s:i_e+1])
    def insert_stops_into_route(self, route, stops):
        # Create a list to hold all points (original route + stops)
        all_points = list(route.coords)
        d1_min, d2_min = math.inf, math.inf
        i1_min, i2_min = 0, 0
        for stop in stops:
            for i in range(len(all_points)-1):
                v1, v2 = shapely.geometry.Point(all_points[i]), shapely.geometry.Point(all_points[i+1])
                d1, d2 = v1.distance(stop), v2.distance(stop)
                if d1<d1_min and d2<d2_min:
                    i1_min, i2_min = i, i+1
                    d1_min, d2_min = d1, d2
            all_points=shapely.geometry.LineString([*all_points[:i1_min], (stop.x, stop.y), *all_points[i2_min:]])

        new_route = shapely.geometry.LineString(all_points)
        return new_route
    def merge_shape_simple(self, shape):
        multiline=shape
        line_segments=[line for line in multiline.geoms]
        ordered=line_segments.pop(0)
        l=len(line_segments)
        while l!=1:
            l=len(line_segments)
            for i in range(l):
                current_s=self.get_last(ordered)
                ordered_s_start=list(ordered.coords)[0]
                ordered_s_end=list(ordered.coords)[-1]
                current_s_end=list(current_s.coords)[-1]
                next_s=line_segments[i]
                next_s_start=list(next_s.coords)[0]
                next_s_end=list(next_s.coords)[-1]
                if next_s_start==next_s_end:
                    # round
                    circle_extend=shapely.geometry.LineString([*list(next_s.coords), *list(next_s.coords)])
                    if len(line_segments)==1:
                        line_segments.pop(i)
                        break
                    next2_s=line_segments[i+1]
                    touching_circle_1=circle_extend.intersection(current_s)
                    touching_circle_2=circle_extend.intersection(next2_s)
                    if touching_circle_1==touching_circle_2:
                        line_segments.pop(i)
                        break
                    splitted_circle=shapely.ops.split(circle_extend, shapely.geometry.MultiPoint((touching_circle_1, touching_circle_2)))
                    l=math.inf
                    minimal=None
                    for g in splitted_circle.geoms:
                        lg=g.length
                        if l>lg and g.touches(touching_circle_1) and g.touches(touching_circle_2):
                            l=lg
                            minimal=g
                    next_s=minimal
                    next_s_start=list(next_s.coords)[0]
                    next_s_end=list(next_s.coords)[-1]
                if current_s_end==next_s_start:
                    ordered=self.append_ordered(ordered, next_s)
                    line_segments.pop(i)
                    ordered=self.remove_duplicates(ordered)
                    break
                else:
                    if ordered_s_start==next_s_end:
                        ordered=self.append_ordered(self.flip(ordered), self.flip(next_s))
                        line_segments.pop(i)
                        ordered=self.remove_duplicates(ordered)
                        break
                    elif ordered_s_end==next_s_end:
                        ordered=self.append_ordered(ordered, self.flip(next_s))
                        line_segments.pop(i)
                        ordered=self.remove_duplicates(ordered)
                        break
                    elif ordered_s_end==next_s_start:
                        ordered=self.append_ordered(ordered, next_s)
                        line_segments.pop(i)
                        ordered=self.remove_duplicates(ordered)
                        break
                    elif ordered_s_start==next_s_start:
                        ordered=self.append_ordered(self.flip(ordered), next_s)
                        line_segments.pop(i)
                        ordered=self.remove_duplicates(ordered)
                        break
                    else:
                        ordered=self.append_ordered(ordered, shapely.geometry.LineString((current_s_end, next_s_start)))
                        line_segments.pop(i)
                        break
        return ordered
    def append_ordered(self, ordered, next):
        ordered_coords=list(ordered.coords)
        for pair in (next.coords):
            ordered_coords.append(pair)
        return shapely.geometry.LineString(ordered_coords)

    def get_last(self, ordered):
        ordered_coords=list(ordered.coords)
        return shapely.geometry.LineString(ordered_coords[-3:])

    def flip(self, line):
        reversed=list(line.coords)[::-1]
        return shapely.geometry.LineString(reversed)

    def remove_duplicates(self, shape):
        unordered=list(shape.coords)
        ordered=[]
        for p in unordered:
            if p not in ordered[-2:]:
                ordered.append(p)
        return shapely.geometry.LineString(ordered)
OSM_Grabber(type='bus', network=None, area=1281220).fetch(s2s=True, out_dir='akadem')
