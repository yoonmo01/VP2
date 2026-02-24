# 라우터 합치기용 편의 모듈 (main.py에서 필요 시 사용할 수 있음)

from .offenders import router as offenders
from .victims import router as victims


__all__ = [ "offenders", "victims"]
