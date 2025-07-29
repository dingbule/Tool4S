from PyInstaller.utils.hooks import copy_metadata
import os
import matplotlib

mat_root = os.path.dirname(matplotlib.__file__)
datas = [
    (os.path.join(mat_root, "mpl-data"), os.path.join('matplotlib', 'mpl-data')),
]
# add pyparsing is necessary for matplotlib
metadata = copy_metadata('matplotlib')+ copy_metadata('pyparsing')
datas += metadata