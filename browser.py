# Copyright (C) 2006, Red Hat, Inc.
# Copyright (C) 2007, One Laptop Per Child
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import logging
from gettext import gettext as _

import gobject
import gtk
import tempfile
import os
import time
import xpcom
from xpcom.nsError import *
from xpcom import components
from xpcom.components import interfaces
from hulahop.webview import WebView

from sugar.datastore import datastore
from sugar import profile
from sugar import env
from sugar.activity import activityfactory
from sugar.activity import activity

import sessionstore

class GetSourceListener(gobject.GObject):
    _com_interfaces_ = interfaces.nsIWebProgressListener
    
    __gsignals__ = {    
        'finished':     (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                             ([]))
    }
    
    def __init__(self, persist):
        gobject.GObject.__init__(self)
        self._persist = persist

    def onStateChange(self, progress, request, flags, status):
        finished = interfaces.nsIWebBrowserPersist.PERSIST_STATE_FINISHED
        if self._persist.currentState == finished:
            self.emit('finished')

    def onProgressChange(self, progress, request, curSelfProgress,
                         maxSelfProgress, curTotalProgress, maxTotalProgress):
        pass

    def onLocationChange(self, progress, request, location):
        pass

    def onStatusChange(self, progress, request, status, message):
        pass

    def onSecurityChange(progress, request, state):
        pass
    
class Browser(WebView):

    AGENT_SHEET = os.path.join(activity.get_bundle_path(), 'agent-stylesheet.css')
    USER_SHEET = os.path.join(env.get_profile_path(), 'gecko', 'user-stylesheet.css')

    def __init__(self):
        WebView.__init__(self)

        io_service_class = components.classes["@mozilla.org/network/io-service;1"]
        io_service = io_service_class.getService(interfaces.nsIIOService)

        cls = components.classes['@mozilla.org/content/style-sheet-service;1']
        style_sheet_service = cls.getService(interfaces.nsIStyleSheetService)

        if os.path.exists(Browser.AGENT_SHEET):
            agent_sheet_uri = io_service.newURI('file:///' + Browser.AGENT_SHEET,
                    None, None)
            style_sheet_service.loadAndRegisterSheet(agent_sheet_uri,
                    interfaces.nsIStyleSheetService.AGENT_SHEET)

        if os.path.exists(Browser.USER_SHEET):
            user_sheet_uri = io_service.newURI('file:///' + Browser.USER_SHEET,
                    None, None)
            style_sheet_service.loadAndRegisterSheet(user_sheet_uri,
                    interfaces.nsIStyleSheetService.USER_SHEET)

    def get_session(self):
        return sessionstore.get_session(self)

    def set_session(self, data):
        return sessionstore.set_session(self, data)

    def get_source(self):
        cls = components.classes['@mozilla.org/embedding/browser/nsWebBrowserPersist;1']
        persist = cls.createInstance(interfaces.nsIWebBrowserPersist)
        # get the source from the cache
        persist.persistFlags = interfaces.nsIWebBrowserPersist.PERSIST_FLAGS_FROM_CACHE

        progresslistener = GetSourceListener(persist)
        persist.progressListener = xpcom.server.WrapObject(
            progresslistener, interfaces.nsIWebProgressListener)
        progresslistener.connect('finished', self._have_source_cb)
            
        file_path = os.path.join(tempfile.gettempdir(), '%i' % time.time())        
        cls = components.classes["@mozilla.org/file/local;1"]
        local_file = cls.createInstance(interfaces.nsILocalFile)
        local_file.initWithPath(file_path)

        uri = self.web_navigation.currentURI            
        persist.saveURI(uri, self.doc_shell, None, None, None, local_file)
        self._create_journal_object(file_path)
        self._jobject.file_path = file_path
        
    def _have_source_cb(self, progress_listener):
        logging.debug("Finished getting source - writing to datastore")                    
        datastore.write(self._jobject,
                        reply_handler=self._internal_save_cb,
                        error_handler=self._internal_save_error_cb)

    def _create_journal_object(self, file_path):        
        self._jobject = datastore.create()        
        title = _('Source') + ': ' + self.props.title 
        self._jobject.metadata['title'] = title
        self._jobject.metadata['keep'] = '0'
        self._jobject.metadata['buddies'] = ''
        self._jobject.metadata['preview'] = ''
        self._jobject.metadata['icon-color'] = profile.get_color().to_string()
        self._jobject.metadata['mime_type'] = 'text/plain'
        self._jobject.metadata['source'] = '1'
        self._jobject.file_path = ''
        datastore.write(self._jobject)

    def _internal_save_cb(self):
        logging.debug("Saved source object to datastore.")
        id = self._jobject.object_id
        service_name = 'org.laptop.AbiWordActivity'
        self._cleanup_jobject()        
        activityfactory.create_with_object_id(service_name, id)
            
    def _internal_save_error_cb(self, err):
        logging.debug("Error saving source object to datastore: %s" % err)
        self._cleanup_jobject()

    def _cleanup_jobject(self):
        if self._jobject:
            if os.path.isfile(self._jobject.file_path):
                logging.debug('_cleanup_jobject: removing %r' % self._jobject.file_path)
                os.remove(self._jobject.file_path)            
            self._jobject.destroy()
            self._jobject = None
