import sys
import os
import re
import subprocess
import tempfile
import shutil
import glob
import logging
from datetime import datetime
from collections import defaultdict
from PyQt5.QtWidgets import (QApplication, QMainWindow, QFileDialog, QTreeWidget, 
                            QTreeWidgetItem, QVBoxLayout, QHBoxLayout, QWidget, 
                            QPushButton, QLineEdit, QLabel, QMessageBox, 
                            QCheckBox, QGroupBox, QFormLayout, QComboBox, QInputDialog,
                            QProgressDialog, QSplitter, QMenu, QAction, QTextEdit,
                            QDialog, QRadioButton, QButtonGroup, QTabWidget)
from PyQt5.QtCore import Qt, QSize, QThread, pyqtSignal, QEvent
from PyQt5.QtGui import QIcon, QFont, QColor, QTextCursor

# Importar lxml.etree en lugar de xml.etree.ElementTree
try:
    from lxml import etree as ET
except ImportError:
    # Mostrar mensaje de que se necesita instalar lxml
    print("Es necesario instalar la biblioteca lxml. Ejecute: pip install lxml")
    sys.exit(1)

# Configurar logger
def setup_logger():
    logger = logging.getLogger('AbletonSampleManager')
    logger.setLevel(logging.DEBUG)
    
    # Crear un manejador para archivos de log
    log_dir = os.path.join(os.path.expanduser("~"), "AbletonSampleManager_logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    log_file = os.path.join(log_dir, f"asm_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    
    # Crear formato para los logs
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    
    # Añadir el manejador al logger
    logger.addHandler(file_handler)
    
    return logger, log_file

# Clase para mostrar el log en la interfaz
class LogWindow(QDialog):
    def __init__(self, log_file, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Log del programa")
        self.setMinimumSize(800, 600)
        
        layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.NoWrap)
        font = QFont("Courier New", 9)
        self.log_text.setFont(font)
        
        # Añadir el contenido actual del log
        try:
            with open(log_file, 'r') as f:
                self.log_text.setText(f.read())
                cursor = self.log_text.textCursor()
                cursor.movePosition(QTextCursor.End)
                self.log_text.setTextCursor(cursor)
        except Exception as e:
            self.log_text.setText(f"Error al cargar el archivo de log: {str(e)}")
        
        refresh_button = QPushButton("Actualizar")
        refresh_button.clicked.connect(lambda: self.refresh_log(log_file))
        
        layout.addWidget(self.log_text)
        layout.addWidget(refresh_button)
        
        self.setLayout(layout)
    
    def refresh_log(self, log_file):
        """Actualiza el contenido del log en la ventana"""
        try:
            with open(log_file, 'r') as f:
                self.log_text.setText(f.read())
                cursor = self.log_text.textCursor()
                cursor.movePosition(QTextCursor.End)
                self.log_text.setTextCursor(cursor)
        except Exception as e:
            self.log_text.append(f"Error al actualizar el archivo de log: {str(e)}")

# Diálogo para mover archivos a carpeta
class MoveToBatchDialog(QDialog):
    def __init__(self, folder_list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mover archivos a carpeta")
        self.setMinimumWidth(400)
        
        layout = QVBoxLayout()
        
        # Opción para seleccionar carpeta existente
        self.existing_radio = QRadioButton("Seleccionar carpeta existente")
        self.existing_radio.setChecked(True)
        
        self.folder_combo = QComboBox()
        self.folder_combo.addItems(folder_list)
        
        # Opción para crear nueva carpeta
        self.new_radio = QRadioButton("Crear nueva carpeta")
        self.new_folder_input = QLineEdit()
        self.new_folder_input.setPlaceholderText("Nombre de la nueva carpeta")
        self.new_folder_input.setEnabled(False)
        
        # Grupo de radio buttons
        self.radio_group = QButtonGroup()
        self.radio_group.addButton(self.existing_radio, 1)
        self.radio_group.addButton(self.new_radio, 2)
        self.radio_group.buttonClicked.connect(self.toggle_input_fields)
        
        # Botones de aceptar/cancelar
        button_box = QHBoxLayout()
        self.ok_button = QPushButton("Aceptar")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.clicked.connect(self.reject)
        
        button_box.addWidget(self.ok_button)
        button_box.addWidget(self.cancel_button)
        
        # Añadir widgets al layout
        layout.addWidget(self.existing_radio)
        layout.addWidget(self.folder_combo)
        layout.addWidget(self.new_radio)
        layout.addWidget(self.new_folder_input)
        layout.addLayout(button_box)
        
        self.setLayout(layout)
    
    def toggle_input_fields(self, button):
        if button == self.existing_radio:
            self.folder_combo.setEnabled(True)
            self.new_folder_input.setEnabled(False)
        else:
            self.folder_combo.setEnabled(False)
            self.new_folder_input.setEnabled(True)
    
    def get_selected_folder(self):
        if self.existing_radio.isChecked():
            return self.folder_combo.currentText(), False
        else:
            return self.new_folder_input.text(), True

# Clase principal
class AbletonSampleManager(QMainWindow):
    def __init__(self):
        super().__init__()
        # Configurar logger
        self.logger, self.log_file = setup_logger()
        self.logger.info("=== Iniciando Gestor de Samples para Ableton Live ===")
        
        self.setWindowTitle("Gestor de Samples para Ableton Live")
        self.setMinimumSize(1200, 800)
        self.current_project = None
        self.project_folder = None
        self.samples = []
        self.xml_tree = None  # Guardar referencia al árbol XML
        self.xml_root = None  # Guardar referencia a la raíz XML
        self.physical_files = []  # Lista de archivos físicos encontrados
        self.folder_structure = {}  # Estructura de carpetas
        
        self.init_ui()
        self.logger.info("Interfaz principal inicializada")
        
    def init_ui(self):
        # Layout principal (usando splitter)
        main_splitter = QSplitter(Qt.Horizontal)
        
        # Panel izquierdo (estructura de carpetas)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(5, 5, 5, 5)
        
        folder_group = QGroupBox("Estructura de carpetas")
        folder_layout = QVBoxLayout()
        
        # TreeWidget para estructura de carpetas
        self.folder_tree = QTreeWidget()
        self.folder_tree.setHeaderLabels(["Carpetas"])
        self.folder_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folder_tree.customContextMenuRequested.connect(self.show_folder_context_menu)
        self.folder_tree.itemClicked.connect(self.folder_selected)
        
        # Botones de acciones para carpetas
        folder_actions_layout = QHBoxLayout()
        self.refresh_folder_button = QPushButton("Actualizar")
        self.refresh_folder_button.clicked.connect(self.update_folder_tree)
        self.create_folder_button = QPushButton("Nueva carpeta")
        self.create_folder_button.clicked.connect(self.create_new_folder)
        
        folder_actions_layout.addWidget(self.refresh_folder_button)
        folder_actions_layout.addWidget(self.create_folder_button)
        
        folder_layout.addWidget(self.folder_tree)
        folder_layout.addLayout(folder_actions_layout)
        folder_group.setLayout(folder_layout)
        
        left_layout.addWidget(folder_group)
        
        # Panel derecho (principal)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(5, 5, 5, 5)
        
        # Pestaña para las diferentes vistas
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        
        # Tab 1: Gestión de proyecto Ableton
        project_tab = QWidget()
        self.init_project_tab(project_tab)
        
        # Tab 2: Explorador de archivos
        explorer_tab = QWidget()
        self.init_explorer_tab(explorer_tab)
        
        # Tab 3: Operaciones por lotes
        batch_tab = QWidget()
        self.init_batch_tab(batch_tab)
        
        # Añadir pestañas
        self.tabs.addTab(project_tab, "Proyecto Ableton")
        self.tabs.addTab(explorer_tab, "Explorador")
        self.tabs.addTab(batch_tab, "Operaciones por lotes")
        
        right_layout.addWidget(self.tabs)
        
        # Barra de estado para logs rápidos
        self.status_bar = self.statusBar()
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(5, 0, 5, 0)
        
        status_label = QLabel("Estado:")
        self.status_text = QLabel("Listo")
        
        view_log_button = QPushButton("Ver Log")
        view_log_button.clicked.connect(self.show_log_window)
        
        status_widget = QWidget()
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(5, 0, 5, 0)
        status_layout.addWidget(status_label)
        status_layout.addWidget(self.status_text, stretch=1)
        status_layout.addWidget(view_log_button)
        
        self.status_bar.addPermanentWidget(status_widget, 1)
        
        # Añadir los widgets al splitter
        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(right_widget)
        main_splitter.setStretchFactor(0, 1)  # Panel izquierdo
        main_splitter.setStretchFactor(1, 3)  # Panel derecho
        
        # Establecer el splitter como widget central
        self.setCentralWidget(main_splitter)
        
        # Deshabilitar inicialmente los botones que requieren un proyecto cargado
        self.refresh_folder_button.setEnabled(False)
        self.create_folder_button.setEnabled(False)
    
    def init_project_tab(self, tab):
        layout = QVBoxLayout(tab)
        
        # Área superior - Carga de proyecto
        project_group = QGroupBox("Proyecto Ableton Live")
        project_layout = QHBoxLayout()
        
        self.project_path = QLineEdit()
        self.project_path.setPlaceholderText("Ruta al archivo .als")
        self.project_path.setReadOnly(True)
        
        browse_button = QPushButton("Explorar...")
        browse_button.clicked.connect(self.browse_als_file)
        
        project_layout.addWidget(self.project_path)
        project_layout.addWidget(browse_button)
        project_group.setLayout(project_layout)
        
        # Área de información del proyecto
        info_group = QGroupBox("Información del Proyecto")
        info_layout = QFormLayout()
        
        self.project_folder_label = QLabel("No seleccionado")
        self.samples_count_label = QLabel("0")
        self.physical_files_count_label = QLabel("0")
        self.missing_files_count_label = QLabel("0")
        self.folder_count_label = QLabel("0")  # Nueva etiqueta para contar carpetas
        
        info_layout.addRow("Carpeta del Proyecto:", self.project_folder_label)
        info_layout.addRow("Samples en Proyecto:", self.samples_count_label)
        info_layout.addRow("Archivos Físicos Encontrados:", self.physical_files_count_label)
        info_layout.addRow("Archivos Faltantes:", self.missing_files_count_label)
        info_layout.addRow("Número de Carpetas:", self.folder_count_label)
        
        info_group.setLayout(info_layout)
        
        # Área de búsqueda
        search_group = QGroupBox("Búsqueda de Samples")
        search_layout = QHBoxLayout()
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar samples por nombre...")
        self.search_input.textChanged.connect(self.filter_samples)
        
        search_button = QPushButton("Buscar")
        search_button.clicked.connect(self.filter_samples)
        
        self.duplicate_check = QCheckBox("Mostrar duplicados")
        self.duplicate_check.stateChanged.connect(self.filter_samples)
        
        self.missing_check = QCheckBox("Mostrar faltantes")
        self.missing_check.stateChanged.connect(self.filter_samples)
        
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.duplicate_check)
        search_layout.addWidget(self.missing_check)
        search_layout.addWidget(search_button)
        search_group.setLayout(search_layout)
        
        # Área de listado de samples
        samples_group = QGroupBox("Samples encontrados")
        samples_layout = QVBoxLayout()
        
        self.samples_tree = QTreeWidget()
        self.samples_tree.setHeaderLabels(["Nombre", "Ruta relativa", "Ruta absoluta", "Tamaño", "Estado", "Carpeta"])
        self.samples_tree.setColumnWidth(0, 200)
        self.samples_tree.setColumnWidth(1, 250)
        self.samples_tree.setColumnWidth(2, 300)
        self.samples_tree.setColumnWidth(3, 80)
        self.samples_tree.setColumnWidth(4, 80)
        self.samples_tree.setColumnWidth(5, 150)
        self.samples_tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.samples_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.samples_tree.customContextMenuRequested.connect(self.show_samples_context_menu)
        
        samples_layout.addWidget(self.samples_tree)
        samples_group.setLayout(samples_layout)
        
        # Área de acciones
        actions_group = QGroupBox("Acciones")
        actions_layout = QHBoxLayout()
        
        self.add_prefix_button = QPushButton("Añadir prefijo")
        self.add_prefix_button.clicked.connect(self.add_prefix)
        
        self.add_suffix_button = QPushButton("Añadir sufijo")
        self.add_suffix_button.clicked.connect(self.add_suffix)
        
        self.replace_button = QPushButton("Reemplazar texto")
        self.replace_button.clicked.connect(self.replace_text)
        
        self.mark_duplicates_button = QPushButton("Marcar duplicados")
        self.mark_duplicates_button.clicked.connect(self.mark_duplicates)
        
        self.save_changes_button = QPushButton("Guardar cambios")
        self.save_changes_button.clicked.connect(self.save_changes)
        
        self.rescan_button = QPushButton("Re-escanear proyecto")
        self.rescan_button.clicked.connect(self.rescan_project)
        
        # Desactivar botones hasta que se cargue un proyecto
        self.add_prefix_button.setEnabled(False)
        self.add_suffix_button.setEnabled(False)
        self.replace_button.setEnabled(False)
        self.mark_duplicates_button.setEnabled(False)
        self.save_changes_button.setEnabled(False)
        self.rescan_button.setEnabled(False)
        
        actions_layout.addWidget(self.add_prefix_button)
        actions_layout.addWidget(self.add_suffix_button)
        actions_layout.addWidget(self.replace_button)
        actions_layout.addWidget(self.mark_duplicates_button)
        actions_layout.addWidget(self.save_changes_button)
        actions_layout.addWidget(self.rescan_button)
        actions_group.setLayout(actions_layout)
        
        # Añadir todos los grupos al layout del tab
        layout.addWidget(project_group)
        layout.addWidget(info_group)
        layout.addWidget(search_group)
        layout.addWidget(samples_group)
        layout.addWidget(actions_group)
    
    def init_explorer_tab(self, tab):
        layout = QVBoxLayout(tab)
        
        # Grupo para la ruta actual
        path_group = QGroupBox("Ruta actual")
        path_layout = QHBoxLayout()
        
        self.current_path = QLineEdit()
        self.current_path.setReadOnly(True)
        
        browse_folder_button = QPushButton("Explorar...")
        browse_folder_button.clicked.connect(self.browse_folder)
        
        up_folder_button = QPushButton("Subir")
        up_folder_button.clicked.connect(self.go_up_folder)
        
        path_layout.addWidget(self.current_path)
        path_layout.addWidget(up_folder_button)
        path_layout.addWidget(browse_folder_button)
        path_group.setLayout(path_layout)
        
        # Grupo para el explorador de archivos
        explorer_group = QGroupBox("Archivos y carpetas")
        explorer_layout = QVBoxLayout()
        
        self.explorer_tree = QTreeWidget()
        self.explorer_tree.setHeaderLabels(["Nombre", "Tipo", "Tamaño", "Fecha modificación"])
        self.explorer_tree.setColumnWidth(0, 300)
        self.explorer_tree.setColumnWidth(1, 100)
        self.explorer_tree.setColumnWidth(2, 100)
        self.explorer_tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.explorer_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.explorer_tree.customContextMenuRequested.connect(self.show_explorer_context_menu)
        self.explorer_tree.itemDoubleClicked.connect(self.explorer_item_double_clicked)
        
        explorer_layout.addWidget(self.explorer_tree)
        explorer_group.setLayout(explorer_layout)
        
        # Grupo para filtros y acciones
        filter_group = QGroupBox("Filtros y acciones")
        filter_layout = QHBoxLayout()
        
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filtrar por nombre...")
        self.filter_input.textChanged.connect(self.filter_explorer)
        
        self.show_audio_only = QCheckBox("Solo audio")
        self.show_audio_only.stateChanged.connect(self.filter_explorer)
        
        refresh_button = QPushButton("Actualizar")
        refresh_button.clicked.connect(self.refresh_explorer)
        
        create_folder_button = QPushButton("Nueva carpeta")
        create_folder_button.clicked.connect(lambda: self.create_new_folder_explorer())
        
        filter_layout.addWidget(self.filter_input)
        filter_layout.addWidget(self.show_audio_only)
        filter_layout.addWidget(refresh_button)
        filter_layout.addWidget(create_folder_button)
        filter_group.setLayout(filter_layout)
        
        # Añadir todos los grupos al layout del tab
        layout.addWidget(path_group)
        layout.addWidget(filter_group)
        layout.addWidget(explorer_group)
    
    def init_batch_tab(self, tab):
        layout = QVBoxLayout(tab)
        
        # Grupo para selección de carpeta
        folder_group = QGroupBox("Carpeta para operaciones por lotes")
        folder_layout = QHBoxLayout()
        
        self.batch_path = QLineEdit()
        self.batch_path.setReadOnly(True)
        self.batch_path.setPlaceholderText("Seleccione una carpeta para trabajar...")
        
        browse_batch_button = QPushButton("Explorar...")
        browse_batch_button.clicked.connect(self.browse_batch_folder)
        
        folder_layout.addWidget(self.batch_path)
        folder_layout.addWidget(browse_batch_button)
        folder_group.setLayout(folder_layout)
        
        # Grupo para filtros
        filter_group = QGroupBox("Filtros")
        filter_layout = QHBoxLayout()
        
        self.batch_filter = QLineEdit()
        self.batch_filter.setPlaceholderText("Filtrar por nombre...")
        
        self.batch_extensions = QComboBox()
        self.batch_extensions.addItem("Todos los archivos")
        self.batch_extensions.addItem("Solo archivos de audio (.wav, .mp3, .aif...)")
        self.batch_extensions.addItem("Personalizado...")
        self.batch_extensions.currentIndexChanged.connect(self.handle_extension_change)
        
        self.custom_extension = QLineEdit()
        self.custom_extension.setPlaceholderText("Extensiones separadas por comas (.wav,.mp3,...)")
        self.custom_extension.setVisible(False)
        
        filter_button = QPushButton("Aplicar filtros")
        filter_button.clicked.connect(self.apply_batch_filters)
        
        filter_layout.addWidget(self.batch_filter)
        filter_layout.addWidget(self.batch_extensions)
        filter_group.setLayout(filter_layout)
        
        custom_ext_layout = QHBoxLayout()
        custom_ext_layout.addWidget(self.custom_extension)
        custom_ext_layout.addWidget(filter_button)
        
        # Grupo para archivos
        files_group = QGroupBox("Archivos encontrados")
        files_layout = QVBoxLayout()
        
        self.batch_files_tree = QTreeWidget()
        self.batch_files_tree.setHeaderLabels(["Nombre", "Ruta", "Tamaño", "Tipo"])
        self.batch_files_tree.setColumnWidth(0, 250)
        self.batch_files_tree.setColumnWidth(1, 350)
        self.batch_files_tree.setColumnWidth(2, 100)
        self.batch_files_tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        
        files_layout.addWidget(self.batch_files_tree)
        files_group.setLayout(files_layout)
        
        # Grupo para acciones por lotes
        actions_group = QGroupBox("Acciones por lotes")
        actions_layout = QHBoxLayout()
        
        self.batch_prefix_button = QPushButton("Añadir prefijo a seleccionados")
        self.batch_prefix_button.clicked.connect(self.batch_add_prefix)
        
        self.batch_suffix_button = QPushButton("Añadir sufijo a seleccionados")
        self.batch_suffix_button.clicked.connect(self.batch_add_suffix)
        
        self.batch_replace_button = QPushButton("Reemplazar texto")
        self.batch_replace_button.clicked.connect(self.batch_replace_text)
        
        self.batch_move_button = QPushButton("Mover a carpeta")
        self.batch_move_button.clicked.connect(self.batch_move_to_folder)
        
        self.batch_create_folder_button = QPushButton("Crear carpeta con seleccionados")
        self.batch_create_folder_button.clicked.connect(self.batch_create_folder_with_selected)
        
        actions_layout.addWidget(self.batch_prefix_button)
        actions_layout.addWidget(self.batch_suffix_button)
        actions_layout.addWidget(self.batch_replace_button)
        actions_layout.addWidget(self.batch_move_button)
        actions_layout.addWidget(self.batch_create_folder_button)
        actions_group.setLayout(actions_layout)
        
        # Deshabilitar botones hasta que se cargue una carpeta
        self.batch_prefix_button.setEnabled(False)
        self.batch_suffix_button.setEnabled(False)
        self.batch_replace_button.setEnabled(False)
        self.batch_move_button.setEnabled(False)
        self.batch_create_folder_button.setEnabled(False)
        
        # Añadir todos los grupos al layout del tab
        layout.addWidget(folder_group)
        layout.addWidget(filter_group)
        layout.addLayout(custom_ext_layout)
        layout.addWidget(files_group)
        layout.addWidget(actions_group)

    # Métodos para logging y depuración
    def show_log_window(self):
        """Muestra la ventana de log"""
        log_window = LogWindow(self.log_file, self)
        log_window.exec_()
    
    def log_status(self, message, log_level=logging.INFO):
        """Actualiza el estado y registra en el log"""
        self.status_text.setText(message)
        
        if log_level == logging.DEBUG:
            self.logger.debug(message)
        elif log_level == logging.INFO:
            self.logger.info(message)
        elif log_level == logging.WARNING:
            self.logger.warning(message)
        elif log_level == logging.ERROR:
            self.logger.error(message)
        elif log_level == logging.CRITICAL:
            self.logger.critical(message)
    
    # Métodos para gestión de proyecto Ableton
    def browse_als_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Seleccionar archivo Ableton Live", "", "Archivos Ableton Live (*.als)")
        if file_path:
            self.project_path.setText(file_path)
            self.current_project = file_path
            self.project_folder = os.path.dirname(file_path)
            self.project_folder_label.setText(self.project_folder)
            self.log_status(f"Proyecto seleccionado: {file_path}")
            self.load_project()
            
    def load_project(self):
        if not self.current_project:
            return
            
        try:
            # Mostrar diálogo de progreso
            progress = QProgressDialog("Cargando proyecto Ableton Live...", "Cancelar", 0, 100, self)
            progress.setWindowTitle("Cargando proyecto")
            progress.setWindowModality(Qt.WindowModal)
            progress.setValue(0)
            progress.show()
            
            self.log_status("Iniciando carga del proyecto...", logging.INFO)
            
            # Crear un archivo temporal para el XML descomprimido
            self.temp_dir = tempfile.mkdtemp()
            self.temp_xml = os.path.join(self.temp_dir, "temp_project.xml")
            
            # Descomprimir el archivo .als usando gzip
            progress.setValue(10)
            progress.setLabelText("Descomprimiendo archivo .als...")
            self.log_status("Descomprimiendo archivo .als...", logging.INFO)
            subprocess.run(['gzip', '-cd', self.current_project], stdout=open(self.temp_xml, 'wb'))
            
            # Analizar el XML
            progress.setValue(20)
            progress.setLabelText("Analizando estructura del proyecto...")
            self.log_status("Analizando estructura del proyecto...", logging.INFO)
            parser = ET.XMLParser(remove_blank_text=True)
            self.xml_tree = ET.parse(self.temp_xml, parser)
            self.xml_root = self.xml_tree.getroot()
            
            # Escanear la carpeta del proyecto para encontrar archivos físicos
            progress.setValue(30)
            progress.setLabelText("Escaneando carpeta del proyecto...")
            self.log_status("Escaneando carpeta del proyecto...", logging.INFO)
            self.scan_physical_files()
            
            # Analizar la estructura de carpetas
            progress.setValue(40)
            progress.setLabelText("Escaneando estructura de carpetas...")
            self.log_status("Escaneando estructura de carpetas...", logging.INFO)
            self.analyze_folder_structure()
            
            # Buscar samples en el proyecto
            progress.setValue(50)
            progress.setLabelText("Buscando samples en el proyecto...")
            self.log_status("Buscando samples en el proyecto...", logging.INFO)
            self.find_samples_in_project()
            
            # Actualizar la UI
            progress.setValue(80)
            progress.setLabelText("Actualizando interfaz...")
            self.log_status("Actualizando interfaz...", logging.INFO)
            self.update_samples_tree()
            self.update_folder_tree()
            
            # Habilitar botones ahora que hay un proyecto cargado
            self.add_prefix_button.setEnabled(True)
            self.add_suffix_button.setEnabled(True)
            self.replace_button.setEnabled(True)
            self.mark_duplicates_button.setEnabled(True)
            self.save_changes_button.setEnabled(True)
            self.rescan_button.setEnabled(True)
            self.refresh_folder_button.setEnabled(True)
            self.create_folder_button.setEnabled(True)
            
            # Completar diálogo de progreso
            progress.setValue(100)
            self.log_status("Proyecto cargado correctamente", logging.INFO)
            
        except Exception as e:
            self.log_status(f"Error al cargar proyecto: {str(e)}", logging.ERROR)
            QMessageBox.critical(self, "Error", f"Error al cargar el proyecto: {str(e)}")
            # Limpiar archivos temporales en caso de error
            if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
    
    def scan_physical_files(self):
        """Escanea los archivos físicos en la carpeta del proyecto"""
        if not self.project_folder:
            return
            
        self.physical_files = []
        for root, dirs, files in os.walk(self.project_folder):
            for file in files:
                if file.lower().endswith(('.wav', '.mp3', '.aiff', '.aif', '.m4a', '.ogg', '.flac')):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, self.project_folder)
                    size = os.path.getsize(full_path)
                    self.physical_files.append({
                        'name': file,
                        'path': full_path,
                        'rel_path': rel_path,
                        'size': size
                    })
        
        self.physical_files_count_label.setText(str(len(self.physical_files)))
        self.log_status(f"Archivos físicos encontrados: {len(self.physical_files)}")
    
    def analyze_folder_structure(self):
        """Analiza la estructura de carpetas del proyecto"""
        if not self.project_folder:
            return
            
        self.folder_structure = {}
        for root, dirs, files in os.walk(self.project_folder):
            rel_path = os.path.relpath(root, self.project_folder)
            if rel_path == '.':
                rel_path = ''
                
            parent_path = os.path.dirname(rel_path)
            folder_name = os.path.basename(rel_path) if rel_path else '/'
            
            # Contar archivos de audio en la carpeta
            audio_files = [f for f in files if f.lower().endswith(('.wav', '.mp3', '.aiff', '.aif', '.m4a', '.ogg', '.flac'))]
            
            folder_info = {
                'name': folder_name,
                'path': root,
                'rel_path': rel_path,
                'audio_count': len(audio_files),
                'subfolders': [],
                'parent': parent_path
            }
            
            self.folder_structure[rel_path] = folder_info
            
            # Añadir como subcarpeta al padre
            if parent_path in self.folder_structure and rel_path:
                self.folder_structure[parent_path]['subfolders'].append(rel_path)
        
        # Actualizar información de carpetas
        self.folder_count_label.setText(str(len(self.folder_structure)))
        self.log_status(f"Carpetas encontradas: {len(self.folder_structure)}")
    
    def find_samples_in_project(self):
        """Busca samples referenciados en el proyecto Ableton"""
        if not self.xml_root:
            return
            
        # Buscar todos los elementos FileRef en el XML
        self.samples = []
        file_refs = self.xml_root.findall(".//FileRef")
        
        for ref in file_refs:
            try:
                # Obtener el atributo RelativePath
                relative_path = ref.find("RelativePath").attrib.get("Value", "")
                
                # Obtener el nombre del archivo
                filename = os.path.basename(relative_path)
                
                # Construir la ruta absoluta
                full_path = os.path.normpath(os.path.join(self.project_folder, relative_path))
                
                # Verificar si el archivo existe
                file_exists = os.path.isfile(full_path)
                
                # Obtener el tamaño si existe
                size = os.path.getsize(full_path) if file_exists else 0
                
                # Obtener la carpeta contenedora
                folder = os.path.dirname(relative_path)
                
                # Añadir a la lista de samples
                self.samples.append({
                    'name': filename,
                    'relative_path': relative_path,
                    'absolute_path': full_path,
                    'exists': file_exists,
                    'size': size,
                    'folder': folder,
                    'xml_element': ref  # Guardar referencia al elemento XML
                })
            except Exception as e:
                self.log_status(f"Error al procesar FileRef: {str(e)}", logging.ERROR)
        
        # Actualizar información
        self.samples_count_label.setText(str(len(self.samples)))
        missing_count = sum(1 for s in self.samples if not s['exists'])
        self.missing_files_count_label.setText(str(missing_count))
        self.log_status(f"Samples en proyecto: {len(self.samples)}, Faltantes: {missing_count}")
    
    def update_samples_tree(self):
        """Actualiza el árbol de samples según los filtros actuales"""
        # Limpiar el árbol
        self.samples_tree.clear()
        
        # Obtener criterios de filtro
        search_text = self.search_input.text().lower()
        show_duplicates = self.duplicate_check.isChecked()
        show_missing = self.missing_check.isChecked()
        
        # Recopilar duplicados si es necesario
        duplicates = {}
        if show_duplicates:
            for sample in self.samples:
                name = sample['name'].lower()
                if name in duplicates:
                    duplicates[name].append(sample)
                else:
                    duplicates[name] = [sample]
            # Filtrar solo los que tienen duplicados
            duplicates = {k: v for k, v in duplicates.items() if len(v) > 1}
        
        # Cargar los samples en el árbol
        for sample in self.samples:
            # Aplicar filtros
            if search_text and search_text not in sample['name'].lower():
                continue
                
            if show_duplicates and sample['name'].lower() not in duplicates:
                continue
                
            if show_missing and sample['exists']:
                continue
            
            # Crear el ítem del árbol
            item = QTreeWidgetItem(self.samples_tree)
            item.setText(0, sample['name'])
            item.setText(1, sample['relative_path'])
            item.setText(2, sample['absolute_path'])
            item.setText(3, self.format_size(sample['size']))
            
            # Estado (Verde si existe, Rojo si falta)
            status = "Encontrado" if sample['exists'] else "Faltante"
            item.setText(4, status)
            
            # Color según estado
            if not sample['exists']:
                item.setForeground(4, QColor(255, 0, 0))  # Rojo para faltantes
            else:
                item.setForeground(4, QColor(0, 128, 0))  # Verde para encontrados
            
            # Carpeta contenedora
            item.setText(5, sample['folder'])
            
            # Destacar duplicados
            if show_duplicates and sample['name'].lower() in duplicates:
                item.setBackground(0, QColor(255, 255, 0, 50))  # Amarillo claro
    
    def update_folder_tree(self):
        """Actualiza el árbol de carpetas"""
        if not self.folder_structure:
            return
            
        self.folder_tree.clear()
        
        # Crear ítem raíz
        root_item = QTreeWidgetItem(self.folder_tree)
        root_item.setText(0, "Proyecto")
        root_item.setData(0, Qt.UserRole, "")  # Ruta relativa vacía para la raíz
        
        # Añadir la raíz al diccionario de items
        self.folder_items = {"": root_item}
        
        # Añadir carpetas de primer nivel
        root_folders = [f for f in self.folder_structure.keys() if f and "/" not in f]
        for folder_path in sorted(root_folders):
            folder = self.folder_structure[folder_path]
            self.add_folder_to_tree(folder, root_item)
        
        # Expandir el ítem raíz
        self.folder_tree.expandItem(root_item)
    
    def add_folder_to_tree(self, folder, parent_item):
        """Añade una carpeta al árbol de carpetas de forma recursiva"""
        folder_item = QTreeWidgetItem(parent_item)
        folder_item.setText(0, folder['name'])
        folder_item.setData(0, Qt.UserRole, folder['rel_path'])
        
        # Guardar referencia al ítem
        self.folder_items[folder['rel_path']] = folder_item
        
        # Añadir subcarpetas
        for subfolder_path in sorted(folder['subfolders']):
            subfolder = self.folder_structure[subfolder_path]
            self.add_folder_to_tree(subfolder, folder_item)
    
    def filter_samples(self):
        """Filtra la lista de samples según los criterios definidos"""
        self.update_samples_tree()
    
    def show_samples_context_menu(self, position):
        """Muestra un menú contextual para los samples seleccionados"""
        menu = QMenu()
        
        # Obtener elementos seleccionados
        selected_items = self.samples_tree.selectedItems()
        if not selected_items:
            return
            
        # Acciones para samples
        open_folder_action = QAction("Abrir carpeta contenedora", self)
        open_folder_action.triggered.connect(self.open_containing_folder)
        
        move_to_action = QAction("Mover a carpeta...", self)
        move_to_action.triggered.connect(self.move_samples_to_folder)
        
        rename_action = QAction("Renombrar...", self)
        rename_action.triggered.connect(self.rename_sample)
        
        # Añadir acciones al menú
        menu.addAction(open_folder_action)
        menu.addAction(move_to_action)
        menu.addAction(rename_action)
        
        # Mostrar el menú
        menu.exec_(self.samples_tree.viewport().mapToGlobal(position))
    
    def show_folder_context_menu(self, position):
        """Muestra un menú contextual para la carpeta seleccionada"""
        menu = QMenu()
        
        # Obtener el ítem seleccionado
        selected_item = self.folder_tree.currentItem()
        if not selected_item:
            return
            
        # Obtener la ruta relativa de la carpeta
        folder_path = selected_item.data(0, Qt.UserRole)
        
        # Acciones para carpetas
        open_folder_action = QAction("Abrir en el explorador", self)
        open_folder_action.triggered.connect(lambda: self.open_folder_in_explorer(folder_path))
        
        create_subfolder_action = QAction("Crear subcarpeta", self)
        create_subfolder_action.triggered.connect(lambda: self.create_subfolder(folder_path))
        
        # Añadir acciones al menú
        menu.addAction(open_folder_action)
        menu.addAction(create_subfolder_action)
        
        # Mostrar el menú
        menu.exec_(self.folder_tree.viewport().mapToGlobal(position))
    
    def open_containing_folder(self):
        """Abre la carpeta contenedora de los samples seleccionados"""
        selected_items = self.samples_tree.selectedItems()
        if not selected_items:
            return
            
        # Obtener la ruta del primer sample seleccionado
        abs_path = selected_items[0].text(2)
        folder_path = os.path.dirname(abs_path)
        
        # Abrir la carpeta
        self.open_folder_in_explorer(folder_path)
    
    def open_folder_in_explorer(self, folder_path):
        """Abre una carpeta en el explorador de archivos"""
        # Si es una ruta relativa, convertirla a absoluta
        if not os.path.isabs(folder_path):
            folder_path = os.path.join(self.project_folder, folder_path)
        
        # Abrir la carpeta según el sistema operativo
        try:
            if sys.platform == 'win32':
                os.startfile(folder_path)
            elif sys.platform == 'darwin':  # macOS
                subprocess.call(['open', folder_path])
            else:  # Linux
                subprocess.call(['xdg-open', folder_path])
                
            self.log_status(f"Carpeta abierta: {folder_path}")
        except Exception as e:
            self.log_status(f"Error al abrir carpeta: {str(e)}", logging.ERROR)
            QMessageBox.warning(self, "Error", f"No se pudo abrir la carpeta: {str(e)}")
    
    def create_new_folder(self):
        """Crea una nueva carpeta en la ubicación actual"""
        # Obtener la carpeta seleccionada o usar la raíz del proyecto
        selected_item = self.folder_tree.currentItem()
        base_path = ""
        if selected_item:
            base_path = selected_item.data(0, Qt.UserRole)
        
        # Pedir nombre para la nueva carpeta
        folder_name, ok = QInputDialog.getText(self, "Nueva carpeta", "Nombre de la carpeta:")
        if not ok or not folder_name:
            return
            
        # Construir la ruta completa
        rel_path = os.path.join(base_path, folder_name) if base_path else folder_name
        abs_path = os.path.join(self.project_folder, rel_path)
        
        # Crear la carpeta
        try:
            os.makedirs(abs_path, exist_ok=True)
            self.log_status(f"Carpeta creada: {rel_path}")
            
            # Actualizar la estructura de carpetas
            self.analyze_folder_structure()
            self.update_folder_tree()
        except Exception as e:
            self.log_status(f"Error al crear carpeta: {str(e)}", logging.ERROR)
            QMessageBox.warning(self, "Error", f"No se pudo crear la carpeta: {str(e)}")
    
    def create_subfolder(self, parent_path):
        """Crea una subcarpeta en la carpeta seleccionada"""
        # Pedir nombre para la nueva carpeta
        folder_name, ok = QInputDialog.getText(self, "Nueva subcarpeta", "Nombre de la subcarpeta:")
        if not ok or not folder_name:
            return
            
        # Construir la ruta completa
        rel_path = os.path.join(parent_path, folder_name) if parent_path else folder_name
        abs_path = os.path.join(self.project_folder, rel_path)
        
        # Crear la carpeta
        try:
            os.makedirs(abs_path, exist_ok=True)
            self.log_status(f"Subcarpeta creada: {rel_path}")
            
            # Actualizar la estructura de carpetas
            self.analyze_folder_structure()
            self.update_folder_tree()
        except Exception as e:
            self.log_status(f"Error al crear subcarpeta: {str(e)}", logging.ERROR)
            QMessageBox.warning(self, "Error", f"No se pudo crear la subcarpeta: {str(e)}")
    
    def folder_selected(self, item):
        """Maneja la selección de una carpeta en el árbol"""
        folder_path = item.data(0, Qt.UserRole)
        self.log_status(f"Carpeta seleccionada: {folder_path}")
        
        # Actualizar la vista de samples filtrados por esta carpeta
        self.search_input.setText("")
        self.duplicate_check.setChecked(False)
        self.missing_check.setChecked(False)
        
        # Filtrar samples por carpeta
        self.samples_tree.clear()
        for sample in self.samples:
            # Comprobar si el sample está en esta carpeta o subcarpeta
            sample_folder = sample['folder']
            if sample_folder == folder_path or sample_folder.startswith(folder_path + "/"):
                # Crear el ítem del árbol
                item = QTreeWidgetItem(self.samples_tree)
                item.setText(0, sample['name'])
                item.setText(1, sample['relative_path'])
                item.setText(2, sample['absolute_path'])
                item.setText(3, self.format_size(sample['size']))
                
                # Estado (Verde si existe, Rojo si falta)
                status = "Encontrado" if sample['exists'] else "Faltante"
                item.setText(4, status)
                
                # Color según estado
                if not sample['exists']:
                    item.setForeground(4, QColor(255, 0, 0))  # Rojo para faltantes
                else:
                    item.setForeground(4, QColor(0, 128, 0))  # Verde para encontrados
                
                # Carpeta contenedora
                item.setText(5, sample['folder'])
    
    def move_samples_to_folder(self):
        """Mueve los samples seleccionados a otra carpeta"""
        selected_items = self.samples_tree.selectedItems()
        if not selected_items:
            return
            
        # Obtener lista de carpetas
        folder_list = list(self.folder_structure.keys())
        
        # Mostrar diálogo para seleccionar carpeta
        dialog = MoveToBatchDialog(folder_list, self)
        if dialog.exec_() != QDialog.Accepted:
            return
            
        target_folder, is_new = dialog.get_selected_folder()
        
        if is_new:
            # Crear nueva carpeta
            abs_path = os.path.join(self.project_folder, target_folder)
            try:
                os.makedirs(abs_path, exist_ok=True)
                self.log_status(f"Carpeta creada: {target_folder}")
            except Exception as e:
                self.log_status(f"Error al crear carpeta: {str(e)}", logging.ERROR)
                QMessageBox.warning(self, "Error", f"No se pudo crear la carpeta: {str(e)}")
                return
        
        # Mostrar diálogo de progreso
        progress = QProgressDialog("Moviendo archivos...", "Cancelar", 0, len(selected_items), self)
        progress.setWindowTitle("Moviendo archivos")
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        
        # Mover cada archivo
        moved_count = 0
        for i, item in enumerate(selected_items):
            progress.setValue(i)
            
            # Obtener información del sample
            sample_name = item.text(0)
            abs_path = item.text(2)
            
            # Comprobar si el archivo existe
            if not os.path.isfile(abs_path):
                self.log_status(f"Archivo no encontrado: {abs_path}", logging.WARNING)
                continue
                
            # Ruta destino
            new_abs_path = os.path.join(self.project_folder, target_folder, sample_name)
            
            # Mover el archivo
            try:
                # Crear carpeta destino si no existe
                os.makedirs(os.path.dirname(new_abs_path), exist_ok=True)
                
                # Mover el archivo
                shutil.move(abs_path, new_abs_path)
                
                # Calcular nueva ruta relativa
                new_rel_path = os.path.join(target_folder, sample_name)
                
                # Actualizar la información en el XML
                for sample in self.samples:
                    if sample['name'] == sample_name and sample['absolute_path'] == abs_path:
                        # Actualizar ruta relativa en el XML
                        rel_path_elem = sample['xml_element'].find("RelativePath")
                        if rel_path_elem is not None:
                            rel_path_elem.set("Value", new_rel_path)
                            
                        # Actualizar datos en memoria
                        sample['relative_path'] = new_rel_path
                        sample['absolute_path'] = new_abs_path
                        sample['folder'] = target_folder
                        
                        # Actualizar ítem en la UI
                        item.setText(1, new_rel_path)
                        item.setText(2, new_abs_path)
                        item.setText(5, target_folder)
                
                moved_count += 1
                
            except Exception as e:
                self.log_status(f"Error al mover archivo {sample_name}: {str(e)}", logging.ERROR)
        
        # Completar el proceso
        progress.setValue(len(selected_items))
        self.log_status(f"Movidos {moved_count} archivos a {target_folder}")
        
        # Recordar guardar los cambios
        QMessageBox.information(self, "Archivos movidos", 
                               f"Se han movido {moved_count} archivos a la carpeta {target_folder}.\n"
                               "No olvide guardar los cambios para actualizar el proyecto.")
    
    def add_prefix(self):
        """Añade un prefijo a los samples seleccionados"""
        selected_items = self.samples_tree.selectedItems()
        if not selected_items:
            return
            
        # Pedir el prefijo
        prefix, ok = QInputDialog.getText(self, "Añadir prefijo", "Prefijo a añadir:")
        if not ok or not prefix:
            return
            
        # Aplicar el prefijo a cada sample seleccionado
        for item in selected_items:
            self.rename_sample_item(item, f"{prefix}{item.text(0)}")
    
    def add_suffix(self):
        """Añade un sufijo a los samples seleccionados"""
        selected_items = self.samples_tree.selectedItems()
        if not selected_items:
            return
            
        # Pedir el sufijo
        suffix, ok = QInputDialog.getText(self, "Añadir sufijo", "Sufijo a añadir:")
        if not ok or not suffix:
            return
            
        # Aplicar el sufijo a cada sample seleccionado
        for item in selected_items:
            # Obtener nombre y extensión
            name, ext = os.path.splitext(item.text(0))
            # Aplicar el sufijo antes de la extensión
            self.rename_sample_item(item, f"{name}{suffix}{ext}")
    
    def replace_text(self):
        """Reemplaza texto en los nombres de samples seleccionados"""
        selected_items = self.samples_tree.selectedItems()
        if not selected_items:
            return
            
        # Pedir el texto a buscar
        search_text, ok = QInputDialog.getText(self, "Reemplazar texto", "Texto a buscar:")
        if not ok or not search_text:
            return
            
        # Pedir el texto de reemplazo
        replace_text, ok = QInputDialog.getText(self, "Reemplazar texto", "Reemplazar con:")
        if not ok:  # Permite reemplazar con cadena vacía
            return
            
        # Aplicar el reemplazo a cada sample seleccionado
        for item in selected_items:
            new_name = item.text(0).replace(search_text, replace_text)
            if new_name != item.text(0):
                self.rename_sample_item(item, new_name)
    
    def rename_sample_item(self, item, new_name):
        """Renombra un sample en el filesystem y en el XML"""
        old_name = item.text(0)
        old_abs_path = item.text(2)
        old_rel_path = item.text(1)
        
        # Comprobar si el archivo existe
        if not os.path.isfile(old_abs_path):
            self.log_status(f"Archivo no encontrado: {old_abs_path}", logging.WARNING)
            return False
            
        # Calcular nueva ruta
        folder = os.path.dirname(old_abs_path)
        new_abs_path = os.path.join(folder, new_name)
        
        # Comprobar si el nuevo nombre ya existe
        if os.path.exists(new_abs_path):
            self.log_status(f"Ya existe un archivo con el nombre: {new_name}", logging.WARNING)
            return False
            
        # Renombrar el archivo
        try:
            shutil.move(old_abs_path, new_abs_path)
            
            # Calcular nueva ruta relativa
            new_rel_path = os.path.join(os.path.dirname(old_rel_path), new_name)
            
            # Actualizar la información en el XML
            for sample in self.samples:
                if sample['name'] == old_name and sample['absolute_path'] == old_abs_path:
                    # Actualizar ruta relativa en el XML
                    rel_path_elem = sample['xml_element'].find("RelativePath")
                    if rel_path_elem is not None:
                        rel_path_elem.set("Value", new_rel_path)
                        
                    # Actualizar datos en memoria
                    sample['name'] = new_name
                    sample['relative_path'] = new_rel_path
                    sample['absolute_path'] = new_abs_path
                    
                    # Actualizar ítem en la UI
                    item.setText(0, new_name)
                    item.setText(1, new_rel_path)
                    item.setText(2, new_abs_path)
                    
            self.log_status(f"Archivo renombrado: {old_name} -> {new_name}")
            return True
            
        except Exception as e:
            self.log_status(f"Error al renombrar archivo: {str(e)}", logging.ERROR)
            return False
    
    def save_changes(self):
        """Guarda los cambios al proyecto Ableton"""
        if not self.xml_tree or not self.current_project:
            return
            
        try:
            # Crear una copia de respaldo del archivo original
            backup_file = f"{self.current_project}.backup"
            shutil.copy2(self.current_project, backup_file)
            self.log_status(f"Creada copia de respaldo: {backup_file}")
            
            # Guardar el XML modificado
            self.xml_tree.write(self.temp_xml, encoding="UTF-8", xml_declaration=True, pretty_print=True)
            
            # Comprimir el XML de vuelta a formato .als
            with open(self.temp_xml, 'rb') as f_in:
                with subprocess.Popen(['gzip', '-c'], stdin=subprocess.PIPE, stdout=subprocess.PIPE) as proc:
                    compressed_data, _ = proc.communicate(input=f_in.read())
                    
                    # Escribir el archivo comprimido
                    with open(self.current_project, 'wb') as f_out:
                        f_out.write(compressed_data)
            
            self.log_status(f"Cambios guardados en: {self.current_project}")
            QMessageBox.information(self, "Cambios guardados", "Los cambios se han guardado correctamente en el proyecto.")
            
        except Exception as e:
            self.log_status(f"Error al guardar cambios: {str(e)}", logging.ERROR)
            QMessageBox.critical(self, "Error", f"Error al guardar los cambios: {str(e)}")
    
    def rescan_project(self):
        """Re-escanea el proyecto para actualizar la información"""
        if not self.current_project:
            return
            
        self.load_project()
    
    def rename_sample(self):
        """Renombra el sample seleccionado"""
        selected_items = self.samples_tree.selectedItems()
        if not selected_items or len(selected_items) != 1:
            return
            
        item = selected_items[0]
        old_name = item.text(0)
        
        # Pedir el nuevo nombre
        new_name, ok = QInputDialog.getText(self, "Renombrar sample", "Nuevo nombre:", text=old_name)
        if not ok or not new_name or new_name == old_name:
            return
            
        # Renombrar el sample
        self.rename_sample_item(item, new_name)
    
    def mark_duplicates(self):
        """Marca los samples duplicados en la lista"""
        # Activar la casilla de verificación para mostrar duplicados
        self.duplicate_check.setChecked(True)
        
        # Identificar duplicados
        duplicates = {}
        for sample in self.samples:
            name = sample['name'].lower()
            if name in duplicates:
                duplicates[name].append(sample)
            else:
                duplicates[name] = [sample]
        
        # Filtrar solo los que tienen duplicados
        duplicates = {k: v for k, v in duplicates.items() if len(v) > 1}
        
        if not duplicates:
            QMessageBox.information(self, "Duplicados", "No se encontraron samples duplicados.")
            return
        
        # Contar duplicados
        total_duplicates = sum(len(v) for v in duplicates.values()) - len(duplicates)
        
        # Mostrar mensaje con resultados
        QMessageBox.information(self, "Duplicados", 
                            f"Se encontraron {len(duplicates)} nombres de archivo duplicados, "
                            f"con un total de {total_duplicates} archivos duplicados.\n\n"
                            "Se han filtrado los resultados para mostrar solo los duplicados.")

    # Métodos para explorador de archivos
    def browse_folder(self):
        """Abre un diálogo para seleccionar una carpeta"""
        folder_path = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta")
        if folder_path:
            self.current_path.setText(folder_path)
            self.refresh_explorer()

    def go_up_folder(self):
        """Sube un nivel en la jerarquía de carpetas"""
        current = self.current_path.text()
        if current:
            parent = os.path.dirname(current)
            if parent:
                self.current_path.setText(parent)
                self.refresh_explorer()

    def refresh_explorer(self):
        """Refresca el contenido del explorador de archivos"""
        path = self.current_path.text()
        if not path or not os.path.isdir(path):
            return
        
        self.explorer_tree.clear()
        
        try:
            # Obtener contenido de la carpeta
            entries = os.listdir(path)
            
            # Ordenar: primero carpetas, luego archivos
            folders = []
            files = []
            
            for entry in entries:
                full_path = os.path.join(path, entry)
                
                if os.path.isdir(full_path):
                    folders.append((entry, full_path))
                else:
                    files.append((entry, full_path))
            
            # Aplicar filtro de nombre si existe
            filter_text = self.filter_input.text().lower()
            
            # Añadir carpetas al árbol
            for name, full_path in sorted(folders):
                if filter_text and filter_text not in name.lower():
                    continue
                    
                item = QTreeWidgetItem(self.explorer_tree)
                item.setText(0, name)
                item.setText(1, "Carpeta")
                item.setText(2, "")
                item.setText(3, self.get_modification_date(full_path))
                item.setData(0, Qt.UserRole, full_path)
            
            # Añadir archivos al árbol
            for name, full_path in sorted(files):
                # Filtrar por nombre
                if filter_text and filter_text not in name.lower():
                    continue
                    
                # Filtrar solo audio si está activado
                if self.show_audio_only.isChecked():
                    _, ext = os.path.splitext(name)
                    if ext.lower() not in ('.wav', '.mp3', '.aiff', '.aif', '.m4a', '.ogg', '.flac'):
                        continue
                
                item = QTreeWidgetItem(self.explorer_tree)
                item.setText(0, name)
                
                # Tipo de archivo
                _, ext = os.path.splitext(name)
                item.setText(1, ext.upper()[1:] if ext else "")
                
                # Tamaño
                try:
                    size = os.path.getsize(full_path)
                    item.setText(2, self.format_size(size))
                except:
                    item.setText(2, "")
                
                # Fecha de modificación
                item.setText(3, self.get_modification_date(full_path))
                
                # Guardar ruta completa
                item.setData(0, Qt.UserRole, full_path)
        
        except Exception as e:
            self.log_status(f"Error al leer carpeta: {str(e)}", logging.ERROR)

    def filter_explorer(self):
        """Aplica filtros al explorador de archivos"""
        self.refresh_explorer()

    def explorer_item_double_clicked(self, item):
        """Maneja el doble clic en un ítem del explorador"""
        path = item.data(0, Qt.UserRole)
        
        if os.path.isdir(path):
            # Si es una carpeta, navegar a ella
            self.current_path.setText(path)
            self.refresh_explorer()
        else:
            # Si es un archivo, intentar abrirlo
            try:
                if sys.platform == 'win32':
                    os.startfile(path)
                elif sys.platform == 'darwin':  # macOS
                    subprocess.call(['open', path])
                else:  # Linux
                    subprocess.call(['xdg-open', path])
            except Exception as e:
                self.log_status(f"Error al abrir archivo: {str(e)}", logging.ERROR)

    def show_explorer_context_menu(self, position):
        """Muestra un menú contextual en el explorador de archivos"""
        menu = QMenu()
        
        # Obtener el ítem seleccionado
        selected_items = self.explorer_tree.selectedItems()
        if not selected_items:
            # Opciones para cuando no hay selección
            refresh_action = QAction("Actualizar", self)
            refresh_action.triggered.connect(self.refresh_explorer)
            
            new_folder_action = QAction("Nueva carpeta", self)
            new_folder_action.triggered.connect(self.create_new_folder_explorer)
            
            menu.addAction(refresh_action)
            menu.addAction(new_folder_action)
        else:
            # Comprobar si todos son carpetas o todos son archivos
            all_folders = all(os.path.isdir(item.data(0, Qt.UserRole)) for item in selected_items)
            all_files = all(not os.path.isdir(item.data(0, Qt.UserRole)) for item in selected_items)
            
            if all_folders:
                # Acciones para carpetas
                open_action = QAction("Abrir", self)
                open_action.triggered.connect(lambda: self.explorer_item_double_clicked(selected_items[0]))
                
                menu.addAction(open_action)
            
            if all_files:
                # Acciones para archivos
                open_action = QAction("Abrir", self)
                open_action.triggered.connect(lambda: self.explorer_item_double_clicked(selected_items[0]))
                
                open_folder_action = QAction("Abrir carpeta contenedora", self)
                open_folder_action.triggered.connect(lambda: self.open_folder_in_explorer(os.path.dirname(selected_items[0].data(0, Qt.UserRole))))
                
                rename_action = QAction("Renombrar", self)
                rename_action.triggered.connect(lambda: self.rename_explorer_item(selected_items[0]))
                
                menu.addAction(open_action)
                menu.addAction(open_folder_action)
                menu.addAction(rename_action)
        
        # Mostrar el menú
        menu.exec_(self.explorer_tree.viewport().mapToGlobal(position))

    def create_new_folder_explorer(self):
        """Crea una nueva carpeta desde el explorador"""
        current_path = self.current_path.text()
        if not current_path:
            return
            
        # Pedir nombre para la nueva carpeta
        folder_name, ok = QInputDialog.getText(self, "Nueva carpeta", "Nombre de la carpeta:")
        if not ok or not folder_name:
            return
            
        # Crear la carpeta
        try:
            new_folder_path = os.path.join(current_path, folder_name)
            os.makedirs(new_folder_path, exist_ok=True)
            self.log_status(f"Carpeta creada: {new_folder_path}")
            
            # Actualizar el explorador
            self.refresh_explorer()
        except Exception as e:
            self.log_status(f"Error al crear carpeta: {str(e)}", logging.ERROR)
            QMessageBox.warning(self, "Error", f"No se pudo crear la carpeta: {str(e)}")

    def rename_explorer_item(self, item):
        """Renombra un archivo o carpeta en el explorador"""
        path = item.data(0, Qt.UserRole)
        old_name = os.path.basename(path)
        
        # Pedir nuevo nombre
        new_name, ok = QInputDialog.getText(self, "Renombrar", "Nuevo nombre:", text=old_name)
        if not ok or not new_name or new_name == old_name:
            return
            
        # Renombrar
        try:
            new_path = os.path.join(os.path.dirname(path), new_name)
            
            # Comprobar si ya existe
            if os.path.exists(new_path):
                QMessageBox.warning(self, "Error", f"Ya existe un archivo o carpeta con el nombre '{new_name}'")
                return
                
            # Renombrar
            os.rename(path, new_path)
            self.log_status(f"Renombrado: {old_name} -> {new_name}")
            
            # Actualizar el explorador
            self.refresh_explorer()
        except Exception as e:
            self.log_status(f"Error al renombrar: {str(e)}", logging.ERROR)
            QMessageBox.warning(self, "Error", f"No se pudo renombrar: {str(e)}")

    # Métodos para operaciones por lotes
    def browse_batch_folder(self):
        """Abre un diálogo para seleccionar una carpeta para operaciones por lotes"""
        folder_path = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta para operaciones por lotes")
        if folder_path:
            self.batch_path.setText(folder_path)
            self.apply_batch_filters()
            
            # Habilitar botones
            self.batch_prefix_button.setEnabled(True)
            self.batch_suffix_button.setEnabled(True)
            self.batch_replace_button.setEnabled(True)
            self.batch_move_button.setEnabled(True)
            self.batch_create_folder_button.setEnabled(True)

    def handle_extension_change(self, index):
        """Maneja el cambio en el combobox de extensiones"""
        if index == 2:  # Personalizado
            self.custom_extension.setVisible(True)
        else:
            self.custom_extension.setVisible(False)

    def apply_batch_filters(self):
        """Aplica los filtros en la pestaña de operaciones por lotes"""
        folder_path = self.batch_path.text()
        if not folder_path or not os.path.isdir(folder_path):
            return
            
        # Limpiar árbol
        self.batch_files_tree.clear()
        
        # Obtener filtros
        name_filter = self.batch_filter.text().lower()
        extension_type = self.batch_extensions.currentIndex()
        
        # Definir extensiones a buscar
        extensions = []
        if extension_type == 1:  # Solo audio
            extensions = ['.wav', '.mp3', '.aif', '.aiff', '.m4a', '.ogg', '.flac']
        elif extension_type == 2:  # Personalizado
            custom_exts = self.custom_extension.text().split(',')
            extensions = [ext.strip() if ext.strip().startswith('.') else f'.{ext.strip()}' for ext in custom_exts if ext.strip()]
        
        # Buscar archivos recursivamente
        try:
            files = []
            for root, dirs, filenames in os.walk(folder_path):
                for filename in filenames:
                    # Aplicar filtro de nombre
                    if name_filter and name_filter not in filename.lower():
                        continue
                        
                    # Aplicar filtro de extensión
                    if extensions:
                        _, ext = os.path.splitext(filename)
                        if ext.lower() not in extensions:
                            continue
                    
                    full_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(full_path, folder_path)
                    
                    files.append((filename, full_path, rel_path))
            
            # Añadir archivos al árbol
            for filename, full_path, rel_path in sorted(files):
                item = QTreeWidgetItem(self.batch_files_tree)
                item.setText(0, filename)
                item.setText(1, rel_path)
                
                # Tamaño
                try:
                    size = os.path.getsize(full_path)
                    item.setText(2, self.format_size(size))
                except:
                    item.setText(2, "")
                
                # Tipo
                _, ext = os.path.splitext(filename)
                item.setText(3, ext.upper()[1:] if ext else "")
                
                # Guardar ruta completa
                item.setData(0, Qt.UserRole, full_path)
            
            self.log_status(f"Encontrados {self.batch_files_tree.topLevelItemCount()} archivos en {folder_path}")
        
        except Exception as e:
            self.log_status(f"Error al buscar archivos: {str(e)}", logging.ERROR)

    def batch_add_prefix(self):
        """Añade un prefijo a los archivos seleccionados"""
        selected_items = self.batch_files_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Advertencia", "No hay archivos seleccionados")
            return
            
        # Pedir prefijo
        prefix, ok = QInputDialog.getText(self, "Añadir prefijo", "Prefijo a añadir:")
        if not ok or not prefix:
            return
            
        # Mostrar diálogo de progreso
        progress = QProgressDialog("Renombrando archivos...", "Cancelar", 0, len(selected_items), self)
        progress.setWindowTitle("Añadiendo prefijo")
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        
        # Procesar cada archivo
        renamed_count = 0
        for i, item in enumerate(selected_items):
            progress.setValue(i)
            
            full_path = item.data(0, Qt.UserRole)
            filename = item.text(0)
            new_name = f"{prefix}{filename}"
            new_path = os.path.join(os.path.dirname(full_path), new_name)
            
            # Renombrar
            try:
                os.rename(full_path, new_path)
                renamed_count += 1
            except Exception as e:
                self.log_status(f"Error al renombrar {filename}: {str(e)}", logging.ERROR)
        
        # Completar
        progress.setValue(len(selected_items))
        self.log_status(f"Renombrados {renamed_count} archivos")
        
        # Actualizar vista
        self.apply_batch_filters()

    def batch_add_suffix(self):
        """Añade un sufijo a los archivos seleccionados"""
        selected_items = self.batch_files_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Advertencia", "No hay archivos seleccionados")
            return
            
        # Pedir sufijo
        suffix, ok = QInputDialog.getText(self, "Añadir sufijo", "Sufijo a añadir:")
        if not ok or not suffix:
            return
            
        # Mostrar diálogo de progreso
        progress = QProgressDialog("Renombrando archivos...", "Cancelar", 0, len(selected_items), self)
        progress.setWindowTitle("Añadiendo sufijo")
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        
        # Procesar cada archivo
        renamed_count = 0
        for i, item in enumerate(selected_items):
            progress.setValue(i)
            
            full_path = item.data(0, Qt.UserRole)
            filename = item.text(0)
            
            # Separar nombre y extensión
            name, ext = os.path.splitext(filename)
            new_name = f"{name}{suffix}{ext}"
            new_path = os.path.join(os.path.dirname(full_path), new_name)
            
            # Renombrar
            try:
                os.rename(full_path, new_path)
                renamed_count += 1
            except Exception as e:
                self.log_status(f"Error al renombrar {filename}: {str(e)}", logging.ERROR)
        
        # Completar
        progress.setValue(len(selected_items))
        self.log_status(f"Renombrados {renamed_count} archivos")
        
        # Actualizar vista
        self.apply_batch_filters()

    def batch_replace_text(self):
        """Reemplaza texto en los nombres de los archivos seleccionados"""
        selected_items = self.batch_files_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Advertencia", "No hay archivos seleccionados")
            return
            
        # Pedir texto a buscar
        search_text, ok = QInputDialog.getText(self, "Reemplazar texto", "Texto a buscar:")
        if not ok or not search_text:
            return
            
        # Pedir texto de reemplazo
        replace_text, ok = QInputDialog.getText(self, "Reemplazar texto", "Reemplazar con:")
        if not ok:  # Permite reemplazar con cadena vacía
            return
            
        # Mostrar diálogo de progreso
        progress = QProgressDialog("Renombrando archivos...", "Cancelar", 0, len(selected_items), self)
        progress.setWindowTitle("Reemplazando texto")
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        
        # Procesar cada archivo
        renamed_count = 0
        for i, item in enumerate(selected_items):
            progress.setValue(i)
            
            full_path = item.data(0, Qt.UserRole)
            filename = item.text(0)
            
            # Aplicar reemplazo
            new_name = filename.replace(search_text, replace_text)
            if new_name == filename:  # No hay cambios
                continue
                
            new_path = os.path.join(os.path.dirname(full_path), new_name)
            
            # Renombrar
            try:
                os.rename(full_path, new_path)
                renamed_count += 1
            except Exception as e:
                self.log_status(f"Error al renombrar {filename}: {str(e)}", logging.ERROR)
        
        # Completar
        progress.setValue(len(selected_items))
        self.log_status(f"Renombrados {renamed_count} archivos")
        
        # Actualizar vista
        self.apply_batch_filters()

    def batch_move_to_folder(self):
        """Mueve los archivos seleccionados a otra carpeta"""
        selected_items = self.batch_files_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Advertencia", "No hay archivos seleccionados")
            return
            
        # Obtener carpeta base
        base_folder = self.batch_path.text()
        
        # Listar carpetas disponibles
        folders = []
        for root, dirs, _ in os.walk(base_folder):
            for dir_name in dirs:
                rel_path = os.path.relpath(os.path.join(root, dir_name), base_folder)
                folders.append(rel_path)
        
        # Mostrar diálogo para seleccionar/crear carpeta
        dialog = MoveToBatchDialog(folders, self)
        if dialog.exec_() != QDialog.Accepted:
            return
            
        target_folder, is_new = dialog.get_selected_folder()
        
        if is_new:
            # Crear nueva carpeta
            abs_path = os.path.join(base_folder, target_folder)
            try:
                os.makedirs(abs_path, exist_ok=True)
                self.log_status(f"Carpeta creada: {target_folder}")
            except Exception as e:
                self.log_status(f"Error al crear carpeta: {str(e)}", logging.ERROR)
                QMessageBox.warning(self, "Error", f"No se pudo crear la carpeta: {str(e)}")
                return
        
        # Mostrar diálogo de progreso
        progress = QProgressDialog("Moviendo archivos...", "Cancelar", 0, len(selected_items), self)
        progress.setWindowTitle("Moviendo archivos")
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        
        # Mover cada archivo
        moved_count = 0
        for i, item in enumerate(selected_items):
            progress.setValue(i)
            
            full_path = item.data(0, Qt.UserRole)
            filename = item.text(0)
            
            # Ruta destino
            dest_path = os.path.join(base_folder, target_folder, filename)
            
            # Comprobar si ya existe
            if os.path.exists(dest_path):
                self.log_status(f"Ya existe un archivo con el nombre {filename} en la carpeta destino", logging.WARNING)
                continue
            
            # Mover
            try:
                shutil.move(full_path, dest_path)
                moved_count += 1
            except Exception as e:
                self.log_status(f"Error al mover {filename}: {str(e)}", logging.ERROR)
        
        # Completar
        progress.setValue(len(selected_items))
        self.log_status(f"Movidos {moved_count} archivos a {target_folder}")
        
        # Actualizar vista
        self.apply_batch_filters()

    def batch_create_folder_with_selected(self):
        """Crea una nueva carpeta y mueve los archivos seleccionados a ella"""
        selected_items = self.batch_files_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Advertencia", "No hay archivos seleccionados")
            return
            
        # Pedir nombre para la nueva carpeta
        folder_name, ok = QInputDialog.getText(self, "Nueva carpeta", "Nombre de la carpeta:")
        if not ok or not folder_name:
            return
            
        # Obtener carpeta base
        base_folder = self.batch_path.text()
        
        # Crear la carpeta
        new_folder_path = os.path.join(base_folder, folder_name)
        try:
            os.makedirs(new_folder_path, exist_ok=True)
            self.log_status(f"Carpeta creada: {folder_name}")
        except Exception as e:
            self.log_status(f"Error al crear carpeta: {str(e)}", logging.ERROR)
            QMessageBox.warning(self, "Error", f"No se pudo crear la carpeta: {str(e)}")
            return
        
        # Mostrar diálogo de progreso
        progress = QProgressDialog("Moviendo archivos...", "Cancelar", 0, len(selected_items), self)
        progress.setWindowTitle("Moviendo archivos")
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        
        # Mover cada archivo
        moved_count = 0
        for i, item in enumerate(selected_items):
            progress.setValue(i)
            
            full_path = item.data(0, Qt.UserRole)
            filename = item.text(0)
            
            # Ruta destino
            dest_path = os.path.join(new_folder_path, filename)
            
            # Mover
            try:
                shutil.move(full_path, dest_path)
                moved_count += 1
            except Exception as e:
                self.log_status(f"Error al mover {filename}: {str(e)}", logging.ERROR)
        
        # Completar
        progress.setValue(len(selected_items))
        self.log_status(f"Movidos {moved_count} archivos a {folder_name}")
        
        # Actualizar vista
        self.apply_batch_filters()

    # Métodos utilitarios
    def format_size(self, size_bytes):
        """Formatea un tamaño en bytes a formato legible"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

    def get_modification_date(self, path):
        """Obtiene la fecha de modificación de un archivo o carpeta"""
        try:
            mtime = os.path.getmtime(path)
            date = datetime.fromtimestamp(mtime)
            return date.strftime("%d/%m/%Y %H:%M")
        except:
            return ""

    # Métodos de limpieza
    def closeEvent(self, event):
        """Limpia los archivos temporales al cerrar la aplicación"""
        if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
                self.log_status("Archivos temporales eliminados", logging.INFO)
            except Exception as e:
                self.log_status(f"Error al eliminar archivos temporales: {str(e)}", logging.ERROR)
        
        event.accept()


# Iniciar la aplicación
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AbletonSampleManager()
    window.show()
    sys.exit(app.exec_())