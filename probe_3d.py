from PyQt6 import QtCore
print('QtCore available')
try:
    from PyQt6.Qt3D import QtCore as Qt3DCore
    print('Qt3D available')
except ImportError as e:
    print('Qt3D NOT available:', e)

try:
    from PyQt6.QtOpenGL import QOpenGLWidget
    print('QOpenGLWidget available')
except ImportError as e:
    print('QOpenGLWidget NOT available:', e)

try:
    import numpy
    print('NumPy available')
except ImportError:
    print('NumPy NOT available')

try:
    import trimesh
    print('trimesh available')
except ImportError:
    print('trimesh NOT available')
