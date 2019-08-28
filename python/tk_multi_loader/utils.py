# Copyright (c) 2015 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.


import glob
import os
import re

import sgtk
from sgtk.platform.qt import QtCore, QtGui
from sgtk import TankError


class ResizeEventFilter(QtCore.QObject):
    """
    Utility and helper.

    Event filter which emits a resized signal whenever
    the monitored widget resizes.

    You use it like this:

    # create the filter object. Typically, it's
    # it's easiest to parent it to the object that is
    # being monitored (in this case self.ui.thumbnail)
    filter = ResizeEventFilter(self.ui.thumbnail)

    # now set up a signal/slot connection so that the
    # __on_thumb_resized slot gets called every time
    # the widget is resized
    filter.resized.connect(self.__on_thumb_resized)

    # finally, install the event filter into the QT
    # event system
    self.ui.thumbnail.installEventFilter(filter)
    """
    resized = QtCore.Signal()

    def eventFilter(self, obj, event):
        """
        Event filter implementation.
        For information, see the QT docs:
        http://doc.qt.io/qt-4.8/qobject.html#eventFilter

        This will emit the resized signal (in this class)
        whenever the linked up object is being resized.

        :param obj: The object that is being watched for events
        :param event: Event object that the object has emitted
        :returns: Always returns False to indicate that no events
                  should ever be discarded by the filter.
        """
        # peek at the message
        if event.type() == QtCore.QEvent.Resize:
            # re-broadcast any resize events
            self.resized.emit()
        # pass it on!
        return False


def create_overlayed_user_publish_thumbnail(publish_pixmap, user_pixmap):
    """
    Creates a sqaure 75x75 thumbnail with an optional overlayed pixmap.
    """
    # create a 100x100 base image
    base_image = QtGui.QPixmap(75, 75)
    base_image.fill(QtCore.Qt.transparent)

    painter = QtGui.QPainter(base_image)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)

    # scale down the thumb
    if not publish_pixmap.isNull():
        thumb_scaled = publish_pixmap.scaled(
            75, 75,
            QtCore.Qt.KeepAspectRatioByExpanding,
            QtCore.Qt.SmoothTransformation)

        # now composite the thumbnail on top of the base image
        # bottom align it to make it look nice
        thumb_img = thumb_scaled.toImage()
        brush = QtGui.QBrush(thumb_img)
        painter.save()
        painter.setBrush(brush)
        painter.setPen(QtGui.QPen(QtCore.Qt.NoPen))
        painter.drawRect(0, 0, 75, 75)
        painter.restore()

    if user_pixmap and not user_pixmap.isNull():

        # overlay the user picture on top of the thumbnail
        user_scaled = user_pixmap.scaled(
            30, 30,
            QtCore.Qt.KeepAspectRatioByExpanding,
            QtCore.Qt.SmoothTransformation)
        user_img = user_scaled.toImage()
        user_brush = QtGui.QBrush(user_img)
        painter.save()
        painter.translate(42, 42)
        painter.setBrush(user_brush)
        painter.setPen(QtGui.QPen(QtCore.Qt.NoPen))
        painter.drawRect(0, 0, 30, 30)
        painter.restore()

    painter.end()

    return base_image


def create_overlayed_folder_thumbnail(image):
    """
    Given a shotgun thumbnail, create a folder icon
    with the thumbnail composited on top. This will return a
    512x400 pixmap object.

    :param image: QImage containing a thumbnail
    :returns: QPixmap with a 512x400 px image
    """
    # folder icon size
    CANVAS_WIDTH = 512
    CANVAS_HEIGHT = 400

    # corner radius when we draw
    CORNER_RADIUS = 10

    # maximum sized canvas we can draw on *inside* the
    # folder icon graphic
    MAX_THUMB_WIDTH = 460
    MAX_THUMB_HEIGHT = 280

    # looks like there are some pyside related memory issues here relating to
    # referencing a resource and then operating on it. Just to be sure, make
    # make a full copy of the resource before starting to manipulate.
    base_image = QtGui.QPixmap(":/res/folder_512x400.png")

    # now attempt to load the image
    # pixmap will be a null pixmap if load fails
    thumb = QtGui.QPixmap.fromImage(image)

    if not thumb.isNull():

        thumb_scaled = thumb.scaled(MAX_THUMB_WIDTH,
                                    MAX_THUMB_HEIGHT,
                                    QtCore.Qt.KeepAspectRatio,
                                    QtCore.Qt.SmoothTransformation)

        # now composite the thumbnail
        thumb_img = thumb_scaled.toImage()
        brush = QtGui.QBrush(thumb_img)

        painter = QtGui.QPainter(base_image)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setBrush(brush)

        # figure out the offset height wise in order to center the thumb
        height_difference = CANVAS_HEIGHT - thumb_scaled.height()
        width_difference = CANVAS_WIDTH - thumb_scaled.width()

        inlay_offset_w = (width_difference/2)+(CORNER_RADIUS/2)
        # add a 30 px offset here to push the image off center to
        # fit nicely inside the folder icon
        inlay_offset_h = (height_difference/2)+(CORNER_RADIUS/2)+30

        # note how we have to compensate for the corner radius
        painter.translate(inlay_offset_w, inlay_offset_h)
        painter.drawRoundedRect(0,
                                0,
                                thumb_scaled.width()-CORNER_RADIUS,
                                thumb_scaled.height()-CORNER_RADIUS,
                                CORNER_RADIUS,
                                CORNER_RADIUS)

        painter.end()

    return base_image


