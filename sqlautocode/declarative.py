import sys, re, inspect
from util import emit
from sqlalchemy.ext.sqlsoup import SqlSoup
from sqlalchemy import MetaData
from sqlalchemy.ext.declarative import declarative_base, _deferred_relation
from sqlalchemy.orm import relation, backref, class_mapper, RelationProperty
from formatter import column_repr

# lifted from http://www.daniweb.com/forums/thread70647.html
# (pattern, search, replace) regex english plural rules tuple
rule_tuple = (
('[ml]ouse$', '([ml])ouse$', '\\1ice'), 
('child$', 'child$', 'children'), 
('booth$', 'booth$', 'booths'), 
('foot$', 'foot$', 'feet'), 
('ooth$', 'ooth$', 'eeth'), 
('l[eo]af$', 'l([eo])af$', 'l\\1aves'), 
('sis$', 'sis$', 'ses'), 
('man$', 'man$', 'men'), 
('ife$', 'ife$', 'ives'), 
('eau$', 'eau$', 'eaux'), 
('lf$', 'lf$', 'lves'), 
('[sxz]$', '$', 'es'), 
('[^aeioudgkprt]h$', '$', 'es'), 
('(qu|[^aeiou])y$', 'y$', 'ies'), 
('$', '$', 's')
)
 
def regex_rules(rules=rule_tuple):
    for line in rules:
        pattern, search, replace = line
        yield lambda word: re.search(pattern, word) and re.sub(search, replace, word)
 
def plural(noun):
    for rule in regex_rules():
        result = rule(noun)
        if result: 
            return result

def name2label(name):
    """
    Convert a column name to a Human Readable name.
    borrowed from old TG fastdata code
    """
    # Create label from the name:
    #   1) Convert _ to Nothing
    #   2) Convert CamelCase to Camel Case
    #   3) Upcase first character of Each Word
    # Note: I *think* it would be thread-safe to
    #       memoize this thing.
    return str(''.join([s.capitalize() for s in
               re.findall(r'([A-Z][a-z0-9]+|[a-z0-9]+|[A-Z0-9]+)', name)]))

class ModelFactory(object):
    
    def __init__(self, config):
        self.config = config
        schema = getattr(self.config, 'schema', None)
        self._metadata = MetaData(bind=config.engine)
        if schema:
            self._metadata.schema = schema
        self._metadata.reflect()
        
        self.DeclarativeBase = declarative_base(metadata=self._metadata)

    @property
    def tables(self):
        return self._metadata.tables.keys()
    
    @property
    def models(self):
        return [self.create_model(table) for table in self.get_non_many_to_many_tables()]
    
    def create_model(self, table):
        #partially borred from Jorge Vargas' code
        #http://dpaste.org/V6YS/
        
        model_name = name2label(table.name)
        class Temporal(self.DeclarativeBase):
            __table__ = table
            
            @classmethod
            def _relation_repr(cls, rel):
                target = rel.argument
                if target and inspect.isfunction(target):
                    target = target()
                target = target.__name__
                secondary = ''
                if rel.secondary:
                    secondary = ", secondary=%s"%rel.secondary.name
                backref=''
                if rel.backref:
                    backref=", backref='%s'"%rel.backref.key
                return "%s = relation(%s%s%s)"%(rel.key, target, secondary, backref)
            
            @classmethod
            def __repr__(cls):
                mapper = class_mapper(cls)
                s = ""
                s += "class "+model_name+'(DeclarativeBase):\n'
                s += "    __table_name__ = '%s'\n\n"%table.name
                s += "    #column definitions\n"
                for column in cls.__table__.c:
                    s += "    %s = %s\n"%(column.name, column_repr(column))
                s += "\n    #relation definitions\n"
                ess = s
                for prop in mapper.iterate_properties:
                    if isinstance(prop, RelationProperty):
                        s+='    %s\n'%cls._relation_repr(prop)
                return s

        #hack the class to have the right classname
        Temporal.__name__ = model_name
        
        #trick sa's model registry to think the model is the correct name
        if model_name != 'Temporal':
            Temporal._decl_class_registry[model_name] = Temporal._decl_class_registry['Temporal']
            del Temporal._decl_class_registry['Temporal']

        #add in single relations
        for column in self.get_foreign_keys(table):
            related_table = column.foreign_keys[0].column.table
            backref = plural(table.name)
            setattr(Temporal, related_table.name, _deferred_relation(Temporal, relation(name2label(related_table.name), backref=backref)))
        
        #add in many-to-many relations
        for join_table in self.get_related_many_to_many_tables(table.name):
            for column in join_table.columns:
                key = column.foreign_keys[0]
                if key.column.table is not table:
                    related_table = column.foreign_keys[0].column.table
                    backref = plural(table.name)
                    setattr(Temporal, plural(related_table.name), _deferred_relation(Temporal, relation(name2label(related_table.name), secondary=join_table)))
                    break;

        return Temporal

    def get_table(self, name):
        """(name) -> sqlalchemy.schema.Table
        get the table definition with the given table name
        """
        if hasattr(self._metadata, 'schema'):
            schema = self._metadata.schema
            if schema and not name.startswith(schema):
                name = '.'.join((schema, name))
        return self._metadata.tables[name]

    def get_foreign_keys(self, table):
        return [column for column in table.columns if len(column.foreign_keys)>0]

    def get_many_to_many_tables(self):
        if not hasattr(self, '_many_to_many_tables'):
            self._many_to_many_tables = [table for table in self._metadata.tables.values() if len(self.get_foreign_keys(table)) == 2 and len(table.c) == 2]
        return self._many_to_many_tables

    def get_non_many_to_many_tables(self):
        return [table for table in self._metadata.tables.values() if len(self.get_foreign_keys(table)) != 2 or len(table.c) != 2]
    
    def get_related_many_to_many_tables(self, table_name):
        tables = []
        src_table = self.get_table(table_name)
        for table in self.get_many_to_many_tables():
            for column in table.columns:
                key = column.foreign_keys[0]
                if key.column.table is src_table:
                    tables.append(table)
                    break
        return tables