import json
import math
import os
import shutil
import threading
from collections import namedtuple

from PyQt5.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QPushButton, QMainWindow, QScrollArea, QHBoxLayout, QVBoxLayout, QWidget, QSizePolicy, QSplitter, QLayoutItem
from PyQt5.QtWidgets import QLineEdit, QTextEdit, QMenu, QListView, QAction, QFileSystemModel, QTreeView, QProgressBar
from PyQt5.QtWidgets import QFileDialog, QDialog, QListWidget, QListWidgetItem, QMessageBox, QSpacerItem
from PyQt5.QtGui import QPixmap, QImage, QCursor, QImageReader, QIcon, QColor, QDesktopServices, QFont
from PyQt5.QtCore import Qt, QDir, QSize, QPoint, QMutex, QUrl, QProcess, QSysInfo
from PyQt5.QtCore import QItemSelectionModel, QItemSelection
from PyQt5 import QtCore

QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True) #enable highdpi scaling
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True) #use highdpi icons

ImageRecord = namedtuple('ImageRecord', ['path', 'tag_path', 'tags'])

def hline(*widgets, **kwargs):
    stretch = kwargs.get('stretch', None)
    hbox = QHBoxLayout()
    for w in widgets:
        if isinstance(w, QWidget):
            hbox.addWidget(w)
        elif isinstance(w, QLayoutItem):
            hbox.addItem(w)
    if stretch:
        for i, p in enumerate(stretch):
            if p:
                hbox.setStretch(i, p)
    return hbox

class CropResizeAndSaveToDialog(QDialog):
    image_cropped = QtCore.pyqtSignal(str)
    image_all_croped = QtCore.pyqtSignal()

    def __init__(self, parent=None, files=[]):
        super().__init__(parent)
        self.files = files
        self.setFont(QFont('Helvetica, Arial, Sans Serif', 11))
        
        # Create widgets for the dialog
        self.item_list = QListWidget()
        self.item_map = {}
        for path in self.files:
            listitem = QListWidgetItem(path)
            self.item_list.addItem(listitem)
            self.item_map[path] = listitem
        size_label = QLabel('Width x Height:')
        self.crop_width_edit = QLineEdit()
        self.crop_width_edit.setText('512')
        self.crop_width_edit.setFixedWidth(50)
        x_label = QLabel('x')
        self.crop_height_edit = QLineEdit()
        self.crop_height_edit.setText('512')
        self.crop_height_edit.setFixedWidth(50)
        self.save_dir_label = QLabel('Save To:')
        self.save_dir_edit = QLineEdit()
        self.save_dir_edit.setText(os.path.join(os.path.commonprefix(self.files), 'prepared'))
        self.save_dir_button = QPushButton('...')
        self.save_dir_button.clicked.connect(self.browse_save_dir)
        self.do_override = QCheckBox('Override existing files')
        self.prefix = QLineEdit()
        self.prefix.setFixedWidth(100)
        self.progress = QProgressBar()
        self.save_button = QPushButton('Save')
        self.save_button.clicked.connect(self.save_images)
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.clicked.connect(self.do_cancel)
        self.work_thread = None
        self.canceled = False
        self.image_cropped.connect(self.on_image_croped)
        self.image_all_croped.connect(self.on_image_all_croped)
        self.num_job_done = 0
        
        # Create layout for the dialog
        layout = QVBoxLayout()
        layout.addWidget(self.item_list)
        layout.addWidget(self.progress)
        layout.addLayout(hline(size_label, self.crop_width_edit, x_label, self.crop_height_edit, QSpacerItem(0,0,QSizePolicy.Expanding), stretch=(0, 0, 0, 0, 1)))
        layout.addLayout(hline(self.save_dir_label, self.save_dir_edit, self.save_dir_button, stretch=(0, 1, 0)))
        layout.addLayout(hline(self.do_override, QLabel('Name prefix:'), self.prefix, stretch=(0, 0, 1)))
        layout.addLayout(hline(self.save_button, self.cancel_button))
        self.setLayout(layout)
        
    def browse_save_dir(self):
        """Open a file dialog to choose the directory to save the cropped images"""
        save_dir = QFileDialog.getExistingDirectory(self, 'Choose Directory', self.save_dir_edit.text())
        if save_dir:
            self.save_dir_edit.setText(save_dir)

    def do_cancel(self):
        self.canceled = True
        if self.work_thread:
            self.work_thread.join()
        self.reject()

    def on_image_croped(self, path):
        self.num_job_done += 1
        self.progress.setValue(self.num_job_done/len(self.files)*100)
        self.item_map[path].setBackground(QColor(104, 159, 56))

    def on_image_all_croped(self):
        self.accept()
        
    def save_images(self):
        """Crop and save the selected images to the chosen directory"""
        # Don't press twice
        self.save_button.setEnabled(False)

        # Get the crop width and height from the edit boxes
        crop_width = int(self.crop_width_edit.text())
        crop_height = int(self.crop_height_edit.text())

        override = self.do_override.isChecked()
        prefix = self.prefix.text()
        
        # Get the save directory from the edit box
        save_dir = self.save_dir_edit.text()
        if not save_dir:
            QMessageBox.warning(self, 'No Save Directory', 'Please choose a directory to save the cropped images.')
            return
        if not os.path.exists(save_dir):
            try:
                os.makedirs(save_dir)
            except:
                QMessageBox.warning(self, 'Invalid Save Directory', 'The chosen directory is invalid.')
                return

        def thread_function():
            # Crop and save each selected image
            for path in self.files:
                if self.canceled:
                    break
                image = QImage(path)
                # resize to best matching size, crop the center area if aspect ratio is different
                if image.width()/image.height() > crop_width/crop_height:
                    image = image.scaledToHeight(crop_height, Qt.SmoothTransformation)
                    crop_x = (image.width() - crop_width) // 2
                    crop_y = 0
                    cropped_image = image.copy(crop_x, crop_y, crop_width, crop_height)
                else:
                    image = image.scaledToWidth(crop_width, Qt.SmoothTransformation)
                    crop_x = 0
                    crop_y = (image.height() - crop_height) // 2
                    cropped_image = image.copy(crop_x, crop_y, crop_width, crop_height)
                
                save_path = os.path.join(save_dir, prefix+os.path.basename(path))
                if override or not os.path.exists(save_path):
                    cropped_image.save(save_path)
                self.image_cropped.emit(path)
            self.image_all_croped.emit()

        self.work_thread = threading.Thread(target=thread_function)
        self.work_thread.start()

