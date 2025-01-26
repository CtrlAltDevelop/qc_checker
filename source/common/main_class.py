import sys
import logging
from contextlib import contextmanager
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime
from tkinter import Tk, filedialog
from typing import Optional, Iterable, Tuple


class MainClass:
    """
    Main application class that handles the core functionality.
    """

    base_path: Path

    def __init__(self, base_path: Path):
        """
        Initializes the Main class.
        """
        self.base_path = base_path
        self.__logs_dir = self.base_path / 'logs'
        self.__ensure_logs_directory__()
        self.__logger = None
        self.__setup_logging__()

    def __ensure_logs_directory__(self):
        """
        Ensures that the logs directory exists. Creates it if it does not.
        """
        try:
            self.__logs_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f'Failed to create logs directory at {self.__logs_dir}: {e}')
            sys.exit(1)

    @contextmanager
    def _tkinter_root(self):
        """Context manager to handle the Tkinter root window."""
        root = Tk()
        try:
            root.withdraw()
            yield root
        finally:
            root.destroy()

    def __setup_logging__(self):
        """
        Configures the logging settings for the application, focusing solely on error logging.
        Logs are stored in the designated logs directory with the current date in the filename.
        """

        # Create a custom logger
        self.__logger = logging.getLogger(__name__)
        self.__logger.setLevel(logging.ERROR)  # Capture only ERROR and CRITICAL logs

        # Formatter for logs
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        # Generate log file name with today's date
        today_str = datetime.now().strftime('%Y-%m-%d')
        error_log_filename = f'{today_str}.log'
        error_log_path = self.__logs_dir / error_log_filename

        # Error log handler with rotation
        error_handler = RotatingFileHandler(error_log_path, maxBytes=5 * 1024 * 1024, backupCount=5)
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)

        # Console handler for real-time error feedback
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.ERROR)
        console_handler.setFormatter(formatter)

        # Add handlers to the logger
        self.__logger.addHandler(error_handler)
        self.__logger.addHandler(console_handler)

    def __run__(self):
        """
        The main method where the core functionality of the application is implemented.
        To be overridden with actual logic.
        """
        pass

    def safe_run(self):
        """
        Executes the run method safely, handling any exceptions that occur.
        """
        start = datetime.now()
        try:
            self.__logger.debug('Application has started running.')
            self.__run__()
            self.__logger.debug('Application has finished running.')
        except Exception as e:
            self.__logger.exception(f'An unexpected error occurred: {e}')
            log_file = self.__logs_dir / f'{datetime.now().strftime('%Y-%m-%d')}.log'
            print(f'\nAn error has occurred. Please check "{log_file}" for more details.\n')
        finally:
            print(f'\nApplication has finished running at {datetime.now() - start}.')
            if hasattr(sys, '_MEIPASS'):
                input('Press Enter to exit.')

    def get_file_via_dialog(self, title: str, filetypes: Iterable[Tuple[str, str]], optional:bool = False)\
            -> Optional[Path]:
        """Open a file dialog to select a file.

        :param optional:
        :param title: Title of the dialog window.
        :param filetypes: List of file types for filtering.
        :return: Path to the selected file.
        :raises FileNotFoundError: If no file is selected.
        """
        logging.debug(f"Opening file dialog: {title}")
        with self._tkinter_root():
            file = filedialog.askopenfile(title=title, filetypes=filetypes, initialdir=self.base_path)
            if not file and not optional:
                logging.error(f"{title} not selected.")
                raise FileNotFoundError(f"{title} not selected.")
            if file:
                selected_path = Path(file.name)
                logging.debug(f"File selected: {selected_path}")
                return selected_path
            return None

    def get_folder_via_dialog(self, title: str) -> Path:
        """Open a folder dialog to select a folder.

        :param title: Title of the dialog window.
        :return: Path to the selected folder or None.
        """
        self.__logger.debug(f"Opening folder dialog: {title}")
        with self._tkinter_root():
            folder = filedialog.askdirectory(title=title, initialdir=self.base_path, mustexist=True)
            if not folder:
                logging.error(f"{title} not selected.")
                raise NotADirectoryError(f"{folder} is not a valid directory.")
            selected_path = Path(folder)
            self.__logger.debug(f"Folder selected: {selected_path}")
            return selected_path
