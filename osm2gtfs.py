import shapely
import geopandas as gpd
import pandas as pd
import math
import json
import pyproj
from tqdm import tqdm
import gtfs_kit as gk
pd.options.mode.chained_assignment = None

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
            if trip['route_master']=='NONE':
                route_id=trip['route_id']
            else:
                route_id=trip['route_master']
            shape_id=str(trip_id)+'_shp'
            # /!\ Messy and incorrect
            exist_dirs=self.trips_df.loc[self.trips_df['route_id']==route_id]
            if len(exist_dirs)%2==0:
                dir=0
            else:
                dir=1
            
            self.trips_df.loc[len(self.trips_df.index)] = [route_id, 0, trip_id, trip_name, dir, shape_id]

            base_time='00:00:00'
            minutes=0
            s=1
            self.stop_times_df.loc[len(self.stop_times_df)]=[trip_id, base_time, base_time, stop_sequence[0], s, 0, 0] #!

            for i in range(len(stop_sequence)-1):
                stop_c = stop_sequence[i]
                stop_n = stop_sequence[i+1]
                leg=self.find_leg(stop_c, stop_n, trip_id)
                speed_min=self.speed*1000/60
                traveltime=int((leg['length'])/speed_min)+1
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
            color=trip['colour'].replace('black', '#000000').replace('red', '##FF0000').replace('green', '#008000').replace('lime', '#00ff00')
            if trip['route_master']!='NONE':
                self.routes_df.loc[len(self.routes_df.index)]=[trip['route_master'], '0', trip['route_master_ref'], trip['route_master_name'].replace('<', '').replace('>', '').replace('=', '-'), route_type, color, '']
            else:
                self.routes_df.loc[len(self.routes_df.index)]=[trip['route_id'], '0', trip['ref'], trip['route_name'].replace('<', '').replace('>', '').replace('=', '-'), route_type, color, '']
        self.routes_df.drop_duplicates(subset='route_id', keep='first', inplace=True)
        
    def export(self, gtfs_dir):
        self.agency_df.to_csv(f'{gtfs_dir}/agency.txt', index=False, sep=',', header=True)
        self.stops_df.to_csv(f'{gtfs_dir}/stops.txt', index=False, sep=',', header=True)
        self.routes_df.to_csv(f'{gtfs_dir}/routes.txt', index=False, sep=',', header=True)
        self.trips_df.to_csv(f'{gtfs_dir}/trips.txt', index=False, sep=',', header=True)
        self.stop_times_df.to_csv(f'{gtfs_dir}/stop_times.txt', index=False, sep=',', header=True)
        self.shapes_df.to_csv(f'{gtfs_dir}/shapes.txt', index=False, sep=',', header=True)
        self.calendar_df.to_csv(f'{gtfs_dir}/calendar.txt', index=False, sep=',', header=True)
        self.calendar_dates_df.to_csv(f'{gtfs_dir}/calendar_dates.txt', index=False, sep=',', header=True)
    
class GTFS_Dataset:
    def __init__(self, gtfs_dir, from_dir=True):
        self.gtfs_dir=gtfs_dir
        self.agency_df=pd.read_csv(f'{gtfs_dir}/agency.txt', sep=',')
        self.stops_df=pd.read_csv(f'{gtfs_dir}/stops.txt', sep=',')
        self.routes_df=pd.read_csv(f'{gtfs_dir}/routes.txt', sep=',')
        self.trips_df=pd.read_csv(f'{gtfs_dir}/trips.txt', sep=',')
        self.stop_times_df=pd.read_csv(f'{gtfs_dir}/stop_times.txt', sep=',')
        self.shapes_df=pd.read_csv(f'{gtfs_dir}/shapes.txt', sep=',')
        self.calendar_df=pd.read_csv(f'{gtfs_dir}/calendar.txt', sep=',')
        self.calendar_dates_df=pd.read_csv(f'{gtfs_dir}/calendar_dates.txt', sep=',')
    def validate(self):
        self.feed=gk.read_feed(self.gtfs_dir, dist_units='km')
        problems=gk.validators.validate(self.feed, as_df=True, include_warnings=True)
        print(problems.to_markdown())
    def export(self, out_dir):
        self.agency_df.to_csv(f'{out_dir}/agency.txt', index=False, sep=',', header=True)
        self.stops_df.to_csv(f'{out_dir}/stops.txt', index=False, sep=',', header=True)
        self.routes_df.to_csv(f'{out_dir}/routes.txt', index=False, sep=',', header=True)
        self.trips_df.to_csv(f'{out_dir}/trips.txt', index=False, sep=',', header=True)
        self.stop_times_df.to_csv(f'{out_dir}/stop_times.txt', index=False, sep=',', header=True)
        self.shapes_df.to_csv(f'{out_dir}/shapes.txt', index=False, sep=',', header=True)
        self.calendar_df.to_csv(f'{out_dir}/calendar.txt', index=False, sep=',', header=True)
        self.calendar_dates_df.to_csv(f'{out_dir}/calendar_dates.txt', index=False, sep=',', header=True)
        print('Export complete in', out_dir)

def combine_gtfs_datasets(gtfs_ds_list, out_dir):
    agencies=[ds.agency_df for ds in gtfs_ds_list]
    agencies_bdf=pd.concat(agencies)
    agencies_bdf.drop_duplicates(inplace=True)
    stops=[ds.stops_df for ds in gtfs_ds_list]
    stops_bdf=pd.concat(stops)
    stops_bdf.drop_duplicates(inplace=True)
    routes=[ds.routes_df for ds in gtfs_ds_list]
    routes_bdf=pd.concat(routes)
    routes_bdf.drop_duplicates(inplace=True)
    trips=[ds.trips_df for ds in gtfs_ds_list]
    trips_bdf=pd.concat(trips)
    trips_bdf.drop_duplicates(inplace=True)
    stop_times=[ds.stop_times_df for ds in gtfs_ds_list]
    stop_times_bdf=pd.concat(stop_times)
    stop_times_bdf.drop_duplicates(inplace=True)
    shapes=[ds.shapes_df for ds in gtfs_ds_list]
    shapes_bdf=pd.concat(shapes)
    shapes_bdf.drop_duplicates(inplace=True)
    calendars=[ds.calendar_df for ds in gtfs_ds_list]
    calendar_bdf=pd.concat(calendars)
    calendar_bdf.drop_duplicates(inplace=True)
    calendar_dates=[ds.calendar_dates_df for ds in gtfs_ds_list]
    calendar_dates_bdf=pd.concat(calendar_dates)
    calendar_dates_bdf.drop_duplicates(inplace=True)

    agencies_bdf.to_csv(f'{out_dir}/agency.txt', index=False, sep=',', header=True)
    stops_bdf.to_csv(f'{out_dir}/stops.txt', index=False, sep=',', header=True)
    routes_bdf.to_csv(f'{out_dir}/routes.txt', index=False, sep=',', header=True)
    trips_bdf.to_csv(f'{out_dir}/trips.txt', index=False, sep=',', header=True)
    stop_times_bdf.to_csv(f'{out_dir}/stop_times.txt', index=False, sep=',', header=True)
    shapes_bdf.to_csv(f'{out_dir}/shapes.txt', index=False, sep=',', header=True)
    calendar_bdf.to_csv(f'{out_dir}/calendar.txt', index=False, sep=',', header=True)
    calendar_dates_bdf.to_csv(f'{out_dir}/calendar_dates.txt', index=False, sep=',', header=True)
    print('Combined GTFS saved in', out_dir)
