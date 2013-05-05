import os
import xdm
import re
import types
from xdm import common, helper
from xdm.classes import *
from xdm.classes import MediaType
from xdm.logger import *
from meta import *
from xdm.helper import replace_all


"""plugins should not set the status of an element !!! it will be done in the loops that call / use the plugins"""


class Plugin(object):
    """plugin base class. loads the config on init
    "self.c" is reserved!!! thats how you get the config
    "self.type" is reserved!!! its the class name
    "self._type" is reserved!!! its the plugin type name e.g. Downloader
    "self.instance" is reserved!!! its the instance name
    "self.name" is reserved!!! its the class name and instance name
    "self.single" is reserved!!! set this if you only want to allow one instance of your plugin !
    """
    _type = 'Plugin'
    single = False # if True the gui will not give the option for more configurations. but there is no logic to stop you do it anyways
    _config = {}
    config_meta = {}
    version = "0.1"
    useConfigsForElementsAs = 'Category'
    addMediaTypeOptions = True
    screenName = ''

    def __init__(self, instance='Default'):
        """returns a new instance of the Plugin with the config loaded get the configuration as self.c.<name_of_config>"""
        if not self.screenName:
            self.screenName = self.__class__.__name__
        self.name = "%s (%s)" % (self.screenName, instance)
        self.type = self.__class__.__name__
        self.instance = instance.replace('.', '_')
        log("Creating new plugin %s" % self.name)
        if self.addMediaTypeOptions:
            self._create_media_type_configs() #this adds the configs for media types
        self.c = ConfigWrapper()
        self.config_meta = ConfigMeta(self.config_meta)
        self._claimed_configs = []

        if not ('enabled' in self._config and self._config['enabled']):
            self._config['enabled'] = False
        self._config['plugin_order'] = 0

        enabled_obj = None
        for k, v in self._config.items():
            #print "looking for", self.__class__.__name__, 'Plugin', k, instance
            try:
                cur_c = Config.get(Config.section == self.__class__.__name__,
                                  Config.module == 'Plugin',
                                  Config.name == k,
                                  Config.instance == self.instance)
            except Config.DoesNotExist:
                cur_c = Config()
                cur_c.module = 'Plugin'
                cur_c.section = self.__class__.__name__
                cur_c.instance = self.instance
                cur_c.name = k
                cur_c.value = v
                if cur_c.name in self.config_meta and self.config_meta[cur_c.name]:
                    for field in ('type', 'element', 'mediaType'):
                        if field in self.config_meta[cur_c.name] is not None:
                            if self.config_meta[cur_c.name][field] is not None:
                                log('Setting %s for %s to %s' % (cur_c.name, field, self.config_meta[cur_c.name][field]))
                                setattr(cur_c, field, self.config_meta[cur_c.name][field])

                cur_c.save()
            self._claimed_configs.append(cur_c.get_id())
            if k == 'enabled':
                enabled_obj = cur_c
            self.c.addConfig(cur_c)
        self.c.finalSort(enabled_obj)

        methodList = [method for method in dir(self) if isinstance(getattr(self, method), (types.FunctionType, types.BuiltinFunctionType, types.MethodType, types.BuiltinMethodType, types.UnboundMethodType)) \
                      and not method.startswith('_')]
        for method_name in methodList:
            alternative = getattr(super(self.__class__, self), method_name)
            method = getattr(self, method_name)
            setattr(self, method_name, pluginMethodWrapper(self.name, method, alternative))

    def _get_enabled(self):
        return self.c.enabled

    def _set_enabled(self, value):
        self.c.enabled = value

    enabled = property(_get_enabled, _set_enabled) # shortcut to the enabled config option

    def deleteInstance(self):
        for c in self.c.configs:
            log("Deleting config %s from %s" % (c, self))
            c.delete_instance()

    def cleanUnusedConfigs(self):
        amount = 0
        for cur_c in Config.select().where(Config.section == self.__class__.__name__&
                                  Config.module == 'Plugin'&
                                  Config.instance == self.instance):
            if cur_c.get_id() in self._claimed_configs:
                continue
            else:
                log('Deleting unclaimed config %s(%s) in %s' % (cur_c, cur_c.get_id(), self))
                cur_c.delete_instance()
                amount += 1
        return amount

    def __str__(self):
        return self.name

    def _get_plugin_file_path(self):
        return os.path.abspath(__file__)

    def _create_media_type_configs(self):
        if self._type in (MediaTypeManager.__name__, System.__name__, Notifier.__name__):
            return
        mtms = common.PM.getMediaTypeManager()
        for mtm in mtms:
            #enable options for mediatype on this indexer
            name = helper.replace_some('%s_runfor' % mtm.name)
            self._config[name] = False
            self.config_meta[name] = {'human': 'Run for %s' % mtm.name, 'type': 'enabled', 'mediaType': mtm.mt}
            #log('Creating multi config fields on %s from %s' % (self.__class__, mtm.__class__))
            for type in [x.__name__ for x in mtm.elementConfigsFor]:
                for element in Element.select().where(Element.type == type):
                    prefix = self.useConfigsForElementsAs
                    sufix = element.getName()
                    h_name = '%s for %s (%s)' % (prefix, sufix, mtm.identifier)
                    c_name = helper.replace_some('%s %s %s' % (mtm.name, prefix.lower(), sufix))
                    self._config[c_name] = None
                    self.config_meta[c_name] = {'human': h_name, 'type': self.useConfigsForElementsAs.lower(), 'mediaType': mtm.mt, 'element': element}

            # add costum options
            if self.__class__.__bases__[0] in mtm.addConfig:
                for config in mtm.addConfig[self.__class__.__bases__[0]]:
                    h_name = '%s %s' % (config['prefix'], config['sufix'])
                    c_name = helper.replace_some('%s %s %s' % (mtm.name, config['prefix'], config['sufix']))
                    self._config[c_name] = config['default']
                    self.config_meta[c_name] = {'human': h_name, 'type': config['type'], 'mediaType': mtm.mt}

    def __getattribute__(self, name):
        useAs = object.__getattribute__(self, 'useConfigsForElementsAs')
        if name == '_get%s' % useAs:
            return object.__getattribute__(self, '_getUseConfigsForElementsAsWrapper')
        return object.__getattribute__(self, name)

    def _getUseConfigsForElementsAsWrapper(self, ele):
        for cur_c in self.c.configs:
            if cur_c.element is None:
                continue
            if cur_c.mediaType == ele.mediaType and\
            self.useConfigsForElementsAs.lower() == cur_c.type and\
            cur_c.element.isAncestorOf(ele): # is the config elemtn "above" the element in question
                return cur_c.value
        return None

    def runFor(self, mtm):
        return getattr(self.c, helper.replace_some('%s_runfor' % mtm.name))


