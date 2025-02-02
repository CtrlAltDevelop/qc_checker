import asyncio
import lzma
import struct
import logging
from datetime import datetime
from pathlib import Path
from typing import Union

import aiohttp
import pandas as pd


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
TICK_URL = "{server}/{symbol}/{year}/{month:02d}/{day:02d}/{hour:02d}h_ticks.bi5"
BID_CANDLE_URL = "{server}/{symbol}/{year}/{month:02d}/{day:02d}/BID_candles_min_1.bi5"
ASK_CANDLE_URL = "{server}/{symbol}/{year}/{month:02d}/{day:02d}/ASK_candles_min_1.bi5"


class DukasData:
    def __init__(self, data_path: Union[str, Path]) -> None:
        self.data_path = Path(data_path)

        self.aggregation = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
        self.timeframe_map = {5: '5min', 15: '15min', 30: '30min', 60: '1h', 240: '4h', 1440: '1d'}

    @staticmethod
    async def _download_file_async(url: str, file_path: Path) -> bytes:
        """
        Asynchronously downloads a file from the given URL.
        If the file exists locally, its contents are returned immediately.
        Retries indefinitely on HTTP errors (403, 404, 500).
        """
        if file_path.exists() and file_path.is_file():
            logging.info(f"File '{file_path}' exists. Reading from disk.")
            return file_path.read_bytes()

        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    logging.info(f"Requesting URL: {url}")
                    async with session.get(url, headers=HEADER) as response:
                        if response.status == 200:
                            data = await response.read()
                            file_path.parent.mkdir(parents=True, exist_ok=True)
                            file_path.write_bytes(data)
                            logging.info("Download successful.")
                            return data
                        elif response.status in (403, 404, 500):
                            logging.warning(f"Error {response.status} received. Retrying in 3 seconds...")
                            await asyncio.sleep(3)
                        else:
                            logging.warning(f"Unexpected status code {response.status}. Retrying in 3 seconds...")
                            await asyncio.sleep(3)
                except Exception as e:
                    logging.error(f"Exception during download: {e}. Retrying in 3 seconds...")
                    await asyncio.sleep(3)

    async def _get_tick_data_async(self, symbol: str, year: int, month: int, day: int, hour: int) -> bytes:
        """
        Constructs the tick URL and downloads the tick data file asynchronously.
        The provided month is 1-indexed (e.g. January = 1) and is converted to 0-indexed.
        """
        # Dukascopy expects 0-indexed months
        url = TICK_URL.format(server=SERVER, symbol=symbol, year=year, month=month - 1, day=day, hour=hour)
        file_path = self.data_path / symbol / f"{year:04d}" / f"{month:02d}" / f"{day:02d}" / f"{hour:02d}h_ticks.bi5"
        return await self._download_file_async(url, file_path)

    async def _get_candle_data_async(self, symbol: str, year: int, month: int, day: int, source: str) -> bytes:
        """
        Constructs the candle URL and downloads the candle data file asynchronously.
        The provided month is 1-indexed and is converted to 0-indexed.
        Parameter:
            source (str): 'BID' or 'ASK'
        """
        candle_type = source.upper()
        date = dict(server=SERVER, symbol=symbol, year=year, month=month - 1, day=day)
        if candle_type == 'BID':
            url = BID_CANDLE_URL.format(**date)
            file_path = self.data_path / symbol / f"{year:04d}_{month:02d}_{day:02d}_bid_m1_candles.bi5"
        elif candle_type == 'ASK':
            url = ASK_CANDLE_URL.format(**date)
            file_path = self.data_path / symbol / f"{year:04d}_{month:02d}_{day:02d}_ask_m1_candles.bi5"
        else:
            raise ValueError("source must be either 'BID' or 'ASK'")
        return await self._download_file_async(url, file_path)

    @staticmethod
    def _decompress_data(data: bytes) -> bytes:
        """
        Attempts to decompress the data using lzma.
        If decompression fails, returns the original data.
        """
        try:
            decompressed = lzma.decompress(data)
            logging.info("LZMA decompression successful.")
            return decompressed
        except Exception as e:
            logging.warning(f"LZMA decompression failed: {e}. Using raw data.")
            return data

    @staticmethod
    def _get_contract_size(symbol: str) -> int:
        """
        Returns the contract size for the given symbol.
        (For now, always returns 100000; modify if necessary.)
        """
        return 100000

    def _parse_candle_data(self, symbol: str, data: bytes, year: int, month: int, day: int) -> pd.DataFrame:
        """
        Parses 24-byte candle records into a pandas DataFrame.
        Each record consists of:
          - timestamp (unsigned int; seconds offset from midnight)
          - open price (unsigned int; price * contract_size)
          - high price (unsigned int; price * contract_size)
          - low price (unsigned int; price * contract_size)
          - close price (unsigned int; price * contract_size)
          - volume (float; as stored)
        """
        candles = []
        record_size = 24
        total_records = len(data) // record_size
        size = self._get_contract_size(symbol)
        base_time = pd.Timestamp(year=year, month=month, day=day)
        for i in range(total_records):
            offset = i * record_size
            record = data[offset:offset + record_size]
            if len(record) < record_size:
                break
            try:
                ts, open_i, high_i, low_i, close_i, volume = struct.unpack('!IIIIIf', record)
                candles.append({
                    'timestamp': base_time + pd.to_timedelta(ts, unit='s'),
                    'open': open_i / size,
                    'high': high_i / size,
                    'low': low_i / size,
                    'close': close_i / size,
                    'volume': volume
                })
            except Exception as e:
                logging.error(f"Error parsing candle record {i}: {e}")
        return pd.DataFrame(candles)

    def _parse_tick_data(self, symbol: str, data: bytes, year: int, month: int, day: int, hour: int) -> pd.DataFrame:
        """
        Parses 20-byte tick records into a pandas DataFrame.
        Each record consists of:
          - timestamp offset in ms (unsigned int)
          - ask price (unsigned int; price * 100000)
          - bid price (unsigned int; price * 100000)
          - ask volume (unsigned int)
          - bid volume (unsigned int)
        A datetime column is created from the base hour plus the offset.
        The spread is calculated as (ask - bid) / contract size.
        """
        ticks = []
        record_size = 20
        total_records = len(data) // record_size
        size = self._get_contract_size(symbol)
        base_time = pd.Timestamp(year=year, month=month, day=day, hour=hour)
        for i in range(total_records):
            offset = i * record_size
            record = data[offset:offset + record_size]
            if len(record) < record_size:
                break
            try:
                ts_ms, ask_i, bid_i, ask_vol, bid_vol = struct.unpack('!IIIff', record)
                ticks.append({
                    'timestamp': base_time + pd.to_timedelta(ts_ms, unit='ms'),
                    'ask': ask_i / size,
                    'bid': bid_i / size,
                    'spread': (ask_i - bid_i) / size,
                    'ask_vol': ask_vol,
                    'bid_vol': bid_vol
                })
            except Exception as e:
                logging.error(f"Error parsing tick record {i}: {e}")
        return pd.DataFrame(ticks)

    def get_candle_data(self, symbol: str, dt: datetime, source: str = 'BID') -> pd.DataFrame:
        """
        Synchronous wrapper that downloads and parses candle data for the given symbol and datetime.
        Internally it calls the asynchronous method using asyncio.run.
        """
        return asyncio.run(self.get_candle_data_async(symbol, dt, source))

    async def get_candle_data_async(self, symbol: str, dt: datetime, source: str = 'BID') -> pd.DataFrame:
        """
        Asynchronously downloads, decompresses, and parses candle data for the given symbol and datetime.
        The source parameter can be 'BID' or 'ASK'.
        """
        raw_data = await self._get_candle_data_async(symbol, dt.year, dt.month, dt.day, source)
        decompressed = self._decompress_data(raw_data)
        return self._parse_candle_data(symbol, decompressed, dt.year, dt.month, dt.day)

    def get_tick_data(self, symbol: str, dt: datetime) -> pd.DataFrame:
        """
        Synchronous wrapper that downloads and parses tick data for the given symbol and datetime.
        Internally it calls the asynchronous method using asyncio.run.
        """
        return asyncio.run(self.get_tick_data_async(symbol, dt))

    async def get_tick_data_async(self, symbol: str, dt: datetime) -> pd.DataFrame:
        """
        Asynchronously downloads, decompresses, and parses tick data for the given symbol and datetime.
        The dt.hour value is used as the base hour for tick offsets.
        """
        raw_data = await self._get_tick_data_async(symbol, dt.year, dt.month, dt.day, dt.hour)
        decompressed = self._decompress_data(raw_data)
        return self._parse_tick_data(symbol, decompressed, dt.year, dt.month, dt.day, dt.hour)

    def get_candles(self, symbol: str, dt: datetime, timeframe: int = 1) -> pd.DataFrame:
        """
        Returns candle data for the given symbol and datetime at the requested timeframe.
        For '1m', the raw data is downloaded and for higher timeframes, 1-minute data is aggregated
        using pandas resample.
        Supported timeframes: 1, 5, 15, 30, 60, 240, 1440
        """
        df_1m = self.get_candle_data(symbol, dt, source='BID')
        if timeframe == 1:
            return df_1m

        df = df_1m.copy().set_index('timestamp').sort_index()

        if timeframe not in self.timeframe_map:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        return df.resample(self.timeframe_map[timeframe]).agg(self.aggregation).dropna().reset_index()
