
import os
import gedit
import gtk
import gobject
import fcntl

ui_str = """<ui>
  <menubar name="MenuBar">
    <menu name="SearchMenu" action="Search">
      <placeholder name="SearchOps_2">
        <menuitem name="FileSearch" action="FileSearch"/>
      </placeholder>
    </menu>
  </menubar>
</ui>
"""


class SearchProcess:
    def __init__ (self, queryText, directory, resultHandler):
        self.parser = GrepParser(resultHandler)

        cmd = "find '%s' -print 2> /dev/null | xargs grep -H -I -n -s -Z -e '%s'" % (directory, queryText)
        #cmd = "sleep 2; echo -n 'abc'; sleep 3; echo 'xyz'; sleep 3"
        #cmd = "sleep 2"
        #cmd = "echo 'abc'"
        print "executing command: %s" % cmd
        self.pipe = os.popen(cmd, 'r')

        # make pipe non-blocking:
        fl = fcntl.fcntl(self.pipe, fcntl.F_GETFL)
        fcntl.fcntl(self.pipe, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        print "(add watch)"
        gobject.io_add_watch(self.pipe, gobject.IO_IN | gobject.IO_ERR | gobject.IO_HUP,
            self.onPipeReadable)

    def onPipeReadable (self, fd, cond):
        print "condition: %s" % cond
        if (cond & gobject.IO_IN):
            readText = self.pipe.read(1000)
            print "(read %d bytes)" % len(readText)
            self.parser.parseFragment(readText)
            return True
        else:
            self.parser.finish()
            print "(closing pipe)"
            result = self.pipe.close()
            if result == None:
                print "(search finished successfully)"
            else:
                print "(search finished with exit code %d; exited: %s, exit status: %d)" % (result,
                    str(os.WIFEXITED(result)), os.WEXITSTATUS(result))
            return False


class GrepParser:
    def __init__ (self, resultHandler):
        self.buf = ""
        self.resultHandler = resultHandler

    def parseFragment (self, text):
        self.buf = self.buf + text

        while '\n' in self.buf:
            pos = self.buf.index('\n')
            line = self.buf[:pos]
            self.buf = self.buf[pos + 1:]
            self.parseLine(line)

    def parseLine (self, line):
        filename = None
        lineno = None
        linetext = ""
        if '\0' in line:
            [filename, end] = line.split('\0', 1)
            if ':' in end:
                [lineno, linetext] = end.split(':', 1)
                lineno = int(lineno)

        if lineno == None:
            print "(ignoring invalid line)"
        else:
            # Assume that grep output is in UTF8 encoding, and convert it to
            # a Unicode string. Also, sanitize non-UTF8 characters.
            # TODO: what's the actual encoding of grep's output?
            linetext = unicode(linetext, 'utf8', 'replace')
            print "file: '%s'; line: %d; text: '%s'" % (filename, lineno, linetext)
            self.resultHandler.handleResult(filename, lineno, linetext)

    def finish (self):
        self.parseFragment("")
        if self.buf != "":
            self.parseLine(self.buf)

class ResultHandler:
    def __init__ (self, resultGUI, resultPanel):
        self.resultGUI = resultGUI
        self.resultPanel = resultPanel
        self.files = {}

    def handleResult (self, file, lineno, linetext):
        if not(self.files.has_key(file)):
            it = self.resultGUI._add_result_file(self.resultPanel, file)
            self.files[file] = it
        else:
            it = self.files[file]
        self.resultGUI._add_result_line(self.resultPanel, it, lineno, linetext)


class FileSearchWindowHelper:
    def __init__(self, plugin, window):
        print "Plugin created for", window
        self._window = window
        self._plugin = plugin
        self._dialog = None

        self._insert_menu()

    def deactivate(self):
        print "Plugin stopped for", self._window
        self._window = None
        self._plugin = None

    def update_ui(self):
        # Called whenever the window has been updated (active tab
        # changed, etc.)
        print "Plugin update for", self._window

    def _insert_menu(self):
        # Get the GtkUIManager
        manager = self._window.get_ui_manager()

        # Create a new action group
        self._action_group = gtk.ActionGroup("FileSearchPluginActions")
        self._action_group.add_actions([("FileSearch", "gtk-find", _("Find in files ..."),
                                         "", _("Search in multiple files"),
                                         self.on_search_files_activate)])

        # Insert the action group
        manager.insert_action_group(self._action_group, -1)

        # Merge the UI
        self._ui_id = manager.add_ui_from_string(ui_str)

    def on_cboSearchTextEntry_changed (self, textEntry):
        """
        Is called when the search text entry is modified;
        disables the Search button whenever no search text is entered.
        """
        if textEntry.get_text() == "":
            self.tree.get_widget('btnSearch').set_sensitive(False)
        else:
            self.tree.get_widget('btnSearch').set_sensitive(True)

    def on_search_files_activate(self, action):
        print "(find in files)"

        gladeFile = os.path.join(os.path.dirname(__file__), "gedit-file-search.glade")
        self.tree = gtk.glade.XML(gladeFile)
        self.tree.signal_autoconnect(self)

        self._dialog = self.tree.get_widget('searchDialog')
        self._dialog.set_transient_for(self._window)

        # set initial values for search dialog widgets
        searchDir = os.getcwdu()
        if self._window.get_active_tab():
            currFileDir = self._window.get_active_tab().get_document().get_uri()
            if currFileDir != None and currFileDir.startswith("file:///"):
                searchDir = os.path.dirname(currFileDir[7:])
        self.tree.get_widget('cboSearchDirectoryEntry').set_text(searchDir)

        result = self._dialog.run()
        print "result: %s" % result

        if result != 1:
            print "(cancelled)"
            self._dialog.destroy()
            return

        print "(starting search)"
        searchText = self.tree.get_widget('cboSearchTextEntry').get_text()
        searchDir = self.tree.get_widget('cboSearchDirectoryEntry').get_text()
        self._dialog.destroy()

        print "searching for '%s' in '%s'" % (searchText, searchDir)
        if searchText == "":
            print "internal error: search text is empty!"
            return
        if not(os.path.exists(searchDir)):
            print "error: directory '%s' doesn't exist!" % searchDir
            return
        container = self._add_result_panel()
        rh = ResultHandler(self, container)
        sp = SearchProcess(searchText, searchDir, rh)

    def _add_result_panel (self):
        print "(add result panel)"

        gladeFile = os.path.join(os.path.dirname(__file__), "gedit-file-search.glade")
        self.tree = gtk.glade.XML(gladeFile, 'hbxFileSearchResult')
        resultContainer = self.tree.get_widget('hbxFileSearchResult')

        panel = self._window.get_bottom_panel()
        panel.add_item(resultContainer, "File Search", "gtk-find")
        panel.activate_item(resultContainer)


        treestore = gtk.TreeStore(str)
        tv = self.tree.get_widget('tvFileSearchResult')
        tv.set_model(treestore)

        tc = gtk.TreeViewColumn("File", gtk.CellRendererText(), markup=0)
        tv.append_column(tc)

        resultContainer.resultStore = treestore
        resultContainer.treeView = tv
        return resultContainer

    def _add_result_file (self, resultPanel, filename):
        line = "<span foreground=\"#000000\" size=\"smaller\">%s</span>" % filename
        it = resultPanel.resultStore.append(None, [line])
        resultPanel.treeView.expand_all()
        return it

    def _add_result_line (self, resultPanel, it, lineno, linetext):
        linetext = escapeMarkup(linetext)
        line = "<b>%d:</b> <span foreground=\"blue\">%s</span>" % (lineno, linetext)
        resultPanel.resultStore.append(it, [line])
        resultPanel.treeView.expand_all()


def escapeMarkup (origText):
    text = origText
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text

class FileSearchPlugin(gedit.Plugin):
    def __init__(self):
        gedit.Plugin.__init__(self)
        self._instances = {}

    def activate(self, window):
        self._instances[window] = FileSearchWindowHelper(self, window)

    def deactivate(self, window):
        self._instances[window].deactivate()
        del self._instances[window]

    def update_ui(self, window):
        self._instances[window].update_ui()
