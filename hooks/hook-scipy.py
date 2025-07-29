from PyInstaller.utils.hooks import copy_metadata
import os
import scipy
mat_root=os.path.dirname(scipy.__file__)
#mat_root="c:\\Users\\dingbule\\anaconda3\\envs\\py38\\lib\\site-packages\\scipy"

datas = [
    (os.path.join(mat_root, "_lib"), os.path.join('scipy', '_lib')),

]

metadata = copy_metadata('scipy')
datas += metadata


