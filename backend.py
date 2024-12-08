import osmnx as ox
import pandas as pd
import geopandas as gd
import networkx as nx
from shapely import geometry, wkt

import psycopg2
from psycopg2 import Error

ox.settings.bidirectional_network_types = ["drive"]

''' Определение тегов '''
tags_port = {'industrial' : 'port'}
tags_aeroway = {'aeroway' : ['aerodrome','heliport', 'airstrip']}
tags_landuse = {'landuse' : 'railway'}
tags_build = {'building' : 'warehouse', 'amenity' : 'mailroom'}

''' Построение датафрейма нужных фич '''
def func_tags(tags, city):

    try:
        gdf = ox.features_from_place(city, tags).reset_index()
        gdf = gdf[['element', 'id']]
        gdf['n_osmid'] = gdf['element'].apply(lambda x: x[0]) + gdf['id'].astype(str)

        list_lat_lon = []
        for i in range(gdf.n_osmid.shape[0]):
            try:
                bb = ox.geocode_to_gdf(gdf.n_osmid.iloc[i], by_osmid=True)[['lat', 'lon']]
                list_lat_lon.append(bb.iloc[:])
            except ox._errors.InsufficientResponseError:
                list_lat_lon.append(pd.DataFrame({'lat': [None], 'lon': [None]}))
        dfs = pd.concat(list_lat_lon, axis=0).reset_index(drop=True)
        gdf = gdf.merge(dfs, on=dfs.index).drop('key_0', axis=1)
        gdf = gdf[['lat', 'lon']]
        gdf['kind_of'] = list(tags.keys())[0]
        gdf = gdf.dropna().reset_index(drop=True)
        return gdf
    except ox._errors.InsufficientResponseError:
        return None

''' Построение графа, получение датафрейма фич и получение датафрейма долгот и широт для дальшейших вычислений '''
def create_graph_city(name_city, my_network_type = None, my_filter = None):
    full_df = pd.concat([func_tags(tags_port, name_city), 
                                    func_tags(tags_aeroway, name_city), 
                                    func_tags(tags_landuse, name_city), 
                                    func_tags(tags_build, name_city)], ignore_index=True)
    G = ox.graph_from_place(name_city, retain_all=True, simplify = True, network_type = my_network_type, custom_filter = my_filter)

    lat = list(full_df['lat'].values)
    lon = list(full_df['lon'].values)

    return full_df, G, lat, lon

''' Формирование датафрейма фич '''
def create_features_city(features_df, city_graph, lat, lon):
    features_df['new_nodes'] = ox.distance.nearest_nodes(city_graph, lon, lat)
    return features_df


''' Создание датафрейма со всеми маршрутами '''
def create_graph_route(input_graph, f_df):
    one_route = []
    for i in range(f_df.shape[0]):
        for j in range(i + 1, f_df.shape[0]):
            try:
                one_route.append(nx.shortest_path(input_graph, f_df['new_nodes'].iloc[i], f_df['new_nodes'].iloc[j]))
            except nx.NetworkXNoPath:
                pass
    route_df = pd.DataFrame({'route' : one_route})
    return route_df


''' Создание из нескольких LineString один MultiLineString - нужно для финального графа '''
def create_gdf_graph(nn, ee):
    ii = 0
    list_line = []
    list_multi_line = []
    for i in range(nn.shape[0] - 1):
        idx = nn.iloc[i + 1].new_nodes
        for j in range(ii, ee.index.get_level_values('u').shape[0]):
            if ee.index.get_level_values('u')[j] != idx:
                for k in range(len(ee.loc[ee.index.get_level_values('u')[j]]['geometry'].values)):
                    list_line.append(ee.loc[ee.index.get_level_values('u')[j]]['geometry'].values[k])
            else : 
                ii = j
        multi_line = geometry.MultiLineString(list_line)
        list_line = []
        list_multi_line.append(multi_line)
    return list_multi_line


''' Построение финального графа путей '''
def create_final_graph(arb_graph, route_df, feature_df):
    list_graphs = []
    for i in range(route_df.route.shape[0]):
        r = route_df['route'].values[i]

        rr = gd.GeoDataFrame({'new_nodes' : r}, crs=None)
        rr['id'] = rr['new_nodes']
        rr = rr.set_index('id')
        rr['x'] = rr.new_nodes.apply(lambda x: arb_graph.nodes[x]['x'])
        rr['y'] = rr.new_nodes.apply(lambda x: arb_graph.nodes[x]['y'])

        edge_dict = {'u': rr.new_nodes[:-1].values, 'v': rr.new_nodes[1:].values, 'key': 0}
        edge_gdf = gd.GeoDataFrame(edge_dict, crs=None)
        edge_gdf = edge_gdf.set_index(['u', 'v', 'key'])

        graph_attrs = {"crs": "WGS84"}
        multi_digraph_aero = ox.convert.graph_from_gdfs(
            rr, edge_gdf, graph_attrs=graph_attrs)
        
        list_graphs.append(multi_digraph_aero)
        
    my_graph = list_graphs[0]
    for i in range(1, len(list_graphs)):
        my_graph = nx.compose_all([my_graph, list_graphs[i]])

    nodes, edges = ox.graph_to_gdfs(my_graph)
    list_nodes = list(feature_df['new_nodes'].values)
    n = nodes[nodes['new_nodes'].isin(list_nodes)]

    list_multiline = create_gdf_graph(n, edges)
    edge_dict = {'u': n.new_nodes[:-1].values, 'v': n.new_nodes[1:].values, 'key': 0}
    edge_gdf = gd.GeoDataFrame(edge_dict, crs=None)
    edge_gdf = edge_gdf.set_index(['u', 'v', 'key'])
    edge_gdf['geometry'] = list_multiline
    graph_attrs = {"crs": "WGS84"}
    multi_digraph = ox.graph_from_gdfs(
        n, edge_gdf, graph_attrs=graph_attrs)
    
    return multi_digraph

