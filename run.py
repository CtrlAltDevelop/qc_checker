from pathlib import Path
from tqdm import tqdm

from source.main import QCChecker


if __name__ == '__main__':
    """
    The main entry point of the application.
    """
    tqdm.pandas()
    app = QCChecker(Path.cwd())
    app.safe_run()
