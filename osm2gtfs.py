import shapely
import geopandas as gpd
import pandas as pd
import math
import json
import pyproj
from tqdm import tqdm

class OSM2GTFS:
    def __init__(self, trips_f, stops_f, s2s_f, type, speed):
        self.speed=speed
        self.type=type
        with open(trips_f, 'r', encoding='utf-8') as f:
            self.trips=json.loads(f.read())
        with open(stops_f, 'r', encoding='utf-8') as f:
            self.stops=json.loads(f.read())
        with open(s2s_f, 'r', encoding='utf-8') as f:
            self.s2s=json.loads(f.read())
        self.agency_df = pd.DataFrame({
            'agency_id': ['0'],
            'agency_name': ['Sample Transit Agency'],
            'agency_url': ['http://www.sampletransit.com'],
            'agency_timezone': ['Europe/Moscow'],
            'agency_lang': ['ru'],
            'agency_phone': ['555-123-4567']
        })

        # Create stops.txt dataframe
        self.stops_df = pd.DataFrame({
            'stop_id': [],
            'stop_name': [],
            'stop_lat': [],
            'stop_lon': [],
            'location_type': [],
            'parent_station': []
        })

        # Create routes.txt dataframe
        self.routes_df = pd.DataFrame({
            'route_id': [],
            'agency_id': [],
            'route_short_name': [],
            'route_long_name': [],
            'route_type': [],
            'route_color': [],
            'route_text_color': []
        })

        # Create trips.txt dataframe
        self.trips_df = pd.DataFrame({
            'route_id': [],
            'service_id': [],
            'trip_id': [],
            'trip_headsign': [],
            'direction_id': [],
            'shape_id': []
        })

        # Create stop_times.txt dataframe
        self.stop_times_df = pd.DataFrame({
            'trip_id': [],
            'arrival_time': [],
            'departure_time': [],
            'stop_id': [],
            'stop_sequence': [],
            'pickup_type': [],
            'drop_off_type': []
        })

        # Create shapes.txt dataframe
        self.shapes_df = pd.DataFrame({
            'shape_id': [],
            'shape_pt_lat': [],
            'shape_pt_lon': [],
            'shape_pt_sequence': []
        })

        # Create calendar.txt dataframe
        self.calendar_df = pd.DataFrame({
            'service_id': ['0'],
            'monday': [1],
            'tuesday': [1],
            'wednesday': [1],
            'thursday': [1],
            'friday': [1],
            'saturday': [1],
            'sunday': [1],
            'start_date': ['20240101'],
            'end_date': ['20251231']
        })
        self.calendar_dates_df = pd.DataFrame({
            'service_id': ['0'],
            'date': ['20240101'],
            'exception_type': [1]  # 1 = service added, 2 = service removed
        })
    def add_stops(self):
        for t in self.stops:
            self.stops_df.loc[len(self.stops_df.index)] = [t['stop_id'], t['stop_name'], shapely.wkt.loads(t['stop_shape']).y, shapely.wkt.loads(t['stop_shape']).x, '0', '']
    
    # Функции проецирования между СК
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
    def minutes2hhmm(self, minutes):
        hh=minutes//60
        mm=minutes%60
        return f'{str(hh).zfill(2)}:{str(mm).zfill(2)}:00'
    def add_trips(self):
        f=open(f'logger_{self.type}.txt', encoding='utf-8', mode='w')
        f.close()
        f=open(f'logger_{self.type}.txt', encoding='utf-8', mode='a')
        for trip in tqdm(self.trips, ncols=100, ascii=True, desc='Appending trips and stop_times'):
            f=open(f'logger_{self.type}.txt', encoding='utf-8', mode='a')
            print(trip, file=f)
            f.close()
            stop_sequence=trip['stop_sequence']
            shape=shapely.wkt.loads(trip['shape'])
            trip_name=trip['route_name']
            trip_id=trip['route_id']
            shape_id=str(trip_id)+'_shp'
            dir=0
            # /!\ Currently, each trip is an unique route id. It is not properly correct. Don't really know how to handle it optimized
            self.trips_df.loc[len(self.trips_df.index)] = [trip_id, 0, trip_id, trip_name, dir, shape_id]

            base_time='00:00:00'
            minutes=0
            s=1
            self.stop_times_df.loc[len(self.stop_times_df)]=[trip_id, base_time, base_time, stop_sequence[0], s, 0, 0] #!

            for i in range(len(stop_sequence)-1):
                stop_c = stop_sequence[i]
                stop_n = stop_sequence[i+1]
                leg=self.find_leg(stop_c, stop_n, trip_id)
                speed_min=self.speed*1000/60
                traveltime=int((shapely.wkt.loads(leg['shape']).length)/speed_min)+1
                minutes+=traveltime
                time=self.minutes2hhmm(minutes)
                s+=1
                self.stop_times_df.loc[len(self.stop_times_df)]=[trip_id, time, time, stop_n, s, 0, 0]
            shape_pt_seq=1
            for x, y in list(shape.coords):
                
                self.shapes_df.loc[len(self.shapes_df)]=[shape_id, y, x, shape_pt_seq]
                shape_pt_seq+=1
    def find_leg(self, stop_c, stop_n, trip_id):
        for leg in self.s2s:
            if leg['from']==stop_c and leg['to']==stop_n and leg['trip_id']==trip_id:
                return leg
    def add_routes(self):
        if self.type=='tram' or self.type=='commuter':
            route_type='0'
        elif self.type=='bus':
            route_type='3'
        elif self.type=='subway':
            route_type='1'
        for trip in self.trips:
            color=trip['colour'].replace('black', '#000000').replace('red', '##FF0000')
            self.routes_df.loc[len(self.routes_df.index)]=[trip['route_id'], '0', trip['ref'], trip['route_name'], route_type, color, '']

    def export(self, gtfs_dir):
        self.agency_df.to_csv(f'{gtfs_dir}/agency.txt', index=False, sep=',', header=True)
        self.stops_df.to_csv(f'{gtfs_dir}/stops.txt', index=False, sep=',', header=True)
        self.routes_df.to_csv(f'{gtfs_dir}/routes.txt', index=False, sep=',', header=True)
        self.trips_df.to_csv(f'{gtfs_dir}/trips.txt', index=False, sep=',', header=True)
        self.stop_times_df.to_csv(f'{gtfs_dir}/stop_times.txt', index=False, sep=',', header=True)
        self.shapes_df.to_csv(f'{gtfs_dir}/shapes.txt', index=False, sep=',', header=True)
        self.calendar_df.to_csv(f'{gtfs_dir}/calendar.txt', index=False, sep=',', header=True)
        self.calendar_dates_df.to_csv(f'{gtfs_dir}/calendar_dates.txt', index=False, sep=',', header=True)
