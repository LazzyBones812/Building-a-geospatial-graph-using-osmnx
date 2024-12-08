import folium
from django.shortcuts import render,redirect

import psycopg2
from psycopg2 import Error

def read_nodes_table(table):

    connection = psycopg2.connect(user="postgres",
                                  password="g15",
                                  host="127.0.0.1",
                                  port="5432",
                                  database="postgis_34_sample")

    query = """SELECT osmid, x, y, ST_AsText(geometry) FROM {}""".format(table)

    cursor = connection.cursor()
    try:
        cursor.execute(query)
        connection.commit()
        print("read_table() done")
        return cursor.fetchall()

    except (Exception, psycopg2.DatabaseError) as error:
        print("Error: %s" % error)
        connection.rollback()
        cursor.close()
        return 1
    
    finally:
        if connection:
            cursor.close()
            connection.close()
            print("Соединение с PostgreSQL закрыто")

def read_edges_table(table):

    connection = psycopg2.connect(user="postgres",
                                  password="g15",
                                  host="127.0.0.1",
                                  port="5432",
                                  database="postgis_34_sample")

    query = """SELECT u, v, key, ST_AsText(geometry) FROM {}""".format(table)

    cursor = connection.cursor()
    try:
        cursor.execute(query)
        connection.commit()
        print("read_table() done")
        return cursor.fetchall()

    except (Exception, psycopg2.DatabaseError) as error:
        print("Error: %s" % error)
        connection.rollback()
        cursor.close()
        return 1
    
    finally:
        if connection:
            cursor.close()
            connection.close()
            print("Соединение с PostgreSQL закрыто")


def showmap(request):
    return render(request,'showmap.html')

import osmnx as ox
import pandas as pd
import geopandas as gd
import networkx as nx
import geopy
from geopy.geocoders import Nominatim
from shapely import geometry, wkt



def showroutes(request, metrics, lat1, long1):
    locator = Nominatim(user_agent = "myapp")
    loc = locator.reverse(lat1 + ' , ' + long1)
    address = loc.raw['address']
    city_from = address.get('city', '')
    figure = folium.Figure()
    m = folium.Map(location=[(lat1),
                                 (long1)], 
                       zoom_start=10)
    m.add_to(figure)


    # gdf_nodes = pd.read_csv('../Analytics/nodes_' + city_from + '.csv', delimiter=",")
    # gdf_edges = pd.read_csv('../Analytics/edges_' + city_from + '.csv', delimiter=",")

    # gdf_nodes_new = gdf_nodes.set_index('osmid').drop(['new_nodes'], axis=1)
    # gdf_nodes_new = gdf_nodes_new[['y', 'x', 'geometry']]
    # gdf_edges_new = gdf_edges.set_index(['u', 'v', 'key'])

    # gdf_edges_new['geometry'] = gdf_edges_new['geometry'].apply(wkt.loads)
    # gdf_nodes_new['geometry'] = gdf_nodes_new['geometry'].apply(wkt.loads)

    # df_edges = gd.GeoDataFrame(gdf_edges_new, crs = 'WGS84')
    # df_nodes = gd.GeoDataFrame(gdf_nodes_new, crs = 'WGS84')
    
    nodes = read_nodes_table(city_from.lower() + '_nodes')
    edges = read_edges_table(city_from.lower() + '_edges')

    df_edges = pd.DataFrame(edges, columns=['u', 'v', 'key', 'geometry'])
    df_edges = df_edges.set_index(['u', 'v', 'key'])
    df_edges['geometry'] = df_edges['geometry'].apply(wkt.loads)
    df_edges = gd.GeoDataFrame(df_edges, crs="epsg:4326")

    df_nodes = pd.DataFrame(nodes, columns=['osmid', 'x', 'y', 'geometry'])
    df_nodes = df_nodes.set_index('osmid')
    df_nodes = df_nodes[['y', 'x', 'geometry']]
    df_nodes['geometry'] = df_nodes['geometry'].apply(wkt.loads)
    df_nodes = gd.GeoDataFrame(df_nodes, crs="epsg:4326")

    #df_edges = pd.read_csv("../Analytics/edges_" + city_from + ".csv", delimiter=",")
    #df_edges['geometry'] = df_edges['geometry'].apply(wkt.loads)
    #gdf_edges = gd.GeoDataFrame(df_edges, crs="epsg:4326")

    #df_nodes = pd.read_csv("../Analytics/nodes_" + city_from + ".csv", delimiter=",")
    #df_nodes['geometry'] = df_nodes['geometry'].apply(wkt.loads)
    #gdf_nodes = gd.GeoDataFrame(df_nodes, crs="epsg:4326")

    graph = ox.graph_from_gdfs(df_nodes, df_edges)
    metrics_1 = nx.degree_centrality(graph)
    metrics_2 = nx.closeness_centrality(graph)
    metrics_3 = nx.betweenness_centrality(graph)
    metrics_4 = nx.pagerank(graph, alpha = 0.8)
    
    folium.GeoJson(df_edges).add_to(m)

    chosen_metrics = metrics

    match chosen_metrics:
        case "degree":
            df_nodes["metric"] = df_nodes.index.map(metrics_1)
        case "closeness":
            df_nodes["metric"] = df_nodes.index.map(metrics_2)
        case "betweenness":
            df_nodes["metric"] = df_nodes.index.map(metrics_3)
        case "pagerank":
            df_nodes["metric"] = df_nodes.index.map(metrics_4)
        case _:
            df_nodes["metric"] = 0

    df_nodes["marker_color"] = pd.cut(df_nodes["metric"], bins=4, labels=['green', 'yellow', 'orange', 'red'])
    for index, poi in df_nodes.iterrows():
        folium.features.CircleMarker(
            [df_nodes.loc[index, 'y'], df_nodes.loc[index, 'x']], radius = 5,
            color = df_nodes.loc[index, 'marker_color'], fill_color = df_nodes.loc[index, 'marker_color'], 
            fill = True, fill_opacity=0.7, popup=folium.Popup(str(df_nodes.loc[index, 'metric']))
        ).add_to(m)
    #folium.GeoJson(gdf_nodes).add_to(m)

    figure.render()
    context={'map':figure}
    return render(request,'showroute.html',context)