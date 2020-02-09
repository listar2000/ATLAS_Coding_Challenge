import numpy as np
from PyQt5 import uic
from PyQt5.QtWidgets import *
import PyQt5.QtCore as core
import sys
from vispy import scene
import vispy.scene
from custom_util import prompt_saving, prompt_deleting, prompt_custom_input, \
floodfill, crop_reserve, crop_remove, FloodfillError, Scene, identical_list
from models import Segment
import os
import open3d as o3d


class AtlasAnnotationTool(QWidget):
    def __init__(self, app):
        super(AtlasAnnotationTool, self).__init__()
        base_form, window = uic.loadUiType("main.ui")
        self.window = window()
        self.base_form = base_form()
        self.base_form.setupUi(self.window)

        # bookkeeping variable
        self.data_fname = "segments.json"
        self.point_size = 3.5
        self.message = "> Program Started, UI Loaded"
        self.selected_points_id = []
        self.largest_seg_id = -1
        self.segmentations = [] # list of segmentations of type Segmentation

        self.current_data_file_name = None
        self.current_result_point_indices = []

        # scene variables -- common
        self.upperScene = Scene()
        self.lowerScene = Scene()
        self.message_center = None
        self.segmentation_list = None
        self.btn_common_save = None
        self.btn_common_load = None 
        self.btn_common_delete = None

        # scene variable -- floodfill specific buttons
        self.btn_floodfill_done = None
        self.btn_floodfill_cancel = None

        # setup
        self.setUpDisplay()
        self.wireWidgets()
        self.setOnClickListener()
        self.populateSegmentList()

        # added by Star Li: a dict for storing original colors of selected points
        self.selected_colors_original = dict()

        self.multi_segments_point_indices = set()
        self.multi_segments_file_name = None

        # Demo
        # self.addSegmentationItems(["Placeholder 1", "Placeholder 2"])
        # pcd = o3d.io.read_point_cloud("./data/scene.ply")
        # self.upperScene.render(pcd)
        self.window.show()
        app.exec_()

    ####### SET UP FUNCTIONS #######
    def setOnClickListener(self):
        self.btn_floodfill_done.clicked.connect(self.btn_floodfill_done_clicked)
        self.btn_floodfill_cancel.clicked.connect(self.btn_floodfill_cancel_clicked)
        self.upperScene.canvas.events.mouse_release.connect(self.topCanvasClicked)
        self.btn_common_load.clicked.connect(self.btn_common_load_clicked)
        self.btn_common_save.clicked.connect(self.btn_save_clicked)
        self.btn_common_delete.clicked.connect(self.btn_delete_clicked)
        self.segmentation_list.itemDoubleClicked.connect(self.segmentation_list_item_double_clicked)

        self.btn_apply.clicked.connect(self.btn_apply_clicked)
        self.btn_combine.clicked.connect(self.btn_combine_clicked)
        self.btn_custom_input.clicked.connect(self.btn_custom_input_clicked)

    def wireWidgets(self):
        # scene wiring
        self.base_form.data_display_window.addWidget(self.upperScene.canvas.native)
        self.base_form.data_display_window.addWidget(self.lowerScene.canvas.native)

        # message box wiring
        self.message_center = self.base_form.message_center_layout.itemAt(0).widget()

        # segmentation list wiring
        self.segmentation_list = self.base_form.segmentation_layout.itemAt(0).widget()
        # scene button wiring
        self.btn_common_save = self.base_form.common_buttons_layout.itemAt(0).widget()
        self.btn_common_load = self.base_form.common_buttons_layout.itemAt(1).widget()
        self.btn_common_delete = self.base_form.common_buttons_layout.itemAt(2).widget()

        self.checkbox_list = self.base_form.checkBoxList
        self.btn_apply = self.base_form.apply_button
        self.btn_combine = self.base_form.combine_button
        self.btn_custom_input = self.base_form.custom_input

        # Floodfill wiring
        tab_floodfill = self.base_form.system_mode_layout.itemAt(0).widget()
        self.btn_floodfill_done = tab_floodfill.widget(0).children()[1]
        self.btn_floodfill_cancel = tab_floodfill.widget(0).children()[2]


    def setUpDisplay(self):
        self.upperScene.canvas = vispy.scene.SceneCanvas(keys='interactive', show=True)
        self.lowerScene.canvas = vispy.scene.SceneCanvas(keys='interactive', show=True)

    ####### ON CLICK FUNCTIONS #######
    def segmentation_list_item_double_clicked(self):
        '''
        When an item is double clicked, read that file and render it onto the upper scene
        '''
        current_item_text = self.segmentation_list.currentItem().text()
        try:
            current_item_index = int(current_item_text.split(" | ")[0])
            current_segmentation = self.segmentations[current_item_index]
            index_to_highlight = current_segmentation.indices
            fname = str(current_segmentation.data_file_name)

            pcd = o3d.io.read_point_cloud(fname)
            class DataPCDIsEmptyException(Exception):
                pass
            if pcd.is_empty():
                raise DataPCDIsEmptyException("ERR: Data file at {} is cannot be found or is empty".format(fname))

            color = np.asarray(pcd.colors)
            for i in index_to_highlight:
                color[i] = (0, 1, 0)
            pcd.colors = o3d.utility.Vector3dVector(color)

            self.upperScene.render(pcd)
        except ValueError as e:
            self.writeMessage("ERR: Index is not an int --> {}".format(current_item_text.split(" | ")[0]))


    def btn_common_load_clicked(self):
        '''
        When load is clicked, load the file and render it onto the upper scene
        '''
        filename = self.openFileNamesDialog()
        # do filetype checking here
        if filename:
            self.current_data_file_name = filename
            self.writeMessage("Opening file <{}>".format(filename))
            self.upperScene.render(o3d.io.read_point_cloud(filename))

    def btn_floodfill_done_clicked(self):
        '''
        When the floodfill button is clicked
        1. get the selected points
        2. get the surface that needs to be cropped
        3. render the result in the lower scene
        '''
        try:
            surface_to_crop = floodfill(self.selected_points_id, self.upperScene.pcd)
            self.current_result_point_indices = surface_to_crop
            new_pcd = crop_reserve(self.upperScene.pcd, surface_to_crop)
            self.lowerScene.render(new_pcd)

        except Exception as e:
            self.writeMessage(str(e))

        pcd = self.upperScene.pcd
        points = np.asarray(pcd.points)
        colors = np.asarray(pcd.colors) 
        
        self.upperScene.marker.set_data(points, edge_color=colors, face_color=colors, size=self.point_size)

        self.writeMessage("Selected Points is cleared")
        self.selected_points_id = []

        '''
        Added by Star Li: the highlighted points resume their original color once they are 
        no longer selected.
        '''
        self.resume_selected_points()

    def btn_floodfill_cancel_clicked(self):
        '''
        When cancel is clicked
        1. clear all selected points
        2. clear the lower scene
        '''
        self.writeMessage("Selected Segmentation Cancelled".format(len(self.selected_points_id)))
        self.current_result_point_indices = []
        self.lowerScene.clear()

        # added by Star: unselect points, resume their color and size to original ones
        self.resume_selected_points()

    def btn_delete_clicked(self):
        '''
        Implemented by Star Li for the code challenge
        When delete is clicked
        1. Prompt a pop-up window with the same list of segmentations loaded
        2. User can select which segmentations to delete or cancel this operation
        3. Update the segmentations both in-memory and in the .json data file

        Index reset is needed in order to keep track of the list of segments:
        original segment id: 1 -> 2 -> 3 -> 4

        delete segment with id = 2

        after reset: 1 -> 2 (original 3) -> 3 (original 4)
        '''
        data = prompt_deleting(self.segmentations)
        deleteFlag = data["delete"]

        if not deleteFlag:
            self.writeMessage("Delete is cancelled")
            return
        
        import json

        index = data["segment_index"]
        delete_segment = self.segmentations[index]

        new_segments = []

        # reset means we re-order the indices of segments in case there are gaps due to deletion
        count = 0
        for segment in self.segmentations:    
            if segment != delete_segment:
                segment.id = count
                new_segments.append(segment.json())
                count += 1

        with open(self.data_fname, mode='w') as f:
            f.write(json.dumps(new_segments))
        
        # messages that will show up in the message center
        self.writeMessage("Segment {} | {} | {} is deleted".format(delete_segment.id, delete_segment.segment_name, delete_segment.type_class))
        self.writeMessage("Segments are reindexed")

        # in order to sync with the .json file, clear the in-memory data and reload from file
        self.segmentations = []
        self.segmentation_list.clear()
        self.checkbox_list.clear()
        self.populateSegmentList()

    def btn_save_clicked(self):
        '''
        When save is clicked
        1. Prompt the user for the name and type of the object
        2. save the object

        '''
        data = prompt_saving()
        if len(self.current_result_point_indices) == 0:
            self.writeMessage("There are no points to save")
        else:
            import json
            a = []
            if not os.path.isfile(self.data_fname):
                self.largest_seg_id = self.largest_seg_id + 1
                segment = Segment(id=self.largest_seg_id,
                                  data_file_name=self.current_data_file_name,
                                  segment_name=data["seg_name"],
                                  indices=self.current_result_point_indices,
                                  type_class=(data["type_class"], 1)
                                  )
                self.addSegmentationItem(segment)
                entry = segment.json()
                a.append(entry)
                with open(self.data_fname, mode='w') as f:
                    f.write(json.dumps(a, indent=2))
            else:
                with open(self.data_fname) as feedsjson:
                    feeds = json.load(feedsjson)
                self.largest_seg_id = len(feeds)
                segment = Segment(id=self.largest_seg_id,
                                  data_file_name=self.current_data_file_name,
                                  segment_name=data["seg_name"],
                                  indices=self.current_result_point_indices,
                                  type_class=(data["type_class"], 1)
                                  )
                self.addSegmentationItem(segment)
                entry = segment.json()
                feeds.append(entry)
                with open(self.data_fname, mode='w') as f:
                    f.write(json.dumps(feeds, indent=2))
            self.lowerScene.clear()

        # added by Star: unselect points, resume their color and size to original ones
        self.resume_selected_points()

    def topCanvasClicked(self, event):
        '''
        When the top canvas is clicked
        1. rotate the scene if necessary
        2. record the point clicked if necessary
        3. show the points clicked (STILL NEED TO IMPLEMENT)
        :param event: event that the top canvas is clicked.
        :return:
        '''
        pcd = self.upperScene.pcd
        points = np.asarray(pcd.points)
        colors = np.asarray(pcd.colors)
        # axis = scene.visuals.XYZAxis(parent=self.upper.scene)

        # prepare list of unique colors needed for picking
        ids = np.arange(1, len(points) + 1, dtype=np.uint32).view(np.uint8)
        ids = ids.reshape(-1, 4)
        ids = np.divide(ids, 255, dtype=np.float32)
        # connect events
        if event.button == 1 and self.distance_traveled(event.trail()) <= 2:
            pos = self.upperScene.canvas.transforms.canvas_transform.map(event.pos)
            try:
                self.upperScene.marker.update_gl_state(blend=False)
                self.upperScene.marker.antialias = 0
                self.upperScene.marker.set_data(points, edge_color=ids, face_color=ids, size=self.point_size)
                img = self.upperScene.canvas.render((pos[0] - 2,
                                                     pos[1] - 2,
                                                     2 * 10 + 1,
                                                     2 * 10 + 1),
                                                    bgcolor=vispy.color.ColorArray('red'))
                # self.upperScene.canvas.update()
            finally:
                self.upperScene.marker.update_gl_state(blend=True)
                self.upperScene.marker.antialias = 1
                self.upperScene.marker.set_data(points, edge_color=colors, face_color=colors, size=self.point_size)

            # We pick the pixel directly under the click, unless it is
            # zero, in which case we look for the most common nonzero
            # pixel value in a square region centered on the click.
            idxs = img.ravel().view(np.uint32)
            idx = idxs[len(idxs) // 2]

            if idx == 0:
                idxs, counts = np.unique(idxs, return_counts=True)
                idxs = idxs[np.argsort(counts)]
                idx = idxs[-1] or (len(idxs) > 1 and idxs[-2])
            # call the callback function
            if idx > 0:
                try:
                    points[idx]
                    self.selected_points_id.append(idx)
                    # p1.set_data(points, edge_color=colors, face_color=colors, size=2)

                    sizes = np.full(len(points), self.point_size)

                    # display the color of the selected points, keep the original colors in a dict
                    self.selected_colors_original[idx] = np.array(colors[idx])
                    for point_id in self.selected_points_id:
                        # red color
                        colors[point_id] = (1, 0, 0)
                        # enlarge the size of selected points so they are more visible
                        sizes[point_id] = 8
   
                    self.upperScene.marker.set_data(points, edge_color=colors, face_color=colors, size=sizes)
                    self.writeMessage("Selected Points {}".format(self.selected_points_id))
                except IndexError:
                    self.writeMessage("The point {} is not in the point cloud".format(idx))
    

    '''
    Added by Star:
    below are the functions for the `multi-segment` utility which exhibits/combines different segments at the same time
    '''
    def btn_apply_clicked(self):
        checked_segments = []
        for index in range(self.checkbox_list.count()):
            if self.checkbox_list.item(index).checkState() == core.Qt.Checked:
                checked_segments.append(self.segmentations[index])
        
        if len(checked_segments) == 0:
            self.writeMessage("No segment is selected")
            return
        
        # check that all segments selected are for the same data file
        fnames = [str(s.data_file_name) for s in checked_segments]
        if not identical_list(fnames):
            self.writeMessage("Error: segments selected belong to different data files")
            self.writeMessage(set(fnames))
            return
        
        fname = fnames[0]
        self.multi_segments_file_name = fname
        # reset the cache for indices of selected segments (for combination purpose)
        self.multi_segments_point_indices.clear()

        for segment in checked_segments:
            self.multi_segments_point_indices.update(segment.indices)
            
        pcd = o3d.io.read_point_cloud(fname)
        class DataPCDIsEmptyException(Exception):
            pass
        if pcd.is_empty():
            raise DataPCDIsEmptyException("ERR: Data file at {} is cannot be found or is empty".format(fname))

        color = np.asarray(pcd.colors)
        for i in self.multi_segments_point_indices:
            color[i] = (0, 1, 0)
        pcd.colors = o3d.utility.Vector3dVector(color)

        self.upperScene.render(pcd)

        self.writeMessage("Segments: {} are displayed".format([s.segment_name for s in checked_segments]))

    def btn_combine_clicked(self):
        data = prompt_saving()

        if len(self.multi_segments_point_indices) == 0:
            self.writeMessage("No segments are selected to combine. Please apply first.")
            return
        
        # reuse the codes in btn_save_clicked. Can be refractored later.
        import json
        a = []
        if not os.path.isfile(self.data_fname):
            self.largest_seg_id = self.largest_seg_id + 1
            segment = Segment(id=self.largest_seg_id,
                                data_file_name=self.current_data_file_name,
                                segment_name=data["seg_name"],
                                indices=self.multi_segments_point_indices,
                                type_class=(data["type_class"], 1)
                                )
            self.addSegmentationItem(segment)
            entry = segment.json()
            a.append(entry)
            with open(self.data_fname, mode='w') as f:
                f.write(json.dumps(a, indent=2))
        else:
            with open(self.data_fname) as feedsjson:
                feeds = json.load(feedsjson)
            self.largest_seg_id = len(feeds)
            segment = Segment(id=self.largest_seg_id,
                                data_file_name=self.current_data_file_name,
                                segment_name=data["seg_name"],
                                indices=self.multi_segments_point_indices,
                                type_class=(data["type_class"], 1)
                                )
            self.addSegmentationItem(segment)
            entry = segment.json()
            feeds.append(entry)
            with open(self.data_fname, mode='w') as f:
                f.write(json.dumps(feeds, indent=2))
    
    '''
    Added by Star: the below function is used to show cropped region given user custom input
    '''
    def btn_custom_input_clicked(self):
        data = prompt_custom_input()
        if not data["confirmFlag"]:
            self.writeMessage("Custom input is cancelled")
            return
        if self.upperScene.pcd == None:
            self.writeMessage("Please load data before user custom input")
            return

        try:
            points_data = [float(num) for num in data["points_data"]]  
        except Exception as e:
            self.writeMessage("User input need to be int/float")

        try:
            surface_to_crop = floodfill(points_data, self.upperScene.pcd, custom_input=True)
            self.current_result_point_indices = surface_to_crop
            new_pcd = crop_reserve(self.upperScene.pcd, surface_to_crop)
            self.lowerScene.render(new_pcd)

        except Exception as e:
            self.writeMessage(str(e))

        pcd = self.upperScene.pcd
        points = np.asarray(pcd.points)
        colors = np.asarray(pcd.colors) 
        
        self.upperScene.marker.set_data(points, edge_color=colors, face_color=colors, size=self.point_size)


    ####### UTILITIES FUNCTIONS #######

    '''
    Added by Star:
    Once the selected points (highlighted) are cancelled/saved, resume their point size and color to the original ones
    '''
    def resume_selected_points(self):
        pcd = self.upperScene.pcd
        points = np.asarray(pcd.points)
        colors = np.asarray(pcd.colors)

        for index in self.selected_points_id:
            colors[index] = self.selected_colors_original[index]
                
        self.upperScene.marker.set_data(points, edge_color=colors, face_color=colors, size=self.point_size)

        self.selected_points_id.clear()
        self.selected_colors_original.clear()

    def openFileNamesDialog(self):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        files, _ = QFileDialog.getOpenFileNames(self, "QFileDialog.getOpenFileNames()", "",
                                                "All Files (*);;Python Files (*.py)", options=options)
        if files:
            return files[0]
        return None

    @staticmethod
    def distance_traveled(positions):
        """
        Return the total amount of pixels traveled in a sequence of pixel
        `positions`, using Manhattan distances for simplicity.
        """
        return np.sum(np.abs(np.diff(positions, axis=0)))

    def addSegmentationItem(self, segment):
        self.segmentations.append(segment)
        self.segmentation_list.addItem("{} | {} | {}".format(segment.id, segment.segment_name, segment.type_class))

        '''
        Added by Star: for the multi-segment functionality, a list of available segments (the same
        as those in the right lower corner) will be given in checkbox form to visualize/combines
        '''
        item = QListWidgetItem()
        item.setText("{} | {} | {}".format(segment.id, segment.segment_name, segment.type_class))
        item.setFlags(item.flags() | core.Qt.ItemIsUserCheckable)
        item.setCheckState(core.Qt.Unchecked)
        self.checkbox_list.addItem(item)

    def writeMessage(self, message):
        '''
        Iteratively populate message
        :param message: new message given
        '''
        self.message = "{} \n> {}".format(self.message, message)  # format the text so that it is one per line
        self.message_center.setPlainText(self.message)  # no url displaying
        self.message_center.verticalScrollBar().setValue(
            self.message_center.verticalScrollBar().maximum())  # scroll bar to the bottom by default

    def populateSegmentList(self):
        '''
        On start, populate a list of segmentations that user previously did
        '''
        try:
            import json
            with open(self.data_fname, 'r') as f:
                segmentations = json.load(f)
            for segment in segmentations:
                segment_dict = json.loads(segment)
                seg = Segment(**segment_dict)
                self.addSegmentationItem(seg)
        except FileNotFoundError as e:
            self.writeMessage("No segmentations detected")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    annotation_tool = AtlasAnnotationTool(app)