class Downloader(Plugin):
    """Plugins of this class convert plain text to HTML"""
    _type = 'Downloader'
    name = "Does Noting"
    types = ['torrent', 'nzb'] # types the downloader can handle ... e.g. blackhole can handle both

    def addDownload(self, download):
        """Add nzb to downloader"""
        return False

    def getGameStaus(self, game):
        """return tuple of Status and a path (str)"""
        return (common.UNKNOWN, Download(), '')

    def _downloadName(self, download):
        """tmplate on how to call the nzb/torrent file. nzb_name for sab"""
        return "%s (XDM.%s-%s)" % (download.element.getName(), download.element.id, download.id)

    def _findIDs(self, s):
        """find the game id and gownload id in s is based on the _downloadName()"""
        m = re.search("\((XDM.(?P<gid>\d+)-(?P<did>\d+))\)", s)
        gid, did = 0, 0
        if m and m.group('gid'):
            gid = int(m.group('gid'))
        if m and m.group('did'):
            did = int(m.group('did'))
        return (gid, did)

    def _findGamezID(self, s):
        return self._findIDs(s)[0]

    def _findDownloadID(self, s):
        return self._findIDs(s)[1]

    def _getTypeExtension(self, downloadType):
        return common.getTypeExtension(downloadType)


class Notifier(Plugin):
    """Plugins of this class send out notification"""
    _type = 'Notifier'
    name = "prints"

    def __init__(self, *args, **kwargs):
        self._config['on_snatch'] = False
        self._config['on_complete'] = True # this is called after pp
        self._config['on_warning'] = False # this is called after pp
        self._config['on_error'] = False # this is called after pp
        super(Notifier, self).__init__(*args, **kwargs)

    def sendMessage(self, msg, element=None):
        return False


