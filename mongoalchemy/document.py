# Copyright (c) 2009, Jeff Jenkins
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * the names of contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY JEFF JENKINS ''AS IS'' AND ANY
# EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL JEFF JENKINS BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import pymongo

from mongoalchemy.util import classproperty
from mongoalchemy.query import QueryFieldSet
from mongoalchemy.fields import ObjectIdField, Field, BadValueException

class DocumentMeta(type):
    def __new__(mcs, classname, bases, class_dict):
        new_class = type.__new__(mcs, classname, bases, class_dict)
        
        for name, value in class_dict.iteritems():
            if not isinstance(value, Field):
                continue
            value.set_name(name)
            value.set_parent(new_class)

        return new_class

class DocumentException(Exception):
    ''' Base for all document-related exceptions'''
    pass

class MissingValueException(DocumentException):
    ''' Raised when a required field isn't set '''
    pass

class ExtraValueException(DocumentException):
    ''' Raised when a value is passed in with no corresponding field '''
    pass

class FieldNotRetrieved(DocumentException):
    '''If a partial document is loaded from the database and a field which 
        wasn't retrieved is accessed this exception is raised'''
    pass

class Document(object):
    object_mapping = {}
    
    __metaclass__ = DocumentMeta
    
    _id = ObjectIdField(required=False)
    
    def __init__(self, **kwargs):
        cls = self.__class__
        
        fields = self.get_fields()
        for name, field in fields.iteritems():
            if name in kwargs:
                setattr(self, name, kwargs[name])
                continue
            
            if field.auto:
                continue
            
            if field.required:
                raise MissingValueException(name)
            
            if hasattr(field, 'default'):
                setattr(self, name, field.default)
        
        for k in kwargs:
            if k not in fields:
                raise ExtraValueException(k)
    
    def __setattr__(self, name, value):
        cls = self.__class__
        if (not hasattr(cls, name) or
            not isinstance(getattr(cls, name), Field)):
                raise AttributeError('%s object has no attribute %s' % (self.class_name(), name))
        field = getattr(cls, name)
        
        field.validate_wrap(value)
        object.__setattr__(self, name, value)
    
    def __getattribute__(self, name):
        value = object.__getattribute__(self, name)
        if isinstance(value, Field):
            raise AttributeError(name)
        return value
    
    @classproperty
    def f(cls):
        return QueryFieldSet(cls, cls.get_fields())
    
    @classmethod
    def get_fields(cls):
        fields = {}
        for name in dir(cls):
            if name == 'f':
                continue
            field = getattr(cls, name)
            if not isinstance(field, Field):
                continue
            fields[name] = field
        return fields
    
    @classmethod
    def class_name(cls):
        return cls.__name__
    
    @classmethod
    def get_collection_name(cls):
        if not hasattr(cls, '_collection_name'):
            return cls.__name__
        return cls._collection_name
    
    @classmethod
    def get_indexes(cls):
        ret = []
        for name in dir(cls):
            field = getattr(cls, name)
            if isinstance(field, Index):
                ret.append(field)
        return ret
    
    def commit(self, db):
        collection = db[self.get_collection_name()]
        for index in self.get_indexes():
            index.ensure(collection)
        id = collection.save(self.wrap())
        self._id = id
    
    def wrap(self):
        '''Wrap a MongoObject into a format which can be inserted into
            a mongo database'''
        res = {}
        cls = self.__class__
        for name in dir(cls):
            field = getattr(cls, name)
            try:
                value = getattr(self, name)
            except AttributeError:
                continue
            if isinstance(field, Field):
                res[name] = field.wrap(value)
        return res
    
    @classmethod
    def unwrap(cls, obj):
        '''Unwrap an object returned from the mongo database.'''
        
        params = {}
        for k, v in obj.iteritems():
            field = getattr(cls, k)
            params[str(k)] = field.unwrap(v)
        
        i = cls(**params)
        return i
    

class DocumentField(Field):
    
    def __init__(self, document_class, **kwargs):
        super(DocumentField, self).__init__(**kwargs)
        self.type = document_class

    def validate_wrap(self, value):
        if not self.is_valid_wrap(value):
            name = self.__class__.__name__
            raise BadValueException('Bad value for field of type "%s(%s)": %s' %
                                    (name, self.type.class_name(), repr(value)))
    def validate_unwrap(self, value):
        if not self.is_valid_unwrap(value):
            name = self.__class__.__name__
            raise BadValueException('Bad value for field of type "%s(%s)": %s' %
                                    (name, self.type.class_name(), repr(value)))

    
    def wrap(self, value):
        self.validate_wrap(value)
        return self.type.wrap(value)
    
    def unwrap(self, value):
        self.validate_unwrap(value)
        return self.type.unwrap(value)
    
    def is_valid_wrap(self, value):
        # we've validated everything we set on the object, so this should 
        # always return True if it's the right kind of object
        return value.__class__ == self.type
    
    def is_valid_unwrap(self, value):
        # this is super-wasteful
        try:
            self.type.unwrap(value)
        except:
            return False
        return True

class BadIndexException(Exception):
    pass

class Index(object):
    ASCENDING = pymongo.ASCENDING
    DESCENDING = pymongo.DESCENDING
    
    def __init__(self):
        self.components = []
        self.__unique = False
        self.__drop_dups = False
    
    def ascending(self, name):
        self.components.append((name, Index.ASCENDING))
        return self

    def descending(self, name):
        self.components.append((name, Index.DESCENDING))
        return self
    
    def unique(self, drop_dups=False):
        self.__unique = True
        self.__drop_dups = drop_dups
        return self
    
    def ensure(self, collection):
        collection.ensure_index(self.components, unique=self.__unique, 
            drop_dups=self.__drop_dups)
        return self
        