class ImageTagger(QMainWindow):
    thumbnail_size = 512

    def __init__(self):
        super().__init__()

        self.setWindowTitle('Image Tagger')
        self.setAcceptDrops(True)
        self.setFont(QFont('Helvetica, Arial, Sans Serif', 12))

        # Create a splitter widget to divide the window into two panels
        self.splitter = QSplitter()

        # Create a vertical box layout to hold the tree view widget and the choose directory button
        vbox = QVBoxLayout()

        # Create a tree view widget to display the list of images in the left panel
        self.model = QFileSystemModel()
        self.model.setRootPath("/")
        self.model.setReadOnly(True)
        self.model.setNameFilters(['*.jpg', '*.jpeg', '*.png'])
        self.model.setNameFilterDisables(False)
        self.tree = QTreeView()
        self.tree.setColumnWidth(0, 300)
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index("/"))
        self.tree.setSelectionMode(QTreeView.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.filetree_context_menu)

        # Add the tree view widget to the vertical box layout
        vbox.addWidget(self.tree)

        # Create a button widget to choose directory
        self.choose_dir_button = QPushButton('Choose Directory')
        self.choose_dir_button.clicked.connect(self.choose_directory)

        # Add the choose directory button to the vertical box layout
        vbox.addWidget(self.choose_dir_button)

        # Add the vertical box layout to the left panel of the splitter
        left_panel = QWidget()
        left_panel.setLayout(vbox)
        self.splitter.addWidget(left_panel)

        # Create a label widget to display the selected image in the right panel

        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumSize(512, 512) # Set the minimum size of the label widget to 512x512

        right_panel = QSplitter(Qt.Vertical)
        right_panel_down = QWidget()
        right_panel_down_layout = QVBoxLayout()
        right_panel.addWidget(self.label)

        self.thumbnail_list = QListWidget()
        self.thumbnail_list.setMinimumSize(512, 600)
        self.thumbnail_list.setFlow(QListWidget.LeftToRight)
        self.thumbnail_list.setResizeMode(QListWidget.Adjust)
        self.thumbnail_list.setViewMode(QListWidget.IconMode)
        self.thumbnail_list.setIconSize(QSize(128, 128))
        self.thumbnail_list.setGridSize(QSize(138, 158))
        self.thumbnail_list.setMovement(QListWidget.Static)
        self.thumbnail_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.thumbnail_list.itemDoubleClicked.connect(self.thumbnail_double_clicked)
        self.thumbnail_list.keyPressEvent = self.thumbnail_key_pressed
        self.thumbnail_list.selectionModel().selectionChanged.connect(self.on_thumbnail_selection_changed)
        right_panel.addWidget(self.thumbnail_list)
        self.thumbnail_list.hide()

        taglist_layout = QVBoxLayout()
        tagpool_layout = QVBoxLayout()

        self.taglist = QListWidget()
        self.tagpool = QListWidget()

        taglist_layout.addWidget(QLabel('Common Tags of Selection'))
        taglist_layout.addWidget(self.taglist)

        self.taglist.setDragDropMode(QListView.InternalMove)
        self.taglist.setSelectionMode(QListView.ExtendedSelection)
        self.taglist.itemDoubleClicked.connect(self.move_tag_to_pool)
        self.tagpool.itemDoubleClicked.connect(self.move_tag_to_list)
        self.tagpool.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tagpool.customContextMenuRequested.connect(self.tagpool_context_menu)

        self.taglist.keyPressEvent = self.taglist_key_pressed
        self.tagpool.keyPressEvent = self.tagpool_key_pressed
               
        tagpool_layout.addWidget(QLabel('All Tags'))
        tagpool_layout.addWidget(self.tagpool)

        hbox = QHBoxLayout()
        hbox.addLayout(taglist_layout)
        hbox.addLayout(tagpool_layout)

        right_panel_down_layout.addLayout(hbox)

        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText('Add tags here')
        self.tags_edit.returnPressed.connect(lambda: self.add_tag(self.tags_edit.text()) or self.tags_edit.setText('') or self.highlight_pool())
        hbox = QHBoxLayout()
        hbox.addWidget(self.tags_edit)
        self.add_tag_button = QPushButton('Add Tag')
        self.add_tag_button.clicked.connect(lambda: self.add_tag(self.tags_edit.text()) or self.tags_edit.setText('') or self.highlight_pool())
        hbox.addWidget(self.add_tag_button)
        right_panel_down_layout.addLayout(hbox)

        right_panel_down.setLayout(right_panel_down_layout)

        right_panel.addWidget(right_panel_down)

        # Add the label widget to the right panel of the splitter
        self.splitter.addWidget(right_panel)

        # Connect the tree view widget's selectionChanged signal to the on_tree_selection_changed function
        self.tree.selectionModel().selectionChanged.connect(self.on_tree_selection_changed)

        # Set the splitter widget as the central widget of the main window
        self.setCentralWidget(self.splitter)

        self.current_images = {} # {image_path: imagerecord}
        self.common_tags = set() # common set of tags for all selected images
        self.tag_cache = {} # {image_path: set(tags)}
        self.filepath_cache = {} # {image_path: fullpath}
        self.image_cache = {} # {image_path: pixmap}

    def highlight_pool(self):
        for item in self.tagpool.findItems('', Qt.MatchContains):
            if self.taglist.findItems(item.text(), Qt.MatchExactly):
                item.setBackground(QColor(200, 200, 200))
            else:
                item.setBackground(QColor(255, 255, 255))

    def move_tag_to_pool(self, item):
        if not self.tagpool.findItems(item.text(), Qt.MatchExactly):
            self.tagpool.addItem(item.text())
            self.tagpool.sortItems()
        self.taglist.takeItem(self.taglist.row(item))
        self.highlight_pool()

    def move_tag_to_list(self, item):
        if not self.taglist.findItems(item.text(), Qt.MatchExactly):
            self.taglist.addItem(item.text())
        self.highlight_pool()

    def taglist_key_pressed(self, event):
        if event.key() == Qt.Key_Delete:
            for item in self.taglist.selectedItems():
                self.taglist.takeItem(self.taglist.row(item))
            self.highlight_pool()
        else:
            QListView.keyPressEvent(self.taglist, event)

    def tagpool_key_pressed(self, event):
        if event.key() == Qt.Key_Delete:
            for item in self.tagpool.selectedItems():
                self.tagpool.takeItem(self.tagpool.row(item))
            self.highlight_pool()
        elif event.key() == Qt.Key_Enter or event.key() == Qt.Key_Return:
            for item in self.tagpool.selectedItems():
                if not self.taglist.findItems(item.text(), Qt.MatchExactly):
                    self.taglist.addItem(item.text())
            self.highlight_pool()
        else:
            QListView.keyPressEvent(self.tagpool, event)

    def thumbnail_key_pressed(self, event):
        if event.key() == Qt.Key_Enter or event.key() == Qt.Key_Return:
            selection = QItemSelection()
            for index in self.find_index_by_basename([item.text() for item in self.thumbnail_list.selectedItems()]):
                selection.merge(QItemSelection(index, index), QItemSelectionModel.Select)
            if selection:
                self.tree.selectionModel().select(selection, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
                self.on_tree_selection_changed(None)

    def tagpool_context_menu(self, pos):
        menu = QMenu()
        current_tag = self.tagpool.currentItem().text()
        select_action = QAction(f'Select all images with tag {current_tag}', self)
        select_action.triggered.connect(lambda: self.select_images_with_tag(current_tag))
        menu.addAction(select_action)

        refresh_action = QAction('Refresh tag pool', self)
        refresh_action.triggered.connect(self.refresh_tagpool)
        menu.addAction(refresh_action)

        menu.exec_(self.tagpool.viewport().mapToGlobal(pos))

    def filetree_context_menu(self, pos):
        menu = QMenu()
        def show_crop_dlg():
            selection = self.tree.selectionModel().selectedRows()
            files = []
            for index in selection:
                files.append(self.model.filePath(index))
            crop_dlg = CropResizeAndSaveToDialog(self, files)
            crop_dlg.setModal(True)
            crop_dlg.exec_()
        resize_dlg_action = QAction('Resize / Crop Selected Items ...', self)
        resize_dlg_action.triggered.connect(show_crop_dlg)
        menu.addAction(resize_dlg_action)
        menu.exec_(self.tree.viewport().mapToGlobal(pos))

    def select_images_with_tag(self, tag):
        selection = QItemSelection()
        for path in self.tag_cache:
            if tag in self.tag_cache[path]:
                index = self.model.index(path)
                if index.isValid():
                    selection.merge(QItemSelection(index, index), QItemSelectionModel.Select)
        self.tree.selectionModel().select(selection, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        self.on_tree_selection_changed(None)

    def refresh_tagpool(self):
        self.tagpool.clear()
        all_tags = set()
        for tags in self.tag_cache.values():
            for tag in tags:
                all_tags.add(tag)
        for tag in all_tags:
            self.tagpool.addItem(tag)
        self.tagpool.sortItems()
        self.highlight_pool()

    def add_tag(self, tag):
        if not self.taglist.findItems(tag, Qt.MatchExactly):
            self.taglist.addItem(tag)
        if not self.tagpool.findItems(tag, Qt.MatchExactly):
            self.tagpool.addItem(tag)
            self.tagpool.sortItems()

    def save_current_tags(self):
        current_tags = [tag.text() for tag in self.taglist.findItems('', Qt.MatchContains)]
        removed_common_tags = (self.common_tags or set()) - set(current_tags)
        added_common_tags = set(current_tags) - (self.common_tags or set())
        print(f'removed common tags: {removed_common_tags}')
        if len(self.current_images) == 1:
            path = list(self.current_images.keys())[0]
            tags = self.current_images[path].tags
            if tags != current_tags:
                self.tag_cache[path] = set(current_tags)
                with open(self.current_images[path].tag_path, 'w') as f:
                    f.write(', '.join(current_tags))
                    print(f'tags for {os.path.basename(path)} saved')
        else:
            for path in self.current_images:
                tags = self.current_images[path].tags.copy()
                for tag in added_common_tags:
                    if tag not in tags:
                        tags.append(tag)
                for tag in removed_common_tags:
                    if tag in tags:
                        tags.remove(tag)
                if tags != self.current_images[path].tags:
                    self.tag_cache[path] = set(tags)
                    with open(self.current_images[path].tag_path, 'w') as f:
                        f.write(', '.join(tags))
                        print(f'tags for {os.path.basename(path)} saved')
                else:
                    print(f'{os.path.basename(path)}: no changes')

    def set_active_images(self, paths, reset_preview=True):
        self.save_current_tags()

        self.common_tags = None
        self.current_images = {}
        all_tags = set()
        processed_files = set()
        for path in paths:
            if path not in self.image_cache:
                self.image_cache[path] = QPixmap(path).scaledToWidth(self.thumbnail_size)
            self.filepath_cache[os.path.basename(path)] = path
            if path in processed_files: # skip duplicates, as multiple indices can point to the same file
                continue
            processed_files.add(path)
            tag_path = os.path.splitext(path)[0] + '.txt'
            try:
                tags = [tag.strip() for tag in open(tag_path).read().split(',')]
                tagset = set(tags)
                self.tag_cache[path] = tagset
                all_tags = all_tags.union(tagset)
                if self.common_tags is None:
                    self.common_tags = tagset
                else:
                    self.common_tags = self.common_tags.intersection(tagset)
                self.current_images[path] = ImageRecord(path, tag_path, tags)
            except FileNotFoundError:
                self.current_images[path] = ImageRecord(path, tag_path, [])

        for tag in all_tags:
            if not self.tagpool.findItems(tag, Qt.MatchExactly):
                self.tagpool.addItem(tag)
        self.tagpool.clearSelection()
        self.tagpool.sortItems()
        self.taglist.clear()
        self.taglist.clearSelection()
        for tag in self.common_tags or []:
            self.taglist.addItem(tag)
        self.highlight_pool()

        if reset_preview:
            self.label.clear()
            if len(self.current_images)==1:
                self.label.setPixmap(self.image_cache.get(list(self.current_images.values())[0].path, None))
                self.label.show()
                self.thumbnail_list.hide()
            else:
                self.label.setText(f'{len(self.current_images)} images selected')
                self.label.hide()
                self.thumbnail_list.show()
                self.thumbnail_list.clear()
                for path in self.current_images:
                    self.thumbnail_list.addItem(QListWidgetItem(QIcon(self.image_cache.get(path, None)), os.path.basename(path)))
 
    def on_thumbnail_selection_changed(self):
        selection = self.thumbnail_list.selectedItems()
        files = []
        if len(selection) == 0:
            for item in self.thumbnail_list.findItems('', Qt.MatchContains):
                files.append(self.filepath_cache[item.text()])
        else:
            for item in selection:
                files.append(self.filepath_cache[item.text()])
        self.set_active_images(files, False)

    def switch_files(self, indices):
        self.save_current_tags()
        processed_files = set()
        files = []
        for index in indices:
            path = self.model.filePath(index)
            if path not in self.image_cache:
                self.image_cache[path] = QPixmap(path).scaledToWidth(self.thumbnail_size)
            self.filepath_cache[os.path.basename(path)] = path
            if path in processed_files: # skip duplicates, as multiple indices can point to the same file
                continue
            processed_files.add(path)
            if not self.is_image_file(index):
                continue
            files.append(path)
        self.set_active_images(files, True)
      
    def closeEvent(self, event):
        self.save_current_tags()

    def find_index_by_basename(self, basenames):
        indices = []
        for name in basenames:
            if name in self.filepath_cache:
                index = self.model.index(self.filepath_cache[name])
                if index.isValid():
                    indices.append(self.model.index(self.filepath_cache[name]))
        return indices

    def thumbnail_double_clicked(self, item):
        indices = self.find_index_by_basename([item.text()])
        if len(indices) < 1:
            return
        index_in_tree = indices[0]
        if index_in_tree.isValid():
            self.tree.selectionModel().select(index_in_tree, QItemSelectionModel.ClearAndSelect)
            self.tree.scrollTo(index_in_tree)

    # Define a function to update the label widget with the selected image
    def on_tree_selection_changed(self, itemSelection):
        selected = self.tree.selectedIndexes()
        self.switch_files(selected)
        print(f'selection changed, {len(self.current_images)} images out of {len(selected)} items selected')

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            url = event.mimeData().urls()[0]
            droppath = url.path()
            if droppath.startswith('/') and os.name == 'nt':
                droppath = droppath[1:]
            if os.path.isdir(droppath):
                self.switch_directory(droppath)
            elif os.path.isfile(droppath):
                self.switch_directory(os.path.dirname(droppath))
                self.tree.setCurrentIndex(self.model.index(droppath))
            else:
                print(f'{droppath}: not a file or directory')
        else:
            event.ignore()

    def switch_directory(self, directory):
        self.tagpool.clear()
        tagfile = os.path.join(os.path.dirname(directory), 'tags.txt')
        tagset = set()
        if os.path.isfile(tagfile):
            for tag in open(tagfile).read().split(','):
                tag = tag.strip()
                if tag and tag not in tagset:
                    self.tagpool.addItem(tag)
                    tagset.add(tag)
            self.tagpool.sortItems()

        self.taglist.clearSelection()
        self.tagpool.clearSelection()
        self.model.setRootPath(directory)
        self.tree.setRootIndex(self.model.index(directory))

    # Define a function to choose directory
    def choose_directory(self):
        directory = QFileDialog.getExistingDirectory(self, 'Choose Directory')
        if directory:
           self.switch_directory(directory)

    def is_image_file(self, index):
        return self.model.fileName(index).lower().endswith(('.png', '.jpg', '.jpeg'))

    def keyPressEvent(self, event):
        print(f'{event.key()} pressed')
        if event.modifiers() == Qt.ControlModifier:
            if event.key() == Qt.Key_N:
                # Select next image file
                next_index = self.tree.currentIndex().sibling(self.tree.currentIndex().row(), 0)
                current_fn = self.model.fileName(next_index)
                while True:
                    next_index = self.tree.indexBelow(next_index)
                    if not next_index.isValid():
                        print('no next')
                        break
                    if self.model.fileName(next_index) != current_fn and self.is_image_file(next_index):
                        print(f'next: {self.model.filePath(next_index)}')
                        self.tree.setCurrentIndex(next_index)
                        self.tree.selectionModel().select(next_index, QItemSelectionModel.ClearAndSelect)
                        self.switch_files([next_index])
                        break
                return
            elif event.key() == Qt.Key_P:
                # Select previous image file
                prev_index = self.tree.currentIndex().sibling(self.tree.currentIndex().row(), 0)
                current_fn = self.model.fileName(prev_index)
                while True:
                    prev_index = self.tree.indexAbove(prev_index)
                    if not prev_index.isValid():
                        print('no prev')
                        break
                    if self.model.fileName(prev_index) != current_fn and self.is_image_file(prev_index):
                        print(f'prev: {self.model.filePath(prev_index)}')
                        self.tree.setCurrentIndex(prev_index)
                        self.tree.selectionModel().select(prev_index, QItemSelectionModel.ClearAndSelect)
                        self.switch_files([prev_index])
                        break
                return
        super().keyPressEvent(event)


if __name__ == '__main__':
    # Create the main window
    app = QApplication([])
    window = ImageTagger()

    # Show the main window
    window.show()

    # Run the event loop
    app.exec_()


