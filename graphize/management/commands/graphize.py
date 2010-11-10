import codecs
import networkx as nx
import simplejson

from datetime import datetime

from django.core.management.base import BaseCommand
from django.db.models.fields.files import ImageFieldFile
from django.db.models.fields.related import ForeignKey
from django.utils.encoding import smart_unicode
from django.contrib.gis.db.models import *
from django.contrib.gis.geos.collections import MultiPolygon
from django.contrib.gis.geos.point import Point

import graphize_settings

GEO_TYPES = (MultiPolygon, Point)

class Command(BaseCommand):

    help = """Converts the data into graphical data."""

    def pajek_getattr(self, element, attr):
        ''' Removes unfriendly characters with Pajek specification '''
        value = getattr(element, attr)
        data_type = type(value)
        if data_type == unicode:
            value = value.replace('"', '\'')
            value = value.replace('\n', ' ')
            value = value.replace('\r', ' ')
        return smart_unicode(value) 

    def to_pajek_file(self, file_name, gdb):
        fh = codecs.open(file_name, 'w', encoding='utf-8')
        nx.write_pajek(gdb, fh)

    def neo4j_getattr(self, element, attr):
        ''' Removes unfriendly characters with neo4j specification '''
        value = getattr(element, attr)
        data_type = type(value)
        if data_type == datetime.datetime or data_type == datetime.date:
            value = str(value)
        elif data_type in GEO_TYPES:
            value = value.wkt
        elif data_type == ImageFieldFile:
            value = str(value)
        return value

    def to_neo4j_server(self, server, gdb):
        from neo4jclient import GraphDatabase
        neo = GraphDatabase(server)
        neo4j_nodes = {}
        for node1_id, node2_id in gdb.edges():
            if node1_id not in neo4j_nodes:
                node_dic = gdb.node[node1_id].copy()
                node_dic.update({'id': node1_id})
                neo4j_nodes[node1_id] = neo.node(**node_dic)
            if node2_id not in neo4j_nodes:
                node_dic2 = gdb.node[node2_id].copy()
                node_dic2.update({'id': node2_id})
                neo4j_nodes[node2_id] = neo.node(**node_dic2)
            edge_data = gdb.edge[node1_id][node2_id]
            if edge_data:
                edge_type = edge_data.get('type', None)
                if edge_type:
                    getattr(neo4j_nodes[node1_id], edge_type)(neo4j_nodes[node2_id])
                else:
                    neo4j_nodes[node1_id].RELATED(neo4j_nodes[node2_id])
            else:
                neo4j_nodes[node1_id].RELATED(neo4j_nodes[node2_id])

    def to_sylva_file(self, file_name, gdb):
        semantic = graphize_settings.SEMANTIC_RELATIONSHIPS
        sylva_export = {'nodes': [], 'edges':[]}
        for node in gdb.nodes():
            sylva_export['nodes'].append(gdb.node[node])
        for node1_id, node2_id in gdb.edges():
            node1 = gdb.node[node1_id]
            node2 = gdb.node[node2_id]
            node1_type = node1['type']
            node2_type = node2['type']
            if (node1_type, node2_type) in semantic:
                sylva_export['edges'].append((node1, node2, 
                            semantic[(node1_type, node2_type)]))
            elif (node2_type, node1_type) in semantic:
                sylva_export['edges'].append((node2, node1, 
                            semantic[(node2_type, node1_type)]))
            else:
                print "Unknown semantic relationship (%s, %s)" % (node1_type,
                                                                    node2_type)
        fh = codecs.open(file_name, 'w', encoding='utf-8')
        fh.write(simplejson.dumps(sylva_export))
        fh.close()
    
    def handle(self, *args, **options):
        if len(args) < 2:
            print """Usage: python manage.py graphize OUTPUT_TYPE OUTPUT

Where OUTPUT_TYPE can be:
- neo4j: Neo4j Graph Database
- sylva: Sylva Graph Database
- pajek: .net pajek file

and OUTPUT is the destination server/file.

Example:
python manage.py graphize neo4j http://localhost:9999
                    """
            return
        else:
            if args[0] == 'neo4j':
                format_function = self.neo4j_getattr
                output_function = self.to_neo4j_server
                destination = args[1]
            elif args[0] == 'pajek':
                format_function = self.pajek_getattr
                output_function = self.to_pajek_file
                destination = args[1]
            elif args[0] == 'sylva':
                format_function = self.neo4j_getattr
                output_function = self.to_sylva_file
                destination = args[1]
            else:
                print 'Unknown OUTPUT_TYPE %s' % args[0]
        structure = graphize_settings.graph_structure
        gdb = nx.Graph()
        valid_models = structure.keys()
        for model_class in valid_models:
            model = structure[model_class]
            elements = model_class.objects.all()
            # Nodes and edges from data and One2Many relationships
            for element in elements:
                meta = element._meta
                node_id = '%s%s' % (model_class.__name__,
                                        element.id)
                gdb.add_node(node_id)
                node = gdb.node[node_id]
                meta_fields = [f for f in meta.fields if f.name not in model[1]]
                for field in meta_fields:
                    #TODO Allow filter several fields
                    if isinstance(field, ForeignKey):
                        related_object = getattr(element, field.name)
                        if type(related_object) in valid_models:
                            related_object_type = type(related_object)
                            related_object_id = '%s%s' % (related_object_type.__name__,
                                                            related_object.id)
                            gdb.add_edge(node_id, related_object_id)
                            gdb.edge[node_id][related_object_id]['type'] = field.name
                        elif type(related_object) != None:
                            pass
                    else:
                        field_data = format_function(element, field.name)
                        if field_data:
                            node[field.name] = field_data
                swapping_nodes = model[2]
                for old_field, new_field, delete in swapping_nodes:
                    node[new_field] = node[old_field]
                    if delete:
                        node.pop(old_field)
                node.update(model[0])
                for many_field in meta.many_to_many:
                    field = getattr(element, many_field.name)
                    related_model_class = many_field.rel.to
                    related_model_field_name = many_field.name
                    if related_model_class in valid_models:
                        related_manager = getattr(element,
                                                    related_model_field_name)
                        for related_object in related_manager.iterator():
                            related_object_id = '%s%s' % (related_model_class.__name__,
                                                           related_object.id)
                            gdb.add_edge(node_id, related_object_id)
                            gdb.edge[node_id][related_object_id]['type'] = related_model_field_name
        output_function(destination, gdb)
