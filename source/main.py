from pathlib import Path

from source.common.main_class import MainClass


class QCChecker(MainClass):
    """
    A class to analyze trade spreads, check stop loss hits, and generate trade reports.
    """

    def __init__(self, base_path: Path, debug: bool = False) -> None:
        """
        Initialize the TradeSpreadAnalyze instance.

        :param base_path: Base directory path.
        :param debug: Flag to enable debug mode.
        """
        super().__init__(base_path)
        self.debug: bool = debug
        self.result_path = self.base_path / "results"
        self.result_path.mkdir(parents=True, exist_ok=True)

    def __run__(self):
        """Initialize data by loading symbol, spreads, candles, and report."""
        print('Data Analysis complete.')