class Indexer(Plugin):
    """Plugins of this class create elemnts based on mediaType structures"""
    _type = 'Indexer'
    types = [common.TYPE_NZB, common.TYPE_TORRENT] # types this indexer will give back
    name = "Does Noting"

    def __init__(self, instance='Default'):
        # wrap function
        def searchForElement(*args, **kwargs):
            res = self._searchForElement(*args, **kwargs)
            for i, d in enumerate(res):
                # default stuff
                d.indexer = self.type
                d.indexer_instance = self.instance
                d.type = common.TYPE_NZB
                d.status = common.UNKNOWN
                res[i]
            return res
        self._searchForElement = self.searchForElement
        self.searchForElement = searchForElement
        Plugin.__init__(self, instance=instance)

    def _getCategory(self, e):
        for cur_c in self.c.configs:
            if cur_c.type == 'category' and e.mediaType == cur_c.mediaType and cur_c.element in e.ancestors:
                return cur_c.value

    def getLatestRss(self):
        """return list of Gamez"""
        return []

    def searchForElement(self, element):
        """return list of Download()"""
        return []

    def _getSearchNames(self, game):
        terms = []
        if game.additional_search_terms != None:
            terms = [x.strip() for x in game.additional_search_terms.split(',')]

        terms.append(re.sub('[ ]*\(\d{4}\)', '', replace_all(game.name)))
        log("Search terms for %s are %s" % (self.name, terms))
        return terms

    def commentOnDownload(self, download):
        return True


class Provider(Plugin):
    """get game information"""
    _type = 'Provider'
    _tag = 'unknown'

    class Progress(object):
        count = 0
        total = 0

        def reset(self):
            self.count = 0
            self.total = 0

        def addItem(self):
            self.count += 1

        def _getPercent(self):
            if self.total:
                return (self.count / float(self.total)) * 100
            else:
                return 0

        percent = property(_getPercent)

    def __init__(self, instance='Default'):
        self._config['favor'] = False
        Plugin.__init__(self, instance=instance)
        self.tag = self._tag
        if instance != 'Default':
            self.tag = instance
        self.progress = self.Progress()

    """creating more providers is definety more complicatedn then other things since
    the platform identification is kinda based on the the id of thegamesdb
    and the Game only has one field... but if one will take on this task please dont create just another field for the game
    instead create a new class that holds the information
    """

    def searchForElement(self, term='', id=0):
        """return always a list of games even if id is given, list might be empty or only contain 1 item"""
        return Element()

    def getElement(self, id):
        return False


class PostProcessor(Plugin):
    _type = 'PostProcessor'

    def ppPath(self, game, path):
        return False


class System(Plugin):
    """Is just a way to handle the config part and stuff"""
    _type = 'System'
    name = "Does Noting"

    def getBlacklistForPlatform(self, p):
        return []

    def getCheckPathForPlatform(self, p):
        return ''

    def getWhitelistForPlatform(self, p):
        return []


