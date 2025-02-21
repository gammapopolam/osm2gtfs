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
    def __init__(self, type='bus', network=None, operator=None, area=None, url=None):
        # types of routes: bus, tram, trolleybus, subway, commuter
        # network (Московский транспорт)
        # operator (ГУП "Мосгортранс")
        # area - area id
        if url is not None:
            self.overpass_url = url
        else:
            self.overpass_url="https://overpass-api.de/api/interpreter"
        self.type=type
        self.area=3600000000 + area
        if self.type!='commuter':
            if self.type=='bus':
                base_query=f'[out:json][timeout:25];area({self.area})->.searchArea;nwr["route"~"bus|trolleybus"]'
            else:
                base_query=f'[out:json][timeout:25];area({self.area})->.searchArea;nwr["route"={self.type}]'
            if network is not None:
                base_query+=f'["network"="{network}"]'
            if operator is not None:
                base_query+=f'["operator"="{operator}"]'
        # /!\ Messy query due to issues with commuter routes
        else:
            base_query=f'[out:json][timeout:25];area({self.area})->.searchArea;nwr(id:10309186,10309185,10309307,10309306,16213701,16213700,16272077,16272078,6548266,6548267)["route"="train"]["service"="commuter"]'
        
        base_query+='(area.searchArea);<<;out body geom;'
        self.query=base_query
        #print(self.overpass_url+'?data='+self.query)
    def fetch(self, s2s=True, out_dir=None):
        print(self.query)
        response = requests.get(self.overpass_url, params={'data': self.query})

        if response.status_code==400:
            raise ValueError('There is a problem with your request. Check area <rel id>')
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
        else:
            raise ValueError(response.status_code)
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
                # /!\ Messy validator that is not working at all
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
        for elem in data:
            if 'route' in elem['tags'].keys():
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
                if 'wheelchair' in elem['tags'].keys():
                    trip_wa=elem['tags']['wheelchair']
                else:
                    trip_wa='no'
                
                trip_stop_sequence=[]
                trip_shape=[]
                members=elem['members']
                
                for member in members:
                    if self.type=='subway' or self.type=='commuter' or self.type=='tram':
                        if member['role']=='platform_entry_only' or member['role']=='platform' or member['role']=='platform_exit_only':
                            trip_stop_sequence.append(str(member['ref']))
                            if str(member['ref']) not in refs:
                                refs.append(str(member['ref']))
                        elif member['role']=='' and member['type']=='way':
                            trip_shape.append(member)
                    else:
                        if member['role']=='stop_entry_only' or member['role']=='stop' or member['role']=='stop_exit_only':
                            trip_stop_sequence.append(str(member['ref']))
                            if str(member['ref']) not in refs:
                                refs.append(str(member['ref']))
                        elif member['role']=='' and member['type']=='way':
                            trip_shape.append(member)
                trip_shape_g=self.build_shape(trip_shape)
                #print(elem['id'])
                if self.type=='bus' or self.type=='trolleybus':
                    shape_merged=self.merge_shape_simple(trip_shape_g)
                else:
                    #print('merged shape')
                    shape_merged=shapely.ops.linemerge(trip_shape_g)
                    print(shape_merged)
                    if type(shape_merged)==shapely.geometry.multilinestring.MultiLineString:
                        shape_merged=self.merge_shape_simple(trip_shape_g)
                    if shape_merged.coords[0]==shape_merged.coords[-1]: #circle
                        #find first stop, find nearest vertex to stop, start from this vertex
                        first_ref=trip_stop_sequence[0]
                        first_stop=shapely.from_wkt(self.fetch_stop(first_ref)['stop_shape'])
                        little=math.inf
                        pmi=0
                        for i in range(len(shape_merged.coords)):
                            c=shape_merged.coords[i]
                            p=shapely.Point(c)
                            le=p.distance(first_stop)
                            if le<little:
                                pmi=i
                                little=le
                        refab=[*shape_merged.coords[pmi:]]
                        refab.extend(shape_merged.coords[:pmi+1])
                        shape_merged=shapely.LineString(refab)
                        
                    #print(shape_merged)
                route_id=elem['id']
                trips.append({'stop_sequence': trip_stop_sequence, 'shape': shape_merged.wkt, 'colour': trip_colour, 'ref': trip_ref, 'wheelchair': trip_wa, 'route_id': route_id, 'route_name': trip_name, 'route_master': 'NONE', 'route_master_name': 'NONE', 'route_master_ref': 'NONE'})
        for elem in data:
            if 'route_master' in elem['tags']:
                #print(elem['tags'])
                master=elem['id']
                if 'name' in elem['tags'].keys():
                    master_name=elem['tags']['name']
                else: master_name='UNKNOWN'
                if 'ref' in elem['tags'].keys():
                    master_ref=elem['tags']['ref']
                else: master_ref='UNKNOWN'
                childs=[]
                for member in elem['members']:
                    childs.append(member['ref'])
                for trip in trips:
                    if trip['route_id'] in childs:
                        trip['route_master']=master
                        trip['route_master_name']=master_name
                        trip['route_master_ref']=master_ref
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
    def fetch_stop(self, stop):
        if self.type=='subway' or self.type=='commuter' or self.type=='tram':
            tag='platform'
        else:
            tag='stop_position'
        stops_info=None
        platform_query=lambda ref: f'''
        [out:json][timeout:25];
        area({self.area})->.searchArea;
        nwr({ref})["public_transport"="{tag}"];
        out geom;'''
        #print(stop)
        response = requests.get(self.overpass_url, params={'data': platform_query(stop)})
        data=response.json()['elements']
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
                    #print(el['tags'])
                    if "wheelchair:description" in el['tags'].keys():
                        
                        if el['tags']['wheelchair:description']=="cross-platform":
                            wheelchair='cross-platform'
                        else:
                            wheelchair='limited'
                    else:
                        wheelchair=el['tags']['wheelchair']
                else:
                    wheelchair='no'
        stop_info={'stop_id': el['id'], 'stop_name': name, 'stop_shape': geom.wkt, 'wheelchair': wheelchair}
        return stop_info
    def fetch_stops(self, stops):
        if self.type=='subway' or self.type=='commuter' or self.type=='tram':
            tag='platform'
        else:
            tag='stop_position'
        stops_info=[]
        platform_query=lambda ref: f'''
        [out:json][timeout:25];
        area({self.area})->.searchArea;
        nwr({ref})["public_transport"="{tag}"];
        out geom;'''
        
        data=[]
        for i in range(0, len(stops), 100):
            partial=stops[i:i+100]
            ref='id:'+','.join(partial)
            print(f'partial {i}:{i+100}', end=' ')
            time.sleep(2)
            #print(platform_query(ref))
            response = requests.get(self.overpass_url, params={'data': platform_query(ref)})
            print(response.status_code)
            partial_data=response.json()['elements']
            data.extend(partial_data)
        for el in data:
            if 'tags' in el.keys():
                if 'public_transport' in el['tags'].keys() or 'disused:public_transport' in el['tags'].keys(): # обманка для некоторых приколов в СПб
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
                    #print(el['tags'])
                    if "wheelchair:description" in el['tags'].keys():
                        if el['tags']['wheelchair:description']=="cross-platform":
                            wheelchair='cross-platform'
                        else:
                            wheelchair='limited'
                    else:
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
                seq_shapes.append(self.wgs84toutm(shapely.from_wkt(stop['stop_shape'])))
        return seq_shapes
    def create_s2s_connections(self, trips, stops):
        self.stop2stop=[]
        #for trip_id in tqdm(list(trips.keys()), ncols=100, ascii=True, desc='Total'):
        for trip in tqdm(trips, ncols=100, ascii=True, desc='s2s connections'):
            trip_s_sequence=trip['stop_sequence']
            #print(trip)
            #print(trip['route_id'])
            shape_geom=self.wgs84toutm(shapely.wkt.loads(trip['shape']))
            trip_s_sequence_shapes=self.get_shapes_of_stop_sequence(trip_s_sequence)
            shape_geom_ext=self.insert_stops_into_route(shape_geom, trip_s_sequence_shapes)
            for i in range(len(trip_s_sequence)-1):
                #print('sequences', trip_s_sequence[i], trip_s_sequence[i+1])
                stop_1 = self.wgs84toutm(shapely.wkt.loads(list(filter(lambda x : str(x['stop_id'])==trip_s_sequence[i], self.stops))[0]['stop_shape']))
                stop_2 = self.wgs84toutm(shapely.wkt.loads(list(filter(lambda x : str(x['stop_id'])==trip_s_sequence[i+1], self.stops))[0]['stop_shape']))
                #print(stop_1, stop_2)
                # The main point of next lines is that routes on rail network can be located along non-unique platforms (i.e. island and shore types of platform), but it is not working properly for bus and tram.
                # That's why I use here platforms for subway/commuter and stop_positions for bus/tram
                if self.type=='subway' or self.type=='commuter' or self.type=='tram':
                    segment=self.cut_shape_by_stops(shape_geom, stop_1, stop_2)
                else:
                    segment=self.cut_shape_by_stops_bus(shape_geom_ext, stop_1, stop_2)
                dist=segment.length
                self.stop2stop.append({'from': trip_s_sequence[i], 'to': trip_s_sequence[i+1], 'shape': self.utmtowgs84(segment).wkt, 'length': dist, 'trip_ref': trip['ref'], 'trip_id': trip['route_id']})
        return self.stop2stop
    def cut_shape_by_stops(self, shape, stop_1, stop_2, type='first'):
        # for tram, commuter, subway
        stop_1_on_shape = shapely.ops.nearest_points(shape, stop_1)[0]
        stop_2_on_shape = shapely.ops.nearest_points(shape, stop_2)[0]

        stop_1_insert, stop_2_insert = 0, 0
        refab_shape=list(shape.coords)
        refab_shape.extend(list(shape.coords))
        # what if i double it? 
        for i in range(len(refab_shape)-1):
            line = shapely.geometry.LineString((refab_shape[i], refab_shape[i+1]))
            if line.intersects(stop_1_on_shape.buffer(1)):
                stop_1_insert=i
            if line.intersects(stop_2_on_shape.buffer(1)):
                stop_2_insert=i
            if stop_1_insert>0 and stop_2_insert>0 and stop_1_insert<stop_2_insert:
                break

        refab_shape.insert(stop_1_insert+1, stop_1_on_shape.coords[0])
        refab_shape.insert(stop_2_insert+1, stop_2_on_shape.coords[0])
        stop_1_index, stop_2_index = 0, 0
        for i in range(len(refab_shape)):
            if shapely.geometry.Point(refab_shape[i]).equals(stop_1_on_shape):
                stop_1_index=i
            if shapely.geometry.Point(refab_shape[i]).equals(stop_2_on_shape):
                stop_2_index=i
            if stop_1_index>0 and stop_2_index>0 and stop_1_index<stop_2_index:
                break
        #print(stop_1_index, stop_2_index)
        #if stop_1_index>stop_2_index:
        #    stop_1_index=len(refab_shape)-stop_1_index
        #print(stop_1_index, stop_2_index)
        #print(refab_shape[stop_1_index:stop_2_index+1])
            #print()
        '''        if type=='first':
            print(shapely.geometry.LineString(refab_shape[:stop_2_index]))
            return shapely.geometry.LineString(refab_shape[:stop_2_index])
        elif type=='last':
            print('last')
            print(shapely.geometry.LineString(refab_shape[stop_1_index:]))
            return shapely.geometry.LineString(refab_shape[stop_1_index:])
        else:'''
        #print(shapely.geometry.LineString(refab_shape[stop_1_index:stop_2_index+1]))
        res=shapely.geometry.LineString(refab_shape[stop_1_index:stop_2_index+1])
        if res.is_empty==False:
            return res
        else:
            return shapely.geometry.LineString((stop_1_on_shape, stop_2_on_shape))

    def cut_shape_by_stops_bus(self, shape, stop_1, stop_2):
        #print(shape)
        i_s, i_e = [], []
        l=len(list(shape.coords))
        #print(l)
        # The problem that some route share same segments and is being round. It moves through vertices in the start and in the end, so this alg gives last indices of vertices  
        for i in range(l):
            v=list(shape.coords)[i]
            if shapely.geometry.Point(v).equals(stop_1):
                i_s.append(i)
                #print('append i_s', i)
            if shapely.geometry.Point(v).equals(stop_2):
                i_e.append(i)
                #print('append i_e', i)
        #print(i_s, i_e)
        if len(i_s)>1 and len(i_e)==1:
            vars=[]
            #print(1)
            for k in range(len(i_s)):
                #print(i_s[k], i_e[0], i_s[k]-i_e[0])
                #if abs(i_e[0]-i_s[k])<100 and i_e[0]>i_s[k]:
                vars.append((i_s[k], i_e[0], i_s[k]-i_e[0]))
            #print(vars)
            need=min(vars, key=lambda x: x[-1])
            #print(need)
            return shapely.geometry.LineString(list(shape.coords)[need[0]:need[1]+1])
            #return shapely.geometry.LineString(list(shape.coords)[i_s[k]:i_e[0]+1])
        elif len(i_e)>1 and len(i_s)==1:
            vars=[]
            #print(2)
            for k in range(len(i_e)):
                vars.append((i_s[0], i_e[k], i_s[0]-i_e[k]))
                #if abs(i_e[k]-i_s[0])<50 and i_e[k]>i_s[0]:
                    #print(i_s[0], i_e[k])
                    #return shapely.geometry.LineString(list(shape.coords)[i_s[0]:i_e[k]+1])
            #print(vars)
            need=min(vars, key=lambda x: x[-1])
            #print(need)
            return shapely.geometry.LineString(list(shape.coords)[need[0]:need[1]+1])
        elif len(i_e)==1 and len(i_s)==1:
            #print(3)
            #print(i_s[0], i_e[0])
            return shapely.geometry.LineString(list(shape.coords)[i_s[0]:i_e[0]+1])
        else:
            # Avoid issues with strange shapes (см. А-482 Шёлково-СПб)
            #print(0)
            return shapely.geometry.LineString((stop_1, stop_2))
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

            
    def cut_shape_by_stops2(self, shape, stop_1, stop_2):
        # DEPRECATED
        # Эта функция привязывает точки остановок к шейпу маршрута, проводит линию между ними для получения сегмента пути.
        # Проблема в том, что геометрия маршрута может быть начата позже, чем идет последовательность остановок, и он режет до конца
        stop_1_on_shape = shapely.ops.nearest_points(shape, stop_1)[0]
        stop_2_on_shape = shapely.ops.nearest_points(shape, stop_2)[0]
        dx_stop1=(stop_1.x-stop_1_on_shape.x)*1.2
        dy_stop1=(stop_1.y-stop_1_on_shape.y)*1.2
        #print(stop_1_on_shape)
        #print(stop_2_on_shape)
        dx_stop2=(stop_2.x-stop_2_on_shape.x)*1.2
        dy_stop2=(stop_2.y-stop_2_on_shape.y)*1.2

        ep_stop1=shapely.geometry.LineString([(stop_1.x-dx_stop1, stop_1.y-dy_stop1), (stop_1_on_shape.x+dx_stop1, stop_1_on_shape.y+dy_stop1)])
        ep_stop2=shapely.geometry.LineString([(stop_2.x-dx_stop2, stop_2.y-dy_stop2), (stop_2_on_shape.x+dx_stop2, stop_2_on_shape.y+dy_stop2)])
        #print(ep_stop1)
        #print(ep_stop2)
        #print('source')
        #print(shape)
        segment_start=shape.difference(ep_stop1)
        #print('segment_start')
        #print(segment_start)
        
        if segment_start.is_empty==False:
            segment=segment_start.difference(ep_stop2)
        else:
            segment=shape.difference(ep_stop2)
        #print('segment_end')
        #print(segment)
        #print('\n')
        # Логика неправильная. Может выбрать не тот сегмент, надо смотреть по касанию ep_stops с сегментом
        le=math.inf
        little=None
        segment2=None
        #  and s.intersects(ep_stop1.buffer(1)) and s.intersects(ep_stop2.buffer(1)) and s.length<12000
        if type(segment)==shapely.geometry.multilinestring.MultiLineString:
            for s in segment.geoms:
                if le>s.length:
                    le=s.length
                    little=s
                
            segment2=little
        return segment2