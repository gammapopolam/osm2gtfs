# -*- coding: utf-8 -*-
import geopandas as gpd
import pandas as pd
import shapely
import json
import requests
import time
from urllib.parse import quote
import overpy

class OSM_Grabber:
    def __init__(self, type='bus', network=None, operator=None, area=None):
        # types of routes: bus, tram, trolleybus, subway, commuter
        # network (Московский транспорт)
        # operator (ГУП "Мосгортранс")
        # area - либо relation id, либо какой-то идентификатор. в случае Москвы - ["ref"="RU-MOW"]
        self.overpass_url="https://overpass-api.de/api/interpreter"
        self.type=type
        area=3600000000 + area
        if self.type!='commuter':
            base_query=f'[out:json][timeout:25];area({area})->.searchArea;nwr["route"={self.type}]'
        else:
            base_query=f'[out:json][timeout:25];area({area})->.searchArea;nwr["route"="train"]["service"="commuter"]'

        if network is not None:
            base_query+=f'["network"="{network}"]'
        if operator is not None:
            base_query+=f'["operator"="{operator}"]'
        base_query+='(area.searchArea);out geom;'
        self.query=base_query
        print(self.overpass_url+'?data='+self.query)
    def fetch(self, out_dir=None):
        response = requests.get(self.overpass_url, params={'data': self.query})

        if response.status_code==400:
            raise ValueError('There is a problem with your request.\nThe problem may be the search area. Try to use (<relid>) with polygon relid from OSM')
        elif response.status_code==200:
            data = response.json()
            self.valid, self.invalid = self.check_ptv2(data)
            self.trips, self.stops = self.rebuild_data(self.valid)
            if out_dir is not None:
                with open(f'{out_dir}/{self.type}_trips.json', 'w', encoding='utf-8') as f:
                    json.dump(self.trips, f, ensure_ascii=False)
                with open(f'{out_dir}/{self.type}_stops.json', 'w', encoding='utf-8') as f:
                    json.dump(self.stops, f, ensure_ascii=False)
            else:
                return self.trips, self.stops
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
        trips={}
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
                
                trip_platform_sequence=[]
                trip_shape=[]
                members=elem['members']
                
                for member in members:
                    if member['role']=='platform_entry_only' or member['role']=='platform' or member['role']=='platform_exit_only':
                        trip_platform_sequence.append(str(member['ref']))
                        if str(member['ref']) not in refs:
                            refs.append(str(member['ref']))
                    elif member['role']=='' and member['type']=='way':
                        trip_shape.append(member)
                trip_shape_g=self.build_shape(trip_shape)
                route_id=elem['id']
                trips[route_id]={'platform_sequence': trip_platform_sequence, 'shape': trip_shape_g.wkt, 'colour': trip_colour, 'ref': trip_ref, 'route_id': route_id, 'route_name': trip_name}
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
        #! area как переменная
        stops_info=[]
        platform_query=lambda ref: f'''
        [out:json][timeout:25];
        area["RU-MOW"]->.searchArea;
        nwr({ref})["public_transport"="platform"];
        out geom;'''
        data=[]
        for i in range(0, len(stops), 100):
            partial=stops[i:i+100]
            ref='id:'+','.join(partial)
            print(f'partial {i}:{i+100}', end=' ')
            time.sleep(2)
            response = requests.get(self.overpass_url, params={'data': platform_query(ref)})
            print(response.status_code)
            partial_data=response.json()['elements']
            data.extend(partial_data)
        for el in data:
            if 'tags' in el.keys():
                if 'public_transport' in el['tags'].keys():
                    if 'name' in el['tags'].keys():
                        name=el['tags']['name']
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
OSM_Grabber(type='commuter', network=None, area=173790).fetch('lobnya')