def create_overlayed_publish_thumbnail(image):
    """
    Given a shotgun thumbnail, create a publish icon
    with the thumbnail composited onto a centered otherwise empty canvas.
    This will return a 512x400 pixmap object.


    :param image: QImage containing a thumbnail
    :returns: QPixmap with a 512x400 px image
    """

    CANVAS_WIDTH = 512
    CANVAS_HEIGHT = 400
    CORNER_RADIUS = 10

    # get the 512 base image
    base_image = QtGui.QPixmap(CANVAS_WIDTH, CANVAS_HEIGHT)
    base_image.fill(QtCore.Qt.transparent)

    # now attempt to load the image
    # pixmap will be a null pixmap if load fails
    thumb = QtGui.QPixmap.fromImage(image)

    if not thumb.isNull():

        # scale it down to fit inside a frame of maximum 512x512
        thumb_scaled = thumb.scaled(CANVAS_WIDTH,
                                    CANVAS_HEIGHT,
                                    QtCore.Qt.KeepAspectRatio,
                                    QtCore.Qt.SmoothTransformation)

        # now composite the thumbnail on top of the base image
        # bottom align it to make it look nice
        thumb_img = thumb_scaled.toImage()
        brush = QtGui.QBrush(thumb_img)

        painter = QtGui.QPainter(base_image)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setBrush(brush)

        # figure out the offsets in order to center the thumb
        height_difference = CANVAS_HEIGHT - thumb_scaled.height()
        width_difference = CANVAS_WIDTH - thumb_scaled.width()

        # center it horizontally
        inlay_offset_w = (width_difference/2)+(CORNER_RADIUS/2)
        # center it vertically
        inlay_offset_h = (height_difference/2)+(CORNER_RADIUS/2)

        # note how we have to compensate for the corner radius
        painter.translate(inlay_offset_w, inlay_offset_h)
        painter.drawRoundedRect(0,
                                0,
                                thumb_scaled.width()-CORNER_RADIUS,
                                thumb_scaled.height()-CORNER_RADIUS,
                                CORNER_RADIUS,
                                CORNER_RADIUS)

        painter.end()

    return base_image


def filter_publishes(app, sg_data_list):
    """
    Filters a list of shotgun published files based on the filter_publishes
    hook.

    :param app:           app that has the hook.
    :param sg_data_list:  list of shotgun dictionaries, as returned by the
                          find() call.
    :returns:             list of filtered shotgun dictionaries, same form as
                          the input.
    """
    try:
        # Constructing a wrapper dictionary so that it's future proof to
        # support returning additional information from the hook
        hook_publish_list = [{"sg_publish": sg_data}
                             for sg_data in sg_data_list]

        hook_publish_list = app.execute_hook("filter_publishes_hook",
                                             publishes=hook_publish_list)
        if not isinstance(hook_publish_list, list):
            app.log_error(
                "hook_filter_publishes returned an unexpected result type \
                '%s' - ignoring!"
                % type(hook_publish_list).__name__)
            hook_publish_list = []

        # split back out publishes:
        sg_data_list = []
        for item in hook_publish_list:
            sg_data = item.get("sg_publish")
            if sg_data:
                sg_data_list.append(sg_data)

    except:
        app.log_exception("Failed to execute 'filter_publishes_hook'!")
        sg_data_list = []

    return sg_data_list


