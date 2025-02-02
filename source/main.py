import time
import logging
import configparser
import datetime  # For timestamping the report.
import textwrap  # For wrapping long lines.
from collections import defaultdict
from pathlib import Path
from typing import Tuple, List, Dict

import pandas as pd
from tqdm import tqdm

from source.common.main_class import MainClass
from source.features.dukas_data import DukasData

# Define common timeframes as a constant.
TIMEFRAMES = [1, 5, 15, 30, 60, 240, 1440]
WEEKEND_CANDLE = {1: 120, 5: 24, 15: 8, 30: 4, 60: 2, 240: 1, 1440: 1}


class QCChecker(MainClass):
    """
    A class to analyze trade spreads, check stop loss hits, and generate trade reports.
    """
    def __init__(self, base_path: Path, debug: bool = True) -> None:
        """
        Initialize the QCChecker instance.

        Reads configuration settings from settings.ini.

        :param base_path: Base directory path.
        :param debug: Flag to enable debug mode.
        """
        super().__init__(base_path)
        self.debug: bool = debug
        self.data_path = self.base_path / "data"
        self.result_path = self.base_path / "results"
        self.result_path.mkdir(parents=True, exist_ok=True)

        # class implement
        self.dukas = DukasData(self.result_path)

        # Read INI configuration
        self.config = configparser.ConfigParser()
        self.config.read(self.base_path / 'settings.ini')

        # Read configuration values from INI
        self.is_gmt = self.config.getboolean("Files", "TimeZoneGMT")
        self.default_mt4 = Path(self.config.get("Files", "MT4"))
        self.default_mt5 = Path(self.config.get("Files", "MT5"))
        self.multiplier = self.config.getfloat("ATR", "Multiplier")
        self.save_after_update = self.config.getboolean("Volume", "SaveAfterUpdate")

        self.red_flags: Dict[Path, List[str]] = defaultdict(list)
        self.spread: Dict[str, float] = {}

    def _get_folders_via_dialog(self) -> Tuple[Path, Path]:
        """
        Retrieves paths for MT4 and MT5 folders.
        Uses default paths if they exist; otherwise, prompts the user to select folders via a dialog.

        :return: A tuple containing paths for the MT4 and MT5 folders.
        """
        def get_folder(default_folder: Path, prompt_msg: str) -> Path:
            if default_folder.exists():
                return default_folder
            logging.info(f"Default folder not found: {default_folder}. Prompting user.")
            folder = self.get_folder_via_dialog(prompt_msg)
            if folder is None:
                raise FileNotFoundError(f"Folder selection canceled for: {prompt_msg}")
            return folder

        mt4_folder = get_folder(self.default_mt4, 'Select folder to analyze Candle Data-MT4')
        mt5_folder = get_folder(self.default_mt5, 'Select folder to analyze Candle Data-MT5')

        logging.info(f"Selected folders: MT4: {mt4_folder}, MT5: {mt5_folder}")
        print('Program will use the following folders:')
        print(f'\tMeta 4 Folder: {mt4_folder}')
        print(f'\tMeta 5 Folder: {mt5_folder}')
        while True:
            answer = input('Do you wish to continue? (Y/n): ').strip().lower()
            if answer in ('y', 'yes', ''):
                break
            elif answer in ('n', 'no'):
                logging.info("User opted to reselect folders.")
                mt4_folder = self.get_folder_via_dialog('Select folder to analyze Candle Data-MT4')
                if mt4_folder is None:
                    raise FileNotFoundError("MT4 folder selection was canceled.")
                mt5_folder = self.get_folder_via_dialog('Select folder to analyze Candle Data-MT5')
                if mt5_folder is None:
                    raise FileNotFoundError("MT5 folder selection was canceled.")
                break
            else:
                print("Invalid input. Please enter 'y' or 'n'.")
        return mt4_folder, mt5_folder

    def _load_spread(self) -> None:
        """
        Loads spread information from Excel files located in the Spread_Files folder.
        """
        for file in (self.data_path / "Spread_Files").glob('*.xlsx'):
            try:
                df = pd.read_excel(file, skiprows=1)
                if 'Normal spread(Point)' in df.columns and not df.empty:
                    self.spread[file.stem] = df['Normal spread(Point)'].iloc[0]
                else:
                    logging.warning(f"Spread column missing or empty in {file}")
            except Exception as e:
                logging.error(f"Error loading spread from {file}: {e}")

    def __run__(self):
        """
        Main method to run the QC analysis.
        Loads spread data, processes MT4 and MT5 folders, and reports/saves any found issues.
        """
        logging.info('Data Analysis Started.')
        self._load_spread()

        mt4_folder, mt5_folder = (self.default_mt4, self.default_mt5) if self.debug else self._get_folders_via_dialog()

        # Process MT4 data
        self._process_folder(mt4_folder, is_mt5=False)
        time.sleep(0.1)
        # Process MT5 data
        self._process_folder(mt5_folder, is_mt5=True)
        time.sleep(0.1)

        logging.info('Data Analysis complete.')
        # Optionally, print combined red flags.
        for path, flags in self.red_flags.items():
            if flags:
                print(f'ERRORS: {path}')
                for msg in flags:
                    print(f'\t- {msg}')

    def _process_folder(self, folder: Path, is_mt5: bool) -> None:
        """
        Processes a folder containing symbol subdirectories.

        :param folder: The folder path (MT4 or MT5).
        :param is_mt5: Flag to indicate if the folder is for MT5 data.
        """
        file_desc = "MT 5" if is_mt5 else "MT 4"
        columns = (
            ['time', 'open', 'high', 'low', 'close', 'tick volume', 'volume', 'spread']
            if is_mt5 else ['time', 'open', 'high', 'low', 'close', 'volume']
        )
        for symbol_path in tqdm([d for d in folder.iterdir() if d.is_dir()], desc=f"{file_desc}: {folder.name}"):
            data_frames = self._read_symbol_folder_data(symbol_path, columns)
            for timeframe, df in data_frames.items():
                self._single_file_analysis(symbol_path, df, timeframe)
            self._multi_file_analysis(symbol_path, data_frames)
            # Save red flags for this symbol folder after processing.
            self._save_red_flags_for_symbol(symbol_path)

    def _read_symbol_folder_data(self, folder: Path, columns: List[str]) -> Dict[int, pd.DataFrame]:
        """
        Reads and validates candle data files from a symbol folder.

        :param folder: Path to the symbol folder.
        :param columns: Expected column names.
        :return: Dictionary mapping timeframe to DataFrame.
        """
        result: Dict[int, pd.DataFrame] = {}
        valid_files = set()
        parts = folder.name.split('-', 1)

        for t in TIMEFRAMES:
            file_name = f'{parts[0]}-{t}-{parts[1]}.csv' if len(parts) > 1 else f'{parts[0]}-{t}.csv'
            valid_files.add(file_name)
            candle_path = folder / file_name
            if not candle_path.exists():
                self.red_flags[folder].append(f"Missing Candle Data file: {candle_path}")
                continue

            try:
                df = pd.read_csv(candle_path, header=None)
                if len(df.columns) != len(columns):
                    self.red_flags[candle_path].append(f"Expected {len(columns)} columns, found {len(df.columns)}")
                df.columns = columns[:len(df.columns)]
                df['time'] = \
                    pd.to_datetime(df['time'], format="%d.%m.%Y %H:%M:%S.%f", errors='coerce', dayfirst=True)
                invalid_indices = df.index[df['time'].isna()].tolist()
                if invalid_indices:
                    self.red_flags[candle_path].append(f"Invalid time format in rows: {invalid_indices}")
                result[t] = df.sort_values(by='time')
            except Exception as e:
                self.red_flags[folder].append(f"Failed to read file {candle_path}: {e}")

        # Report any extra unexpected files.
        all_files = {f.name for f in folder.iterdir() if f.is_file()}
        extra_files = all_files - valid_files
        if extra_files:
            for extra_file in extra_files:
                self.red_flags[folder].append(f"Unexpected file found: {extra_file}")
        return result

    def _single_file_analysis(self, path: Path, df: pd.DataFrame, timeframe: int) -> None:
        """
        Performs analysis on a single timeframe file.

        :param path: Path to the symbol folder.
        :param df: DataFrame containing candle data.
        :param timeframe: Timeframe of the data.
        """
        df = df.copy()

        # Check for empty rows and columns.
        empty_rows = df.index[df.isna().all(axis=1)].tolist()
        if empty_rows:
            self.red_flags[path].append(f"TF: {timeframe}, Empty rows at indices: {empty_rows}")
        empty_cols = df.columns[df.isna().all()].tolist()
        if empty_cols:
            self.red_flags[path].append(f"TF: {timeframe}, Empty columns at indices: {empty_cols}")

        # Check for duplicate rows.
        duplicate_rows = df.index[df.duplicated()].tolist()
        if duplicate_rows:
            self.red_flags[path].append(f"TF: {timeframe}, Duplicate rows at indices: {duplicate_rows}")

        # Validate high and low values relative to open, close.
        invalid_candles = df.index[
            (df['high'] != df[['open', 'high', 'low', 'close']].max(axis=1)) |
            (df['low'] != df[['open', 'high', 'low', 'close']].min(axis=1))
        ].tolist()
        if invalid_candles:
            self.red_flags[path].append(f"TF: {timeframe}, Incorrect candle data at indices: {invalid_candles}")

        # Check and update volume (for non 1-minute timeframes).
        if timeframe != 1:
            original_volume = df['volume'].copy()
            df['volume'] = df['volume'].replace(1, 2)
            if not original_volume.equals(df['volume']):
                self.red_flags[path].append(f"TF: {timeframe}, Volume values updated.")
                if self.save_after_update:
                    df.to_csv(path, header=False, index=False)
                    self.red_flags[path].append(f"Saved changes to {path}")

        # Analyze gaps and calculate volatility metrics.
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
        gap_indices = df.index[(df['Diff'] > df['ATR_Multi']) & (df['time_diff'] <= 15)].tolist()
        if gap_indices:
            self.red_flags[path].append(f"TF: {timeframe}, Unusual gap detected at indices: {gap_indices}")

        # Check weekend candles.
        df['day_of_week'] = df['time'].dt.dayofweek
        weekend_data = df[df['day_of_week'].isin([5, 6])]
        max_weekend = WEEKEND_CANDLE.get(timeframe, 0) if self.is_gmt else 0
        if len(weekend_data) > max_weekend:
            self.red_flags[path].append(
                f"TF: {timeframe}, Weekend data count {len(weekend_data)} exceeds maximum {max_weekend}. "
                f"Indices: {weekend_data.index.tolist()}"
            )

        # Validate spread if applicable.
        if 'spread' in df.columns:
            symbol_name = path.stem.split('-')[0]
            valid_spread = self.spread.get(symbol_name)
            if valid_spread is None:
                self.red_flags[path].append(f"TF: {timeframe}, Spread not found for symbol {symbol_name}")
            else:
                wrong_spread_idx = df.index[df['spread'] != valid_spread].tolist()
                if wrong_spread_idx:
                    self.red_flags[path].append(
                        f"TF: {timeframe}, Incorrect spread (expected {valid_spread}) at indices: {wrong_spread_idx}"
                    )

    def _multi_file_analysis(self, path: Path, dfs: Dict[int, pd.DataFrame]) -> None:
        """
        Performs cross-file analysis to check for consistency in start and end dates across timeframes.

        :param path: Path to the symbol folder.
        :param dfs: Dictionary of DataFrames keyed by timeframe.
        """
        start_times = [(tf, df['time'].iloc[0].date()) for tf, df in dfs.items() if not df.empty]
        if len({date for _, date in start_times}) > 1:
            self.red_flags[path].append(f"Inconsistent start dates across timeframes: {start_times}")

        end_times = [(tf, df['time'].iloc[-1].date()) for tf, df in dfs.items() if not df.empty]
        if len({date for _, date in end_times}) > 1:
            self.red_flags[path].append(f"Inconsistent end dates across timeframes: {end_times}")

    def _validate_data_by_server(self, df: pd.DataFrame, tf: int) -> None:
        # Create helper columns for date-only and grouping by month
        df['date_only'] = df['time'].dt.date
        df['year_month'] = df['time'].dt.to_period('M')

        result = {}

        # Process each month group
        for period, group in df.groupby('year_month'):
            # Get unique days (as Python date objects) in sorted order using NumPy
            unique_days = np.array(sorted(set(group['date_only'])))
            if unique_days.size == 0:
                continue

            # Convert unique days to a pandas DatetimeIndex to easily compute weekdays
            unique_days_dt = pd.to_datetime(unique_days)
            # Build a boolean mask: weekdays are those with weekday() 0 (Monday) to 4 (Friday)
            is_weekday = unique_days_dt.weekday < 5
            weekdays = unique_days[is_weekday]

            # Select first and last trading days in the month from the unique days
            first_date = unique_days[0]
            last_date = unique_days[-1]

            # From the weekdays list, exclude the first and last dates (if they are weekdays) for random selection
            if weekdays.size > 0:
                candidate_mask = (weekdays != first_date) & (weekdays != last_date)
                candidate_dates = weekdays[candidate_mask]
            else:
                candidate_dates = np.array([], dtype=unique_days.dtype)

            # Randomly sample 3 candidate dates if available, otherwise take all candidates
            if candidate_dates.size >= 3:
                random_dates = np.random.choice(candidate_dates, 3, replace=False)
            else:
                random_dates = candidate_dates

            # Combine first, last, and the random selected days and sort them
            selected_dates = np.sort(np.unique(np.concatenate(([first_date, last_date], random_dates))))

            # For each selected day, filter the trades and drop the helper columns before storing in result
            for sel in selected_dates:
                # Format key as 'YYYY-MM-DD'
                key = pd.to_datetime(sel).strftime('%Y-%m-%d')
                # Filter rows where the date_only column equals the selected date
                mask = df['date_only'] == sel
                trades = df.loc[mask].copy()
                trades.drop(columns=['year_month', 'date_only'], inplace=True)
                result[key] = trades

        # Print the result dictionary where each key is a selected date and its value is the corresponding trades DataFrame
        for _date, _df in result.items():
            print(_date, len(_df))

    def _save_red_flags_for_symbol(self, symbol_path: Path) -> None:
        """
        Saves all red flags related to the given symbol folder to a text file.
        The file is saved in the results folder with the name <symbol>_red_flags.txt.
        The report includes a header with generation timestamp, summary counts, and detailed sections for each file.
        Long lines are wrapped for readability.

        :param symbol_path: The path of the symbol folder.
        """
        messages = []
        total_issues = 0
        details = []
        # Gather red flags for files that are either the symbol folder or within it.
        for path, flags in self.red_flags.items():
            try:
                if path == symbol_path or symbol_path in path.parents:
                    if flags:
                        total_issues += len(flags)
                        # Format the file header.
                        file_report = f"-----\nFile: {path}\n-----\n"
                        # Wrap each flag message to 120 characters.
                        wrapped_flags = "\n".join(f"  • {textwrap.fill(flag, width=120, subsequent_indent='    ')}"
                                                  for flag in flags)
                        file_report += wrapped_flags
                        details.append(file_report)
            except Exception as e:
                logging.error(f"Error processing red flags for {symbol_path}: {e}")

        # Prepare a header with additional details.
        header = "\n".join(["=" * 50, f"Red Flag Report for Symbol: {symbol_path.name}",
                            f"Report generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                            f"Total issues found: {total_issues}", "=" * 50, ""])
        if details:
            (self.result_path / symbol_path.parent.name).mkdir(exist_ok=True)
            output_file = self.result_path / symbol_path.parent.name /f"{symbol_path.name}_red_flags.txt"
            with open(output_file, "w") as f:
                f.write(header + "\n\n" + "\n\n".join(details))
            logging.info(f"Saved red flags for {symbol_path} to {output_file}")
