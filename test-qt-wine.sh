#!/bin/bash
# Test PyQt6 functionality in Wine

echo "Testing PyQt6 w Wine environment..."

# Test basic Qt import
echo "1. Testing basic PyQt6 import..."
wine python -c "
import PyQt6.QtCore
import PyQt6.QtWidgets
import PyQt6.QtGui
print('✅ Basic PyQt6 imports OK')
"

# Test Qt application creation
echo "2. Testing Qt application creation..."
wine python -c "
import sys
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt6.QtWidgets import QApplication, QWidget
app = QApplication(sys.argv)
widget = QWidget()
print('✅ Qt application creation OK')
app.quit()
"

# Check Qt plugins
echo "3. Checking Qt plugins..."
wine python -c "
import PyQt6.QtCore
import os
qt_dir = os.path.dirname(PyQt6.QtCore.__file__)
print(f'PyQt6 directory: {qt_dir}')

plugins_dirs = [
    os.path.join(qt_dir, 'Qt6', 'plugins'),
    os.path.join(qt_dir, 'plugins'),
    os.path.join(qt_dir, '..', 'PyQt6_Qt6', 'plugins')
]

for plugins_dir in plugins_dirs:
    if os.path.exists(plugins_dir):
        print(f'Found plugins in: {plugins_dir}')
        platforms_dir = os.path.join(plugins_dir, 'platforms')
        if os.path.exists(platforms_dir):
            print('Platform plugins:')
            for f in os.listdir(platforms_dir):
                print(f'  {f}')
        break
else:
    print('⚠️  No Qt plugins found')
"

echo "Qt Wine test completed."