def result(name_city):
    graph_city = create_graph_city(name_city, my_network_type = 'drive')
    feature_df = create_features_city(*graph_city)
    ox.distance.add_edge_lengths(graph_city[1], edges=None)
    route_df = create_graph_route(graph_city[1], feature_df)
    final_graph_1_drive = create_final_graph(graph_city[1], route_df, feature_df)
    return final_graph_1_drive

def check_connect_db():
    try:
        connection = psycopg2.connect(user="postgres",
                                    password="g15",
                                    host="127.0.0.1",
                                    port="5432",
                                    database="postgis_34_sample")

        cursor = connection.cursor()
        print("Информация о сервере PostgreSQL")
        print(connection.get_dsn_parameters(), "\n")
        
        # Проверка, есть ли PostGIS
        cursor.execute("SELECT PostGIS_Full_Version();")

        record = cursor.fetchone()
        print("Вы подключены к - ", record, "\n")

    except (Exception, Error) as error:
        print("Ошибка при работе с PostgreSQL", error)
    finally:
        if connection:
            cursor.close()
            connection.close()
            print("Соединение с PostgreSQL закрыто")

def create_table_in_db(name_table_nodes, name_table_edges):
    try:
        connection = psycopg2.connect(user="postgres",
                                    password="g15",
                                    host="127.0.0.1",
                                    port="5432",
                                    database="postgis_34_sample")

        cursor = connection.cursor()
        create_table_query_1 = '''CREATE TABLE {}
                            (osmid FLOAT PRIMARY KEY     NOT NULL,
                            x           FLOAT    NOT NULL,
                            y         FLOAT    NOT NULL,
                            geometry  geometry   NOT NULL); '''.format(name_table_nodes)
        
        create_table_query_2 = '''CREATE TABLE {}
                            (u FLOAT PRIMARY KEY     NOT NULL,
                            v           FLOAT    NOT NULL,
                            key         FLOAT    NOT NULL,
                            geometry  geometry   NOT NULL); '''.format(name_table_edges)
        

        cursor.execute(create_table_query_1)
        cursor.execute(create_table_query_2)
        connection.commit()
        print("Таблица успешно создана в PostgreSQL")

    except (Exception, Error) as error:
        print("Ошибка при работе с PostgreSQL", error)
    finally:
        if connection:
            cursor.close()
            connection.close()
            print("Соединение с PostgreSQL закрыто")

def insert_to_table(df, table):

    connection = psycopg2.connect(user="postgres",
                                  password="g15",
                                  host="127.0.0.1",
                                  port="5432",
                                  database="postgis_34_sample")

    tuples = [tuple(x) for x in df.to_numpy()]
    cols = ','.join(list(df.columns))
    query  = "INSERT INTO %s(%s) VALUES(%%s,%%s,%%s,ST_AsText(%%s))" % (table, cols)

    cursor = connection.cursor()
    try:
        cursor.executemany(query, tuples)
        connection.commit()
        print("insert_to_table() done")

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

def drop_table(table):

    connection = psycopg2.connect(user="postgres",
                                  password="g15",
                                  host="127.0.0.1",
                                  port="5432",
                                  database="postgis_34_sample")

    query  = "DELETE FROM {}".format(table)

    cursor = connection.cursor()
    try:
        cursor.execute(query)
        connection.commit()
        print("drop_table() done")

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

def convert_df_in_geodf(res_1):
    nodes_1, edges_1 = ox.graph_to_gdfs(res_1)
    nodes_1 = nodes_1.drop(['new_nodes'], axis=1)
    nodes_1 = nodes_1[['y', 'x', 'geometry']]
    nodes_1['geometry'] = nodes_1.geometry.apply(wkt.dumps)
    edges_1['geometry'] = edges_1.geometry.apply(wkt.dumps)
    df_nodes = nodes_1.reset_index()
    df_edges = edges_1.reset_index()
    # edges_1 = edges_1.set_index(['u', 'v', 'key'])
    # edges_1['geometry'] = edges_1['geometry'].apply(wkt.loads)
    # nodes_1['geometry'] = nodes_1['geometry'].apply(wkt.loads)
    # df_edges = gd.GeoDataFrame(edges_1, crs = 'WGS84')
    # df_nodes = gd.GeoDataFrame(nodes_1, crs = 'WGS84')
    return (df_nodes, df_edges)

name_city = 'Helsinki'
res_1 = result(name_city)

name_nodes_table = name_city.lower() + '_nodes'
name_edges_table = name_city.lower() + '_edges'

# check_connect_db()
create_table_in_db(name_nodes_table, name_edges_table)
insert_to_table(convert_df_in_geodf(res_1)[0], name_nodes_table)
insert_to_table(convert_df_in_geodf(res_1)[1], name_edges_table)


