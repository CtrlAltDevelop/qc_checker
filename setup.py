import sys
import PyInstaller.__main__
from pathlib import Path


def build():
    # Define the project directory
    project_dir = Path.cwd()

    # Paths to necessary files and directories
    main_script = project_dir / 'run.py'
    site_packages = project_dir / '.venv' / 'Lib' / 'site-packages'
    output_folder = project_dir / 'build'
    version_file = project_dir / 'VERSION'
    icon_path = project_dir / 'icon.ico'
    spec_folder = project_dir / '.build'
    hooks_dir = project_dir / '.hooks'

    # Fetch the version from setup.py or another source
    version = '1.0.0'  # Replace it with dynamic fetching if needed

    # Define the executable name with the version
    exe_name = f'Zarif-QC-Checker_v{version}'

    # Verify that the necessary files exist
    missing_files = []
    if not main_script.is_file():
        missing_files.append(f"Main script not found: {main_script}")
    if not version_file.is_file():
        missing_files.append(f"Version file not found: {version_file}")
    if not icon_path.is_file():
        missing_files.append(f"Icon file not found: {icon_path}")

    if missing_files:
        for error in missing_files:
            print(error)
        sys.exit(1)

    # Ensure the output and spec directories exist
    output_folder.mkdir(parents=True, exist_ok=True)
    spec_folder.mkdir(parents=True, exist_ok=True)

    # Define PyInstaller options
    pyinstaller_options = [
        str(main_script),                       # Path to the main script
        '--clean',                              # Clean PyInstaller cache
        '--console',                            # Uncomment if it's a console app
        '--onefile',                            # Create a single executable
        f'-n={exe_name}',                       # Name of the executable with the version
        f'--icon={icon_path}',                  # Path to the icon file
        f'-p={site_packages}',                  # Path to site-packages (virtualenv)
        f'--specpath={spec_folder}',            # Path to store the spec file
        f'--workpath={spec_folder}',            # Use .build for temporary files
        f'--distpath={output_folder}',          # Output directory for the executable
        f'--version-file={version_file}',       # Path to the version file
        f'--additional-hooks-dir={hooks_dir}',  # Include additional hooks directory
    ]

    # Add hidden imports for pandas and numpy C extensions
    # pyinstaller_options += [
    #     '--hidden-import=pandas',
    #     '--hidden-import=numpy'
    #     '--hidden-import=tkinter'
    # ]

    print("Running PyInstaller with options:")
    print(" ".join(pyinstaller_options))

    # Run PyInstaller with the specified options
    try:
        PyInstaller.__main__.run(pyinstaller_options)
    except Exception as e:
        print(f"PyInstaller failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    build()