def resolve_filters(filters):
    """
    When passed a list of filters, it will resolve strings found in the filters using the context.
    For example: '{context.user}' could get resolved to {'type': 'HumanUser', 'id': 86, 'name': 'Philip Scadding'}

    :param filters: A list of filters that has usually be defined by the user or by default in the environment yml
    config or the app's info.yml. Supports complex filters as well. Filters should be passed in the following format:
    [[task_assignees, is, '{context.user}'],[sg_status_list, not_in, [fin,omt]]]

    :return: A List of filters for use with the shotgun api
    """
    app = sgtk.platform.current_bundle()

    resolved_filters = []
    for filter in filters:
        if type(filter) is dict:
            resolved_filter = {
                "filter_operator": filter["filter_operator"],
                "filters": resolve_filters(filter["filters"])}
        else:
            resolved_filter = []
            for field in filter:
                if field == "{context.entity}":
                    field = app.context.entity
                elif field == "{context.step}":
                    field = app.context.step
                elif field == "{context.project}":
                    field = app.context.project
                elif field == "{context.project.id}":
                    if app.context.project:
                        field = app.context.project.get("id")
                    else:
                        field = None
                elif field == "{context.task}":
                    field = app.context.task
                elif field == "{context.user}":
                    field = app.context.user
                resolved_filter.append(field)
        resolved_filters.append(resolved_filter)
    return resolved_filters


def sequence_range_from_path(path):
    """
    Parses the file name in an attempt to determine the first and last
    frame number of a sequence. This assumes some sort of common convention
    for the file names, where the frame number is an integer at the end of
    the basename, just ahead of the file extension, such as
    file.0001.jpg, or file_001.jpg. We also check for input file names with
    abstracted frame number tokens, such as file.####.jpg, or file.%04d.jpg.

    :param str path: The file path to parse.

    :returns: None if no range could be determined, otherwise (min, max)
    :rtype: tuple or None
    """
    # This pattern will match the following at the end of a string and
    # retain the frame number or frame token as group(1) in the resulting
    # match object:
    #
    # 0001
    # ####
    # %04d
    #
    # The number of digits or hashes does not matter; we match as many as
    # exist.
    frame_pattern = re.compile(r"([0-9#]+|[%]0\dd)$")
    root, ext = os.path.splitext(path)
    match = re.search(frame_pattern, root)

    # If we did not match, we don't know how to parse the file name, or there
    # is no frame number to extract.
    if not match:
        return None

    # We need to get all files that match the pattern from disk so that we
    # can determine what the min and max frame number is.
    glob_path = "%s%s" % (
        re.sub(frame_pattern, "*", root),
        ext,
    )
    files = glob.glob(glob_path)

    # Our pattern from above matches against the file root, so we need
    # to chop off the extension at the end.
    file_roots = [os.path.splitext(f)[0] for f in files]

    # We know that the search will result in a match at this point, otherwise
    # the glob wouldn't have found the file. We can search and pull group 1
    # to get the integer frame number from the file root name.
    frames = [int(re.search(frame_pattern, f).group(1)) for f in file_roots]
    return min(frames), max(frames)


def find_sequence_range(tk, path):
    """
    Helper method attempting to extract sequence information.

    Using the toolkit template system, the path will be probed to
    check if it is a sequence, and if so, frame information is
    attempted to be extracted.

    :param path: Path to file on disk.
    :returns: None if no range could be determined, otherwise (min, max)
    """
    # find a template that matches the path:
    template = None
    try:
        template = tk.template_from_path(path)
    except TankError:
        pass

    if not template:
        # If we don't have a template to take advantage of, then
        # we are forced to do some rough parsing ourself to try
        # to determine the frame range.
        return sequence_range_from_path(path)

    # get the fields and find all matching files:
    fields = template.get_fields(path)
    if "SEQ" not in fields:
        # Ticket #655: older paths match wrong templates,
        # so fall back on path parsing
        return sequence_range_from_path(path)

    files = tk.paths_from_template(template, fields, ["SEQ", "eye"])

    # find frame numbers from these files:
    frames = []
    for file in files:
        fields = template.get_fields(file)
        frame = fields.get("SEQ")
        if frame != None:
            frames.append(frame)
    if not frames:
        return None

    # return the range
    return min(frames), max(frames)

