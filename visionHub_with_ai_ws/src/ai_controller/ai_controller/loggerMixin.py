"""
logger 주입이 필요한 클래스에 상속해서 사용.
rclpy Node를 상속받지 않는 헬퍼 클래스들의 중복 로깅 코드를 제거.

사용법:
    class MyClass(LoggerMixin):
        def __init__(self, logger=None):
            self.set_logger(logger)
"""

class LoggerMixin:
    def set_logger(self, logger):
        self._logger = logger

    def _log_info(self, msg):
        if self._logger:
            self._logger.info(msg)

    def _log_warn(self, msg):
        if self._logger:
            self._logger.warn(msg)

    def _log_error(self, msg):
        if self._logger:
            self._logger.error(msg)