#%%
import geopandas as gpd
import pandas as pd
import shapely
import folium
import matplotlib.pyplot as plt
m=folium.Map()
ref='419'
path='akadem'
stops=pd.read_json(path+'/bus_stops.json')
stops['geometry']=stops.apply(lambda s: shapely.from_wkt(s['stop_shape']), axis=1)
stops.drop('stop_shape', axis=1, inplace=True)
stops=gpd.GeoDataFrame(stops, geometry='geometry', crs='EPSG:4326')
stops.explore(m=m)

s2s=pd.read_json(path+'/bus_s2s.json')
s2s['geometry']=s2s.apply(lambda s: shapely.from_wkt(s['shape']), axis=1)
s2s.drop('shape', axis=1, inplace=True)
s2s=gpd.GeoDataFrame(s2s, geometry='geometry', crs='EPSG:4326')
#s2s[s2s['trip_ref']==ref].explore(m=m)

trips=pd.read_json(path+'/bus_trips.json')
trips['geometry']=trips.apply(lambda s: shapely.from_wkt(s['shape']), axis=1)
trips.drop('shape', axis=1, inplace=True)
trips=gpd.GeoDataFrame(trips, geometry='geometry', crs='EPSG:4326')
s2s[s2s['trip_ref']==ref].explore(m=m)
#trips[trips['ref']==ref].explore(m=m, color='red')
m
# %%
