import time
import logging
import configparser
from collections import defaultdict
from pathlib import Path
from typing import Tuple, List, Dict, Hashable

import pandas as pd
from tqdm import tqdm

from source.common.main_class import MainClass


class QCChecker(MainClass):
    """
    A class to analyze trade spreads, check stop loss hits, and generate trade reports.
    """
    red_flags: Dict[Path, List[str]] =  defaultdict(lambda: [])
    weekend_candle = {1: 120, 5: 24, 15: 8, 30: 4, 60: 2, 240: 1, 1440: 1}
    default_mt4 = Path('Z:/(Sharing Technical Team)/Symbols Data-DS/Candle Data-DS/Candle Data-MT4-DS/')
    default_mt5 = Path('Z:/(Sharing Technical Team)/Symbols Data-DS/Candle Data-DS/Candle Data-MT5-DS/')
    config = configparser.ConfigParser()
    multiplier = 3
    is_gmt = False

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
        self.config.read(self.base_path / 'settings.ini')

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
            columns = ['time', 'open', 'high', 'low', 'close', 'volume']
            data_frames = self._read_symbol_folder_data(symbol_path, columns)
            for time_frame, df in data_frames.items():
                self._single_file_analysis(symbol_path, df, time_frame)
            self._multi_file_analysis(symbol_path, data_frames)
            break

        # time.sleep(.1)
        # for symbol_path in tqdm([d for d in mt5_folder.iterdir() if d.is_dir()], desc=f"MT 5: {mt4_folder.name}"):
        #     columns = ['time', 'open', 'high', 'low', 'close', 'tick volume', 'volume', 'spread']
        #     data_frames = self._read_symbol_folder_data(symbol_path, columns)
        #     for time_frame, df in data_frames.items():
        #         self._single_file_analysis(symbol_path, df, time_frame)
        #     self._multi_file_analysis(symbol_path, data_frames)
        #     break

        time.sleep(.1)
        logging.info('Data Analysis complete.')
        for path, flags in self.red_flags.items():
            if not flags:
                continue
            print(f'ERRORS: {path}')
            for each in flags:
                print(f'\t- {each}')

    def _read_symbol_folder_data(self, folder: Path, columns: List[str]) ->  Dict[int, pd.DataFrame]:
        def find_invalid_time_rows(time_series: pd.Series, date_format: str = "%d.%m.%Y %H:%M:%S.%f") -> List[Hashable]:
            """Find indices of rows with invalid time formats."""
            _invalid_indices = []
            for idx, value in time_series.items():
                try:
                    pd.to_datetime(value, format=date_format, dayfirst=True)
                except ValueError:
                    _invalid_indices.append(idx)
            return _invalid_indices

        result = {}
        valid_files = set()
        parts = folder.name.split('-', 1)

        # Generate valid file names based on the expected pattern
        for t in tqdm([1, 5, 15, 30, 60, 240, 1440], desc='Read Candle Data File'):
            if len(parts) > 1:
                file_name = f'{parts[0]}-{t}-{parts[1]}.csv'
            else:
                file_name = f'{parts[0]}-{t}.csv'
            valid_files.add(file_name)
            candle_path = folder / file_name
            if not candle_path.exists():
                self.red_flags[folder].append(f'Candle Data is missing: {candle_path}')
            else:
                try:
                    df = pd.read_csv(candle_path, header=None)
                    # Validate the header of the DataFrame
                    try:
                        df.columns = columns
                    except ValueError as e:
                        self.red_flags[candle_path].append(f"Missing required columns: {e}")

                    # Validate the time column for correct date format.
                    try:
                        df['time'] = pd.to_datetime(df['time'], format="%d.%m.%Y %H:%M:%S.%f", dayfirst=True)
                    except ValueError:
                        invalid_indices = find_invalid_time_rows(df['time'])
                        self.red_flags[candle_path].append(f"Rows with invalid time format: {invalid_indices}")

                    result[t] = df.sort_values(by='time')

                except Exception as e:
                    self.red_flags[folder].append(f"Failed to Read file: {e}")

        # Check for extra files
        all_files = {f.name for f in folder.iterdir() if f.is_file()}
        extra_files = all_files - valid_files
        if extra_files:
            for extra_file in extra_files:
                self.red_flags[folder].append(f'Unexpected file found: {extra_file}')
        return result

    def _single_file_analysis(self, path: Path, df: pd.DataFrame, time_frame: int):
        df = df.copy()

        # Find the indices of empty rows
        empty_row_indices = df[df.isnull().all(axis=1)].index
        if not empty_row_indices.empty:
            self.red_flags[path].append(f"Indices of empty rows: {list(empty_row_indices)}")

        # Find the indices of empty columns
        empty_column_indices = df.columns[df.isnull().all()]
        if len(empty_column_indices) > 0:
            self.red_flags[path].append(f"Indices of empty columns: {list(empty_column_indices)}")

        # Find the indices of duplicate rows
        duplicate_indices = df[df.duplicated()].index
        if not duplicate_indices.empty:
            self.red_flags[path].append(f"Indices of duplicate rows: {list(duplicate_indices)}")

        # Check High and Low value
        high_is_max = (df['high'] != df[['open', 'high', 'low', 'close']].max(axis=1))
        low_is_min = (df['low'] != df[['open', 'high', 'low', 'close']].min(axis=1))
        for idx in sorted(set(high_is_max[high_is_max].index) | set(low_is_min[low_is_min].index)):
            self.red_flags[path].append(f"Wrong Candle Data in Index {idx}")

        # check volume
        if time_frame != 1:
            last_volume = df['volume'].copy()
            df['volume'] = df['volume'].replace(1, 2)
            if not (last_volume == df['volume']).all():
                self.red_flags[path].append(f'Volumes updated, Save to {path}')
                df.to_csv(path, header=False, index=False)

        # check the gap between candle
        df['prev_close'] = df['close'].shift(1)
        df['prev_time'] = df['time'].shift(1)
        df['time_diff'] = (df['time'] - df['prev_time']).dt.total_seconds() / 60
        df['TR1'] = df['high'] - df['low']
        df['TR2'] = (df['high'] - df['prev_close']).abs()
        df['TR3'] = (df['low'] - df['prev_close']).abs()

        df['TR'] = df[['TR1', 'TR2', 'TR3']].max(axis=1)
        df['ATR'] = df['TR'].rolling(window=14).mean()
        df['ATR_Multi'] = df['ATR'] * self.multiplier
        df['Diff'] = abs(df['prev_close'] - df['open'])
        df.drop(columns=['TR', 'TR1', 'TR2', 'TR3'], inplace=True)

        big_gap = df[(df['Diff'] > df['ATR_Multi']) & (df['time_diff'] <= 15)]
        if not big_gap.empty:
            self.red_flags[path].append(f'Index with Unnormal Gap: {big_gap.index}')

        # check weekend candle
        df['day_of_week'] = df['time'].dt.dayofweek
        weekend_data = df[(df['day_of_week'] == 5) | (df['day_of_week'] == 6)]
        if self.is_gmt and len(weekend_data) > self.weekend_candle.get(time_frame):
            self.red_flags[path].append(f"Data exists for Saturdays and/or Sundays. Count: {len(weekend_data)}, " 
                                        f"Max: {self.weekend_candle.get(time_frame)}, Details: {weekend_data.index}")
        elif not self.is_gmt and not weekend_data.empty:
            self.red_flags[path].append(f"Data exists for Saturdays and/or Sundays. Count: {len(weekend_data)}, " 
                                        f"Max: 0, Details: {weekend_data.index}")

    def _multi_file_analysis(self, path: Path, dfs: Dict[int, pd.DataFrame]):
        # Check start times
        start_times = [(i, df['time'].iloc[0].date()) for i, df in dfs.items()]
        if len(set(t for _, t in start_times)) != 1:
            self.red_flags[path].append(f"TimeFrames Data do not start at the same datetime. Details: {start_times}")

        # Check end times
        end_times = [(i, df['time'].iloc[-1].date()) for i, df in dfs.items()]
        if len(set(t for _, t in end_times)) != 1:
            self.red_flags[path].append(f"TimeFrames Data do not end at the same datetime. Details: {end_times}")
