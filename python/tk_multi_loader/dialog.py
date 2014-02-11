# Copyright (c) 2013 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.

import tank
from tank import TankError
import os
import sys
import threading

from tank.platform.qt import QtCore, QtGui

from .model_entity import SgEntityModel
from .model_latestpublish import SgLatestPublishModel
from .model_publishtype import SgPublishTypeModel
from .model_status import SgStatusModel
from .action_manager import ActionManager
from .proxymodel_publish import SgPublishProxyModel 
from .delegate_publish_thumb import SgPublishDelegate
from .model_publishhistory import SgPublishHistoryModel
from .delegate_publish_history import SgPublishHistoryDelegate

from .ui.dialog import Ui_Dialog

# import the shotgun_model module from the shotgun utils framework
shotgun_model = tank.platform.import_framework("tk-framework-shotgunutils", "shotgun_model") 
ShotgunModel = shotgun_model.ShotgunModel 
       

class AppDialog(QtGui.QWidget):
    """
    Main dialog window for the App
    """

    def __init__(self):
        """
        Constructor
        """
        
        QtGui.QWidget.__init__(self)
        
        # set up the UI
        self.ui = Ui_Dialog()
        self.ui.setupUi(self)
        
        #################################################
        # maintain a list where we keep a reference to
        # all the dynamic UI we create. This is to make
        # the GC happy.
        self._dynamic_widgets = []
        
        # flag to indicate that the current selection 
        # operation is part of a programatic selection
        # and not a generated by a user clicking
        self._programmatic_selection_mode = False 
                
        #################################################
        # hook a helper model tracking status codes so we
        # can use those in the UI
        self._status_model = SgStatusModel(self.ui.publish_type_list)
        
        self._action_manager = ActionManager()
        
        #################################################
        # details pane
        self.ui.details.setVisible(False)
        self.ui.info.toggled.connect(self._on_info_toggled)
                
        self._publish_history_model = SgPublishHistoryModel(self.ui.history_view)
        
        self._publish_history_proxy = QtGui.QSortFilterProxyModel(self)
        self._publish_history_proxy.setSourceModel(self._publish_history_model)
        
        # now use the proxy model to sort the data to ensure
        # higher version numbers appear earlier in the list
        # the history model is set up so that the default display
        # role contains the version number field in shotgun.
        # This field is what the proxy model sorts by default
        # We set the dynamic filter to true, meaning QT will keep
        # continously sorting. And then tell it to use column 0
        # (we only have one column in our models) and descending order.
        self._publish_history_proxy.setDynamicSortFilter(True)
        self._publish_history_proxy.sort(0, QtCore.Qt.DescendingOrder)
        
        self.ui.history_view.setModel(self._publish_history_proxy)
        self._history_delegate = SgPublishHistoryDelegate(self.ui.history_view, self._status_model, self._action_manager)
        self.ui.history_view.setItemDelegate(self._history_delegate)
        
        self._no_selection_pixmap = QtGui.QPixmap(":/res/no_item_selected_512x400.png")
        
        #################################################
        # load and initialize cached publish type model
        self._publish_type_model = SgPublishTypeModel(self.ui.publish_type_list)        
        self.ui.publish_type_list.setModel(self._publish_type_model)

        #################################################
        # setup publish model
        self._publish_model = SgLatestPublishModel(self.ui.publish_view, self._publish_type_model)
        
        # set up a proxy model to cull results based on type selection
        self._publish_proxy_model = SgPublishProxyModel(self)
        self._publish_proxy_model.setSourceModel(self._publish_model)
                
        # tell our publish view to use a custom delegate to produce widgetry
        self._publish_delegate = SgPublishDelegate(self.ui.publish_view, self._status_model, self._action_manager) 
        self.ui.publish_view.setItemDelegate(self._publish_delegate)
                
        # hook up view -> proxy model -> model
        self.ui.publish_view.setModel(self._publish_proxy_model)
        
        # whenever the type list is checked, update the publish filters
        self._publish_type_model.itemChanged.connect(self._apply_type_filters_on_publishes)        
        
        # if an item in the table is double clicked ensure details are shown
        self.ui.publish_view.doubleClicked.connect(self._on_publish_double_clicked)
                
        # event handler for when the selection in the publish view is changing
        # note! Because of some GC issues (maya 2012 Pyside), need to first establish
        # a direct reference to the selection model before we can set up any signal/slots
        # against it
        publish_view_selection_model = self.ui.publish_view.selectionModel()
        self._dynamic_widgets.append(publish_view_selection_model)
        publish_view_selection_model.selectionChanged.connect(self._on_publish_selection)
        
        self.ui.show_sub_items.toggled.connect(self._on_show_subitems_toggled)
        
        #################################################
        # thumb scaling
        self.ui.thumb_scale.valueChanged.connect(self._on_thumb_size_slider_change)
        self.ui.thumb_scale.setValue(180)
        
        #################################################
        # setup history
        
        self._history = []
        self._history_index = 0
        # state flag used by history tracker to indicate that the 
        # current navigation operation is happen as a part of a 
        # back/forward operation and not part of a user's click
        self._history_navigation_mode = False
        self.ui.navigation_home.clicked.connect(self._on_home_clicked)
        self.ui.navigation_prev.clicked.connect(self._on_back_clicked)
        self.ui.navigation_next.clicked.connect(self._on_forward_clicked)
        
        #################################################
        # set up preset tabs and load and init tree views
        self._entity_presets = {} 
        self._current_entity_preset = None
        self._load_entity_presets()
        
        # lastly, set the splitter ratio roughly. QT will do fine adjustments.
        self.ui.left_side_splitter.setSizes( [400, 200] )
        
        
        
    def closeEvent(self, event):
        """
        Executed when the main dialog is closed.
        All worker threads and other things which need a proper shutdown
        need to be called here.
        """
        self._publish_model.destroy()
        self._publish_history_model.destroy()
        self._publish_type_model.destroy()
        self._status_model.destroy()    
        for p in self._entity_presets:
            self._entity_presets[p].model.destroy()
        
        # okay to close!
        event.accept()
                
    ########################################################################################
    # info bar related
    
    def _on_info_toggled(self, checked):
        """
        Executed when someone clicks the show/hide details button
        """
        if checked:
            self.ui.details.setVisible(True)
            
            # if there is something selected, make sure the detail
            # section is focused on this 
            selection_model = self.ui.publish_view.selectionModel()     
            
            if selection_model.hasSelection():
            
                current_proxy_model_idx = selection_model.selection().indexes()[0]
                
                # the incoming model index is an index into our proxy model
                # before continuing, translate it to an index into the 
                # underlying model
                proxy_model = current_proxy_model_idx.model()
                source_index = proxy_model.mapToSource(current_proxy_model_idx)
                
                # now we have arrived at our model derived from StandardItemModel
                # so let's retrieve the standarditem object associated with the index
                item = source_index.model().itemFromIndex(source_index)
            
                self._setup_details_panel(item)
            
            else:
                self._setup_details_panel(None)
                
        else:
            self.ui.details.setVisible(False)
        
        
        
    def _setup_details_panel(self, item):
        """
        Sets up the details panel with info for a given item.        
        """
        if not self.ui.details.isVisible():
            return
        
        if item is None:        
            # display a 'please select something' message in the thumb area
            self._publish_history_model.clear()
            self.ui.details_header.setText("")
            self.ui.details_image.setPixmap(self._no_selection_pixmap)
            
        else:            
            # render out details
            thumb_pixmap = item.icon().pixmap(512)
            self.ui.details_image.setPixmap(thumb_pixmap)
            
            sg_data = item.data(SgEntityModel.SG_DATA_ROLE)
            
            if sg_data is None:
                # an item which doesn't have any sg data directly associated
                # typically an item higher up the tree
                # just use the default text
                self.ui.details_header.setText("Folder Name: %s" % item.text())
            
            elif item.data(SgLatestPublishModel.IS_FOLDER_ROLE):
                # folder
                
                status_code = sg_data.get("sg_status_list")
                if status_code is None:
                    status_name = "No Status"
                else:
                    status_name = self._status_model.get_long_name(status_code)

                status_color = self._status_model.get_color_str(status_code)
                if status_color:
                    status_name = "%s&nbsp;<span style='color: rgb(%s)'>&#9608;</span>" % (status_name, status_color)
                
                if sg_data.get("description"):
                    desc_str = sg_data.get("description")
                else:
                    desc_str = "No description entered."

                msg = ""
                msg += "<b>%s %s</b><br>" % (sg_data.get("type"), sg_data.get("code"))
                msg += "<b>Status: </b>%s<br>" % status_name
                msg += "<b>Description:</b> %s<br>" % desc_str
                self.ui.details_header.setText(msg)
                
                # blank out the version history
                self._publish_history_model.clear()
                
            
            else:
                # this is a publish!
                
                sg_item = item.data(SgEntityModel.SG_DATA_ROLE)                
                
                if sg_item.get("entity") is None:
                    entity_str = "Unlinked Publish"
                else:
                    entity_str = "%s %s" % (sg_item.get("entity").get("type"),
                                            sg_item.get("entity").get("name"))
                
                if sg_item.get("name") is None:
                    name_str = "No Name"
                else:
                    name_str = sg_item.get("name")
        
                type_str = item.data(SgLatestPublishModel.PUBLISH_TYPE_NAME_ROLE)
                                                
                msg = ""
                msg += "<b>Name:</b> %s<br>" % name_str
                msg += "<b>Type:</b> %s<br>" % type_str
                msg += "<b>Associated with:</b> %s<br>" % entity_str

                # sort out the task label
                if sg_item.get("task"):

                    if sg_item.get("task.Task.content") is None:
                        task_name_str = "Unnamed"
                    else:
                        task_name_str = sg_item.get("task.Task.content")
                    
                    if sg_item.get("task.Task.sg_status_list") is None:
                        task_status_str = "No Status"
                    else:
                        task_status_code = sg_item.get("task.Task.sg_status_list")
                        task_status_str = self._status_model.get_long_name(task_status_code)
                    
                    msg += "<b>Associated Task:</b> %s (%s)<br>" % (task_name_str, task_status_str)    
                    

                self.ui.details_header.setText(msg)
                                
                # tell details pane to load stuff
                sg_data = item.data(ShotgunModel.SG_DATA_ROLE)
                self._publish_history_model.load_data(sg_data)
            
            self.ui.details_header.updateGeometry()
            
            
            
            
            
                
        
    ########################################################################################
    # history related
    
    def _compute_history_button_visibility(self):
        """
        compute history button enabled/disabled state based on contents of history stack.
        """
        self.ui.navigation_next.setEnabled(True)
        self.ui.navigation_prev.setEnabled(True)
        if self._history_index == len(self._history):
            self.ui.navigation_next.setEnabled(False) 
        if self._history_index == 1:
            self.ui.navigation_prev.setEnabled(False)         
    
    def _add_history_record(self, preset_caption, std_item):
        """
        Adds a record to the history stack
        """
        # self._history_index is a one based index that points at the currently displayed
        # item. If it is not pointing at the last element, it means a user has stepped back
        # in that case, discard the history after the current item and add this new record
        # after the current item

        if not self._history_navigation_mode: # do not add to history when browsing the history :)
            # chop off history at the point we are currently
            self._history = self._history[:self._history_index]         
            # append our current item to the chopped history
            self._history.append({"preset": preset_caption, "item": std_item})
            self._history_index += 1

        # now compute buttons
        self._compute_history_button_visibility()
        
    def _history_navigate_to_item(self, preset, item):
        """
        Focus in on an item in the tree view.
        """
        # tell rest of event handlers etc that this navigation
        # is part of a history click. This will ensure that no
        # *new* entries are added to the history log when we 
        # are clicking back/next...
        self._history_navigation_mode = True
        try:            
            self._select_item_in_entity_tree(preset, item)            
        finally:
            self._history_navigation_mode = False
        
    def _on_home_clicked(self):
        """
        User clicks the home button
        """
        # first, try to find the "home" item by looking at the current app context.
        found_preset = None
        found_item = None
        
        # get entity portion of context
        ctx = tank.platform.current_bundle().context
        if ctx.entity:

            # now step through the profiles and find a matching entity
            for p in self._entity_presets:
                if self._entity_presets[p].entity_type == ctx.entity["type"]:
                    # found an at least partially matching entity profile.
                    found_preset = p
                                        
                    # now see if our context object also exists in the tree of this profile
                    model = self._entity_presets[p].model
                    item = model.item_from_entity(ctx.entity["type"], ctx.entity["id"]) 
                    
                    if item is not None:
                        # find an absolute match! Break the search.
                        found_item = item
                        break
                
        if found_preset is None:
            # no suitable item found. Use the first tab
            found_preset = self.ui.entity_preset_tabs.tabText(0)
            
        # set the current preset to the one we just found
        print "on home clicked" 
        self._current_entity_preset = found_preset
        
        # select it in the left hand side tree view
        self._select_item_in_entity_tree(found_preset, found_item)
                
    def _on_back_clicked(self):
        """
        User clicks the back button
        """
        self._history_index += -1
        # get the data for this guy (note: index are one based)
        d = self._history[ self._history_index - 1]
        self._history_navigate_to_item(d["preset"], d["item"])
        self._compute_history_button_visibility()
        
    def _on_forward_clicked(self):
        """
        User clicks the forward button
        """
        self._history_index += 1
        # get the data for this guy (note: index are one based)
        d = self._history[ self._history_index - 1]
        self._history_navigate_to_item(d["preset"], d["item"])
        self._compute_history_button_visibility()
        
    ########################################################################################
    # filter view
        
    def _apply_type_filters_on_publishes(self):
        """
        Executed when the type listing changes
        """         
        # go through and figure out which checkboxes are clicked and then
        # update the publish proxy model so that only items of that type 
        # is displayed
        sg_type_ids = self._publish_type_model.get_selected_types()
        show_folders = self._publish_type_model.get_show_folders()
        self._publish_proxy_model.set_filter_by_type_ids(sg_type_ids, show_folders)

    ########################################################################################
    # publish view
        
    def _on_show_subitems_toggled(self):
        """
        Triggered when the show sub items checkbox is clicked
        """
        selection_model = self._entity_presets[self._current_entity_preset].view.selectionModel()        
        item = None
        if selection_model.hasSelection():            
            # get the current index
            current = selection_model.selection().indexes()[0]
            # get selected item
            item = current.model().itemFromIndex(current)        
        # tell publish UI to update itself
        self._load_publishes_for_entity_item(item)
         
        
    def _on_thumb_size_slider_change(self, value):
        """
        When scale slider is manipulated
        """
        self.ui.publish_view.setIconSize(QtCore.QSize(value, value))
        
    def _on_publish_selection(self, selected, deselected):
        """
        Signal triggered when someone changes the selection in the main publish area
        """
        
        selected_indexes = selected.indexes()
        
        if len(selected_indexes) == 0:
            self._setup_details_panel(None)
            
        else:
            # get the currently selected model index
            model_index = selected_indexes[0]
    
            # the incoming model index is an index into our proxy model
            # before continuing, translate it to an index into the 
            # underlying model
            proxy_model = model_index.model()
            source_index = proxy_model.mapToSource(model_index)
            
            # now we have arrived at our model derived from StandardItemModel
            # so let's retrieve the standarditem object associated with the index
            item = source_index.model().itemFromIndex(source_index)                
            self._setup_details_panel(item)
        
        
    def _on_publish_double_clicked(self, model_index):
        """
        When someone double clicks an item in the publish area,
        ensure that the details pane is visible
        """
        
        # the incoming model index is an index into our proxy model
        # before continuing, translate it to an index into the 
        # underlying model
        proxy_model = model_index.model()
        source_index = proxy_model.mapToSource(model_index)
        
        # now we have arrived at our model derived from StandardItemModel
        # so let's retrieve the standarditem object associated with the index
        item = source_index.model().itemFromIndex(source_index)
        
        is_folder = item.data(SgLatestPublishModel.IS_FOLDER_ROLE)
        
        if is_folder:
            
            # get the corresponding tree view item
            tree_view_item = item.data(SgLatestPublishModel.ASSOCIATED_TREE_VIEW_ITEM_ROLE)
            
            # select it in the tree view
            self._select_item_in_entity_tree(self._current_entity_preset, tree_view_item)
            
        else:
            # ensure publish details are visible
            if not self.ui.info.isChecked():
                self.ui.info.setChecked(True)
        
    ########################################################################################
    # entity listing tree view and presets toolbar
        
    def _select_item_in_entity_tree(self, tab_caption, item):
        """
        Select an item in the entity tree, ensure the tab
        which holds it is selected and scroll to make it visible.
        
        Item can be None - in this case, nothing is selected.
        """
        
        # indicate that all events triggered by operations in here
        # originated from this programmatic request and not by
        # a user's click
        self._programmatic_selection_mode = True
        
        try:
            # set the right tab
            if tab_caption != self._current_entity_preset:            
                for idx in range(self.ui.entity_preset_tabs.count()):
                    tab_name = self.ui.entity_preset_tabs.tabText(idx)
                    if tab_name == tab_caption:
                        # click the tab view control. This will call the 
                        # on-index changed events, shift the new content
                        # into view and prepare the treeview.
                        self.ui.entity_preset_tabs.setCurrentIndex(idx)
            
            
            # now focus on the item
            view = self._entity_presets[self._current_entity_preset].view
            selection_model = view.selectionModel()

            if item:
                # ensure that the tree view is expanded and that the item we are about 
                # to selected is in vertically centered in the widget
                view.scrollTo(item.index(), QtGui.QAbstractItemView.PositionAtCenter)
                selection_model.clear()
                selection_model.select(item.index(), QtGui.QItemSelectionModel.ClearAndSelect)
                selection_model.setCurrentIndex(item.index(), QtGui.QItemSelectionModel.ClearAndSelect)
                
            else:
                # clear selection to match none item
                selection_model.clear()
                                
            # note: the on-select event handler will take over at this point and register
            # history, handle click logic etc.
            
        finally:
            self._programmatic_selection_mode = False
        
    def _load_entity_presets(self):
        """
        Loads the entity presets from the configuration and sets up buttons and models
        based on the config.
        """
        app = tank.platform.current_bundle()
        entities = app.get_setting("entities")
        
        for e in entities:
            
            # validate that the settings dict contains all items needed.
            for k in ["caption", "entity_type", "hierarchy", "filters"]:
                if k not in e:
                    raise TankError("Configuration error: One or more items in %s "
                                    "are missing a '%s' key!" % (entities, k))
        
            # set up a bunch of stuff
            
            # resolve any magic tokens in the filter
            resolved_filters = []
            for filter in e["filters"]:
                resolved_filter = []
                for field in filter:
                    if field == "{context.entity}":
                        field = app.context.entity
                    elif field == "{context.project}":
                        field = app.context.project
                    elif field == "{context.step}":
                        field = app.context.step
                    elif field == "{context.task}":
                        field = app.context.task
                    elif field == "{context.user}":
                        field = app.context.user                    
                    resolved_filter.append(field)
                resolved_filters.append(resolved_filter)
            e["filters"] = resolved_filters
            
            
            preset_name = e["caption"]
            sg_entity_type = e["entity_type"]
            
                        
            # now set up a new tab
            tab = QtGui.QWidget()
            # add a layout
            layout = QtGui.QVBoxLayout(tab)
            layout.setSpacing(1)
            layout.setContentsMargins(1, 1, 1, 1)
            # and add a treeview
            view = QtGui.QTreeView(tab)
            layout.addWidget(view)
            # add it to the main tab UI
            self.ui.entity_preset_tabs.addTab(tab, preset_name)

            # make sure we keep a handle to all the new objects
            # otherwise the GC may not work
            self._dynamic_widgets.extend( [tab, layout, view] )

            # set up data backend
            model = SgEntityModel(view, sg_entity_type, e["filters"], e["hierarchy"])

            # configure the view
            view.setEditTriggers(QtGui.QAbstractItemView.NoEditTriggers)
            view.setProperty("showDropIndicator", False)
            view.setIconSize(QtCore.QSize(16, 16))
            view.setHeaderHidden(True)
            view.setModel(model)
        
            # set up on-select callbacks - need to help pyside GC (maya 2012)
            # by first creating a direct handle to the selection model before
            # setting up signal / slots
            selection_model = view.selectionModel()
            self._dynamic_widgets.append(selection_model)            
            selection_model.selectionChanged.connect(self._on_treeview_item_selected)
            
            # finally store all these objects keyed by the caption
            ep = EntityPreset(preset_name,
                              sg_entity_type,
                              model,
                              view)
            
            self._entity_presets[preset_name] = ep
            
        # hook up an event handler when someone clicks a tab
        self.ui.entity_preset_tabs.currentChanged.connect(self._on_entity_profile_tab_clicked)
                
        # finalize initialization by clicking the home button, but only once the 
        # data has properly arrived in the model. 
        self._on_home_clicked()
        
    def _on_entity_profile_tab_clicked(self):
        """
        Called when someone clicks one of the profile tabs
        """
        # get the name of the clicked tab        
        curr_tab_index = self.ui.entity_preset_tabs.currentIndex()
        curr_tab_name = self.ui.entity_preset_tabs.tabText(curr_tab_index)

        # and set up which our currently visible preset is
        self._current_entity_preset = curr_tab_name 
                
        if self._history_navigation_mode == False:
            # when we are not navigating back and forth as part of 
            # history navigation, ask the currently visible
            # view to (background async) refresh its data
            model = self._entity_presets[self._current_entity_preset].model
            model.async_refresh()
        
        if self._programmatic_selection_mode == False:
            # this request is because a user clicked a tab
            # and not part of a history operation (or other)

            # programmatic selection means the operation is part of a
            # combo selection process, where a tab is first selection
            # and then an item. So in this case we should not 
            # register history or trigger a refresh of the publish
            # model, since these operations will be handled by later
            # parts of the combo operation

            # now figure out what is selected            
            selected_item = None
            selection_model = self._entity_presets[self._current_entity_preset].view.selectionModel()
            if selection_model.hasSelection():
                # get the current index
                current = selection_model.selection().indexes()[0]
                # get selected item
                selected_item = current.model().itemFromIndex(current)
            
            # tell details view to clear
            self._setup_details_panel(None)
            
            # add history record
            self._add_history_record(self._current_entity_preset, selected_item)
            
            # tell the publish view to change 
            self._load_publishes_for_entity_item(selected_item)            

        
        
    def _on_treeview_item_selected(self):
        """
        Signal triggered when someone changes the selection in a treeview.
        """
        print "SELECTION CHANGED!"
        # update breadcrumbs
        self._populate_entity_breadcrumbs()
        
        selection_model = self._entity_presets[self._current_entity_preset].view.selectionModel()
        
        item = None
        
        if selection_model.hasSelection():            
            # get the current index
            current = selection_model.selection().indexes()[0]
            # get selected item
            item = current.model().itemFromIndex(current)
        
        # notify history
        self._add_history_record(self._current_entity_preset, item)
        
        # tell details panel to clear itself
        self._setup_details_panel(None)
        
        # tell publish UI to update itself
        self._load_publishes_for_entity_item(item)
            
    
    def _load_publishes_for_entity_item(self, item):
        """
        Given an item from the treeview, or None if no item
        is selected, prepare the publish area UI.
        """
        
        # clear selection. If we don't clear the model at this point, 
        # the selection model will attempt to pair up with the model is
        # data is being loaded in, resulting in many many events
        self.ui.publish_view.selectionModel().clear()
        
        if item is None:
            self._publish_model.load_data(None, [])
        
        else:

            # get all the folder children - these need to be displayed
            # by the model as folders
            child_folders = []
            for child_idx in range(item.rowCount()):
                child_folders.append(item.child(child_idx))

            sg_data = item.data(ShotgunModel.SG_DATA_ROLE)
            
            if sg_data is None:
                show_sub_items = self.ui.show_sub_items.isChecked()
                if show_sub_items:
                    # we are at an intermediary node and the sub items is ticked!
                    # load up a partial query
                    partial_filters = item.model().get_filters(item)
                    entity_type = item.model().get_entity_type()
                    self._publish_model.load_data_based_on_query(partial_filters, entity_type, child_folders)
                    
                else:
                    # do not include shotgun matches 
                    self._publish_model.load_data(None, child_folders)
                    
            else:
                # we are at a leaf level. 
                self._publish_model.load_data(sg_data, child_folders)
            

    def _populate_entity_breadcrumbs(self):
        """
        Computes the current entity breadcrumbs
        """
        
        selection_model = self._entity_presets[self._current_entity_preset].view.selectionModel()
        
        crumbs = []
    
        if selection_model.hasSelection():
        
            # get the current index
            current = selection_model.selection().indexes()[0]
            # get selected item
            item = current.model().itemFromIndex(current)
            
            # figure out the tree view selection, 
            # walk up to root, list of items will be in bottom-up order...
            tmp_item = item
            while tmp_item:
                crumbs.append(tmp_item.text())
                tmp_item = tmp_item.parent()
                    
        breadcrumbs = " > ".join( crumbs[::-1] )  
        self.ui.entity_breadcrumbs.setText("<big>%s</big>" % breadcrumbs)
        
        
################################################################################################
# Helper stuff

class EntityPreset(object):
    """
    Little struct that represents one of the tabs / presets in the 
    Left hand side entity tree view
    """
    def __init__(self, name, entity_type, model, view): 
        self.model = model
        self.name = name
        self.view = view
        self.entity_type = entity_type 
