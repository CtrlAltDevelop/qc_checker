import asyncio
import lzma
import struct
from datetime import datetime
from pathlib import Path
import aiohttp
import pandas as pd


class DukasData:
    HEADER = {
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin': 'https://freeserv.dukascopy.com',
        'Priority': 'u=1, i',
        'Referer': 'https://freeserv.dukascopy.com/',
        'Sec-Ch-Ua': 'https://freeserv.dukascopy.com/',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': 'Windows',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/132.0.0.0 Safari/537.36'
        )
    }
    SERVER = 'https://www.dukascopy.com/datafeed'
    TICK_URL = "{server}/{currency}/{year}/{month:02d}/{day:02d}/{hour:02d}h_ticks.bi5"
    BID_CANDLE_URL = "{server}/{currency}/{year}/{month:02d}/{day:02d}/BID_candles_min_1.bi5"
    ASK_CANDLE_URL = "{server}/{currency}/{year}/{month:02d}/{day:02d}/ASK_candles_min_1.bi5"

    def __init__(self, data_path: Path) -> None:
        self.data_path = data_path

    @classmethod
    async def _download_file_async(cls, url: str, file_path: Path) -> bytes:
        """
        Asynchronously downloads a file from the provided URL using aiohttp.
        If the file already exists locally, it is read and returned.
        Retries indefinitely on HTTP 403, 404, or 500 status codes.
        """
        if file_path.exists() and file_path.is_file():
            print(f"File '{file_path}' exists. Reading from disk.")
            with open(file_path, 'rb') as f:
                return f.read()

        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    print(f"Requesting URL: {url}")
                    async with session.get(url, headers=cls.HEADER) as response:
                        if response.status == 200:
                            data = await response.read()
                            with open(file_path, 'wb') as f:
                                f.write(data)
                            print("Download successful.")
                            return data
                        elif response.status in (403, 404, 500):
                            print(f"Error {response.status} received. Retrying in 5 seconds...")
                            await asyncio.sleep(3)
                        else:
                            print(f"Unexpected status code {response.status}. Retrying in 5 seconds...")
                            await asyncio.sleep(3)
                except Exception as e:
                    print(f"Exception during download: {e}. Retrying in 5 seconds...")
                    await asyncio.sleep(3)

    async def _get_tick_data_async(self, currency: str, year: int, month: int, day: int, hour: int) -> bytes:
        """
        Constructs the tick URL, downloads the tick data file asynchronously,
        and returns the raw binary content.
        The provided month is 1-indexed (1 for January) and is converted to 0-indexed for the URL.
        """
        url = self.TICK_URL.format(currency=currency, year=year, month=month - 1, day=day, hour=hour)
        file_path = self.data_path / currency / f'{year:04d}' / f'{month:02d}' /f'{day:02d}' / f'{hour:02d}h_ticks.bi5'
        return await self._download_file_async(url, file_path)

    async def _get_candle_data_async(self, currency: str, year: int, month: int, day: int, source: str) -> bytes:
        """
        Constructs the candle URL, downloads the candle data file asynchronously,
        and returns the raw binary content.
        The provided month is 1-indexed (1 for January) and is converted to 0-indexed for the URL.

        Parameters:
            source (str): 'BID' or 'ASK'. Defaults to 'BID'.
        """
        candle_type = source.upper()
        date = dict(currency=currency, year=year, month=month - 1, day=day)
        if candle_type == 'BID':
            url = self.BID_CANDLE_URL.format(**date)
            file_path = self.data_path / currency / f'{year:04d}_{month:02d}_{day:02d}_bid_m1_candles.bi5'
        elif candle_type == 'ASK':
            url = self.ASK_CANDLE_URL.format(**date)
            file_path = self.data_path / currency / f'{year:04d}_{month:02d}_{day:02d}_ask_m1_candles.bi5'
        else:
            raise ValueError("candle_type must be either 'BID' or 'ASK'")
        return await self._download_file_async(url, file_path)

    @staticmethod
    def _decompress_data(data: bytes) -> bytes:
        """
        Attempts to decompress the data using lzma.
        If lzma decompression fails, returns the data as is.
        """
        try:
            decompressed = lzma.decompress(data)
            print("LZMA decompression successful.")
            return decompressed
        except Exception as e:
            print(f"LZMA decompression failed: {e}. Using raw data.")
            return data

    @staticmethod
    def _get_contract_size(symbol:str) -> int:
        # read json file and get size with symbol key
        return 100000

    def _parse_candle_data(self, symbol: str, data: bytes, year: int, month: int, day: int) -> pd.DataFrame:
        """
        Parses decompressed candle data.
        Assumes each candle record is 24 bytes, stored as six values:
          - 4 bytes unsigned int: timestamp (seconds offset from midnight)
          - 4 bytes unsigned int: open price (price * 100000)
          - 4 bytes unsigned int: high price (price * 100000)
          - 4 bytes unsigned int: low price (price * 100000)
          - 4 bytes unsigned int: close price (price * 100000)
          - 4 bytes float: volume
        Converts the price values to floats by dividing by 100000.
        If base_year, base_month, and base_day are provided, a datetime column is created by
        adding the timestamp (in seconds) to the base date.
        Returns a pandas DataFrame with the parsed records.
        """

        candles = []
        record_size = 24  # 6 x 4 bytes each
        total_records = len(data) // record_size
        # print(f"Total candle records found: {total_records}")
        size = self._get_contract_size(symbol)
        base_time = pd.Timestamp(year=year, month=month, day=day)
        for i in range(total_records):
            offset = i * record_size
            record = data[offset:offset + record_size]
            if len(record) < record_size:
                break
            try:
                ts, open_i, high_i, low_i, close_i, volume = struct.unpack('!IIIIIf', record)
                candles.append({'timestamp': base_time + pd.to_timedelta(ts, unit='s'), 'open': open_i / size,
                                'high': high_i / size, 'low': low_i / size, 'close': close_i / size, 'volume': volume})
            except Exception as e:
                print(f"Error parsing candle record {i}: {e}")
        return pd.DataFrame(candles)

    def _parse_tick_data(self, symbol: str, data: bytes, year: int, month: int, day: int, hour: int) -> pd.DataFrame:
        """
        Parses tick data.
        Assumes each tick record is 20 bytes, stored as five unsigned integers:
          - 4 bytes unsigned int: timestamp offset in milliseconds (from the beginning of the hour)
          - 4 bytes unsigned int: ask price (price * 100000)
          - 4 bytes unsigned int: bid price (price * 100000)
          - 4 bytes unsigned int: ask volume
          - 4 bytes unsigned int: bid volume
        The ask and bid prices are converted to floats by dividing by 100000.0.
        A datetime column is created by adding the millisecond offset to the base hour’s timestamp.
        Additionally, a new column 'spread' is calculated as (ask - bid).
        Returns a pandas DataFrame with the parsed tick records.
        """
        ticks = []
        record_size = 20  # 5 x 4 bytes each
        total_records = len(data) // record_size
        # print(f"Total tick records found: {total_records}")
        size = self._get_contract_size(symbol)
        base_time = pd.Timestamp(year=year, month=month, day=day, hour=hour)
        for i in range(total_records):
            offset = i * record_size
            record = data[offset:offset + record_size]
            if len(record) < record_size:
                break
            try:
                ts_ms, ask_i, bid_i, ask_vol, bid_vol = struct.unpack('!IIIff', record)
                ticks.append({'timestamp': base_time + pd.to_timedelta(ts_ms, unit='ms'), 'ask': ask_i / size,
                              'bid': bid_i / size, 'spread': ask_i - bid_i, 'ask_vol': ask_vol, 'bid_vol': bid_vol})
            except Exception as e:
                print(f"Error parsing tick record {i}: {e}")
        return pd.DataFrame(ticks)

    async def get_candle_data(self, symbol: str, time: datetime, source: str = 'BID') -> pd.DataFrame:
        raw_data = await self._get_candle_data_async(symbol, time.year, time.month, time.day, source)
        decompressed = self._decompress_data(raw_data)
        return self._parse_candle_data(symbol, decompressed, time.year, time.month, time.day)

    async def get_tick_data(self, symbol: str, time: datetime) -> pd.DataFrame:
        raw_data = await self._get_tick_data_async(symbol, time.year, time.month, time.day, time.hour)
        decompressed = self._decompress_data(raw_data)
        return self._parse_tick_data(symbol, decompressed, time.year, time.month, time.day, time.hour)
