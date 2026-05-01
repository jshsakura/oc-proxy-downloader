# -*- coding: utf-8 -*-
"""pytest 공용 설정.

backend 디렉토리를 sys.path 에 추가해서 ``core.*`` / ``services.*`` 등을
import 할 수 있게 한다.

또한 테스트 실행 중 ``CONFIG_DIR`` 을 임시 디렉터리로 격리해서, 단위
테스트가 실제 ``backend/config/`` 의 ``parse_debug_*.html``, ``config.json``,
``downloads.db`` 같은 운영 파일을 덮어쓰지 않도록 한다. (실제로 발생했던
사고: ``_save_parse_debug`` 가 테스트 픽스처 HTML 을 운영 디버그 파일에
써서 사용자가 실패 원인을 추적할 수 없었음.)
"""

import os
import sys
import tempfile

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# core.config 가 import 되기 전에 먼저 환경변수를 잡아둔다.
# 테스트는 항상 실제 운영 설정 디렉터리와 격리되어야 하므로 강제로 덮어쓴다
# (CONFIG_PATH / OC_CONFIG_DIR 둘 다). config 모듈은 OC_CONFIG_DIR 을
# 우선 확인하므로 그 값만 세팅해도 충분하지만, 명시적으로 둘 다 잡아 안전.
_TEST_CONFIG_DIR = tempfile.mkdtemp(prefix="oc_test_config_")
os.environ["OC_CONFIG_DIR"] = _TEST_CONFIG_DIR
os.environ.pop("CONFIG_PATH", None)
