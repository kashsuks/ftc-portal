import PyInstaller.__main__
import os

# Get the current directory
current_dir = os.path.dirname(os.path.abspath(__file__))

# Define the main script path
main_script = os.path.join(current_dir, 'main.py')

# Define the output directory
output_dir = os.path.join(current_dir, 'dist')

# PyInstaller configuration for Windows
PyInstaller.__main__.run([
    'main.py',
    '--name=FTC_Portal',
    '--onefile',
    '--windowed',
    '--add-data=requirements.txt;.',  # Use semicolon for Windows, and fix syntax
    '--clean',
    '--noconfirm',
]) 