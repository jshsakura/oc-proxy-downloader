# -*- coding: utf-8 -*-
"""pytest 공용 설정.

backend 디렉토리를 sys.path 에 추가해서 ``core.*`` / ``services.*`` 등을
import 할 수 있게 한다.
"""

import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
