import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Tuple, List, Dict

import pandas as pd
from tqdm import tqdm

from source.common.main_class import MainClass


class QCChecker(MainClass):
    """
    A class to analyze trade spreads, check stop loss hits, and generate trade reports.
    """
    red_flags: Dict[Path, List[str]] =  defaultdict(lambda: [])
    default_mt4 = Path('Z:/(Sharing Technical Team)/Symbols Data-DS/Candle Data-DS/Candle Data-MT4-DS/')
    default_mt5 = Path('Z:/(Sharing Technical Team)/Symbols Data-DS/Candle Data-DS/Candle Data-MT5-DS/')

    def __init__(self, base_path: Path, debug: bool = True) -> None:
        """
        Initialize the TradeSpreadAnalyze instance.

        :param base_path: Base directory path.
        :param debug: Flag to enable debug mode.
        """
        super().__init__(base_path)
        self.debug: bool = debug
        self.result_path = self.base_path / "results"
        self.result_path.mkdir(parents=True, exist_ok=True)

    def _get_folders_via_dialog(self) -> Tuple[Path, Path]:
        """
        Retrieves paths for MT4 and MT5 folders.
        Uses default paths if they exist; otherwise, prompts the user to select folders via dialog.

        :return: A tuple containing paths for the MT4 and MT5 folders.
        """

        # Check if default MT4 folder exists
        mt4_folder = self.default_mt4 if self.default_mt4.exists() else None
        if not mt4_folder:
            logging.info(f"Default MT4 folder not found. Prompting user to select folder.")
            mt4_folder = self.get_folder_via_dialog('Select folder to analyze Candle Data-MT4')
            if not mt4_folder:
                raise FileNotFoundError("MT4 folder selection was canceled.")

        # Check if default MT5 folder exists
        mt5_folder = self.default_mt5 if self.default_mt5.exists() else None
        if not mt5_folder:
            logging.info(f"Default MT5 folder not found. Prompting user to select folder.")
            mt5_folder = self.get_folder_via_dialog('Select folder to analyze Candle Data-MT5')
            if not mt5_folder:
                raise FileNotFoundError("MT5 folder selection was canceled.")

        # Confirm folders with the user
        print('Program will use the following folders:')
        print(f'\tMeta 4 Folder: {mt4_folder}')
        print(f'\tMeta 5 Folder: {mt5_folder}')
        while True:
            answer = input('Do you wish to continue? (Y/n): ').strip().lower()
            if answer == 'y' or answer == 'yes' or answer == '':
                break
            elif answer == 'n' or answer == 'no':
                logging.info("User opted to reselect folders.")
                mt4_folder = self.get_folder_via_dialog('Select folder to analyze Candle Data-MT4')
                if not mt4_folder:
                    raise FileNotFoundError("MT4 folder selection was canceled.")
                mt5_folder = self.get_folder_via_dialog('Select folder to analyze Candle Data-MT5')
                if not mt5_folder:
                    raise FileNotFoundError("MT5 folder selection was canceled.")
                break
            else:
                print("Invalid input. Please enter 'y' or 'n'.")

        logging.info(f"Selected folders: MT4: {mt4_folder}, MT5: {mt5_folder}")
        return mt4_folder, mt5_folder

    def __run__(self):
        """Initialize data by loading symbol, spreads, candles, and report."""
        logging.info('Data Analysis Started.')
        mt4_folder, mt5_folder = self.default_mt4, self.default_mt5
        if not self.debug:
            mt4_folder, mt5_folder = self._get_folders_via_dialog()
        for symbol_path in tqdm([d for d in mt4_folder.iterdir() if d.is_dir()], desc=f"MT 4: {mt4_folder.name}"):
            pass

        for symbol_path in tqdm([d for d in mt5_folder.iterdir() if d.is_dir()], desc=f"MT 5: {mt4_folder.name}"):
            pass

        time.sleep(.1)
        logging.info('Data Analysis complete.')
        for path, flags in self.red_flags.items():
            if not flags:
                continue
            print(f'ERRORS: {path}')
            for each in flags:
                print(f'\t- {each}')