class MediaTypeManager(Plugin):
    _type = 'MediaTypeManager'
    name = "Does Noting"
    identifier = ''
    order = ()
    download = None
    addConfig = {}
    elementConfigsFor = ()
    defaultElements = {}

    def __init__(self, instance):
        self.single = True
        super(MediaTypeManager, self).__init__(instance)
        self.searcher = None
        self.config_meta['enable'] = {'on_enable': 'recachePlugins'}
        self.s = {'root': self.__class__.__name__}
        l = list(self.order)
        for i, e in enumerate(l):
            attributes = [attr for attr in dir(e) if isinstance(getattr(e, attr), (types.IntType, types.StringType)) and not attr.startswith('_')]
            if not i:
                self.s[e.__name__] = {'parent': 'root', 'child': l[i + 1], 'class': e, 'attr': attributes}
            else:
                if i == len(l) - 1:
                    self.s[e.__name__] = {'parent': l[i - 1], 'child': None, 'class': e, 'attr': attributes}
                    self.leaf = e.__name__
                else:
                    self.s[e.__name__] = {'parent': l[i - 1], 'child': l[i + 1], 'class': e, 'attr': attributes}
        try:
            self.mt = MediaType.get(MediaType.identifier == self.identifier)
        except MediaType.DoesNotExist:
            self.mt = MediaType()
            self.mt.name = self.__class__.__name__
            self.mt.identifier = self.identifier
            self.mt.save()

        try:
            self.root = Element.get(Element.type == self.__class__.__name__, Element.status != common.TEMP)
        except Element.DoesNotExist:
            self.root = Element()
            self.root.type = self.__class__.__name__
            self.root.parent = None
            self.root.mediaType = self.mt
            self.root.save()

        for elementType in self.defaultElements:
            for defaultElement in self.defaultElements[elementType]:
                for providerTag, defaultAttributes in defaultElement.items():
                    try:
                        e = Element.getWhereField(self.mt, elementType.__name__, defaultAttributes, providerTag)
                    except Element.DoesNotExist:
                        log('Creating default element for %s. type:%s, attrs:%s' % (self.identifier, elementType.__name__, defaultAttributes))
                        #continue
                        e = Element()
                        e.type = elementType.__name__
                        e.mediaType = self.mt
                        e.parent = self.root
                        e.status = common.UNKNOWN
                        for name, value in defaultAttributes.items():
                            e.setField(name, value, providerTag)
                        e.save()

    def getDownloadableElements(self, asList=True):
        out = Element.select().where(Element.mediaType == self.mt, Element.type == self.download.__name__, Element.status != common.TEMP)
        if asList:
            out = list(out)
        return out

    def isTypeLeaf(self, eType):
        return self.leaf == eType

    def getFn(self, eType, fnName):
        if eType in self.s and fnName in self.s[eType]['class'].__dict__:
            return self.s[eType]['class'].__dict__[fnName]
        else:
            return None

    def getOrderField(self, eType):
        if eType in self.s and '_orderBy' in self.s[eType]['class'].__dict__:
            return self.s[eType]['class'].__dict__['_orderBy']
        else:
            return ''

    def getAttrs(self, eType):
        return self.s[eType]['attr']

    def headInject(self):
        return ''

    def paint(self, root=None):
        if root is None:
            log('init paint on default root %s %s' % (self.root, self.root.id))
            return self.root.paint()
        else:
            log('init paint on given root %s %s' % (root, root.id))
            return root.paint(search=True)

    def search(self, search_query):
        log.info('Init search on %s for %s' % (self, search_query))
        self.searcher = None
        #xdm.DATABASE.set_autocommit(False)
        out = None
        for provider in common.PM.P:
            if not provider.runFor(self) or self.identifier not in provider.types:
                continue
            self.searcher = provider
            out = provider.searchForElement(term=search_query)
        #xdm.DATABASE.commit()
        #xdm.DATABASE.set_autocommit(True)
        self.searcher = None
        return out

    #TODO: THIS is not save for any structur !!!!
    def makeReal(self, element):
        """log.info('Making element %s (%s) real' % (element, element.id))
        #element should be of type self.download
        if element.type != self.download.__name__:
            log.error('%s is of wrong type for permanent saving. the id send from the add butto nbelongs to the wrong type of eement! tell that the plugin writer')

        for curClass in reversed(self.order):
            pass
 
        ancestors = element.ancestors
        saveOnElement = self.save.__name__
        for i, ancestor in enumerate(ancestors):
            print 'ancestor %s (%s) vs %s' % (ancestor, ancestor.id, self.save.__name__)

            if ancestor.type == saveOnElement:
                searchAttr = {}
                for attr in self.getAttrs(ancestor.type):
                    searchAttr[attr] = ancestor.getField(attr)
                try:
                    saveElement = Element.getWhereField(self.mt, ancestor.type, searchAttr, '', self.root)
                except Element.DoesNotExist:
                    log('Moving %s as a parent for the %s element we want to save' % (ancestor.type, element.type))
                    ancestor.parent = self.root
                    saveElement = ancestor
                    saveElement.status = common.UNKNOWN
                    saveElement.save()
                else: # we have the artist / platform in the db so we have to rehock one below the current ancestor
                    log('We have this %s in the db already. Searching for new/lower type' % ancestor.type)
                    nextOne = False
                    saveOnElement = ''
                    for curClass in self.order:
                        if nextOne == True:
                            saveOnElement = curClass.__name__
                            break
                        if curClass.__name__ == ancestor.type:
                            nextOne = True
                    if saveOnElement:
                        log('Found %s as the next lower type' % saveOnElement)
                        continue
                    else:
                        log.error('I am at i point where i dont know what to do :(')
                return True"""
                
        log.warning('Default makereal/save method called but the media type should have implemented this')
        return False
        
                
    def getSearches(self):
        return Element.select().where(Element.status == common.TEMP, Element.type == self.__class__.__name__)

    def getFakeRoot(self, term=''):
        root = Element()
        root.type = self.__class__.__name__
        root.parent = None
        root.mediaType = self.mt
        root.setField('term', term)
        root.saveTemp()
        return root

__all__ = ['System', 'PostProcessor', 'Provider', 'Indexer', 'Notifier', 'Downloader', 'MediaTypeManager', 'Element']