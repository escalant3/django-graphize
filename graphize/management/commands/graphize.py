import networkx as nx

from django.core.management.base import BaseCommand
from django.db.models.fields.related import ForeignKey


class Command(BaseCommand):

    help = """Converts the data into graphical data."""

    def pajek_getattr(self, element, attr):
        ''' Removes unfriendly characters with Pajek specification '''
        value = getattr(element, attr)
        if type(value) == unicode:
            value = value.replace('"', '\'')
            value = value.replace('\n', ' ')
            value = value.replace('\r', ' ')
        return value

    def handle(self, *args, **options):
        import graphize_settings
        if len(args) < 1:
            print 'Usage: python manage.py graphize destination_file'
            return
        else:
            file_name = args[0]
        structure = graphize_settings.graph_structure
        gdb = nx.Graph()
        valid_models = structure.keys()
        for model_class in valid_models:
            model = structure[model_class]
            elements = model_class.objects.all()
            # Nodes and edges from data and One2Many relationships
            for element in elements:
                meta = element._meta
                node_id = '%d-%s' % (valid_models.index(model_class),
                                        element.id)
                gdb.add_node(node_id)
                node = gdb.node[node_id]
                for field in meta.fields:
                    #TODO Allow filter several fields
                    if isinstance(field, ForeignKey):
                        related_object = getattr(element, field.name)
                        if type(related_object) in valid_models:
                            related_object_type = type(related_object)
                            related_object_id = '%d-%s' % (valid_models.index(related_object_type),
                                                            related_object.id)
                            gdb.add_edge(node_id, related_object_id)
                        elif type(related_object) != None:
                            pass
                    else:
                        field_data = self.pajek_getattr(element, field.name)
                        if type(field_data) == unicode:
                            field_data = '"%s"' % field_data
                        if field_data:
                            node[field.name] = field_data
                node.update(model[0])
                for many_field in meta.many_to_many:
                    field = getattr(element, many_field.name)
                    related_model_class = many_field.rel.to
                    related_model_field_name = many_field.name
                    if related_model_class in valid_models:
                        valid_models_index = valid_models.index(related_model_class)
                        related_manager = getattr(element,
                                                    related_model_field_name)
                        for related_object in related_manager.iterator():
                            related_object_id = '%d-%s' % (valid_models_index,
                                                           related_object.id)
                            gdb.add_edge(node_id, related_object_id)
        import codecs
        fh = codecs.open(file_name, 'w', encoding='utf-8')
        nx.write_pajek(gdb, fh)
