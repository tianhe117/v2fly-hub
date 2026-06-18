import sys
import threading
from datetime import datetime
from collections import deque


class WebLogger:
    """Web UI 日志收集器"""

    def __init__(self, max_lines=500):
        self.logs = deque(maxlen=max_lines)
        self.lock = threading.Lock()
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        self._setup()

    def _setup(self):
        """重定向 stdout 和 stderr"""
        sys.stdout = self._create_writer('stdout', 'info')
        sys.stderr = self._create_writer('stderr', 'error')

    def _create_writer(self, stream_name, level):
        """创建一个写入器，同时输出到原始流和日志"""
        return LogWriter(self, stream_name, level, self._original_stdout if stream_name == 'stdout' else self._original_stderr)

    def add(self, level, module, message):
        """添加日志"""
        now = datetime.now().strftime('%H:%M:%S')
        entry = {
            'time': now,
            'level': level,
            'module': module,
            'message': message
        }
        with self.lock:
            self.logs.append(entry)

    def get_logs(self, since_index=0):
        """获取日志，从指定索引开始"""
        with self.lock:
            return list(self.logs)[since_index:]

    def get_count(self):
        """获取日志总数"""
        with self.lock:
            return len(self.logs)

    def restore(self):
        """恢复原始 stdout/stderr"""
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr


class LogWriter:
    """日志写入器，模拟文件对象"""

    def __init__(self, logger, stream_name, level, original):
        self.logger = logger
        self.stream_name = stream_name
        self.level = level
        self.original = original

    def write(self, text):
        """写入文本"""
        # 输出到原始流
        self.original.write(text)

        # 如果有内容，添加到日志
        text = text.strip()
        if text:
            # 尝试识别模块名
            module = 'system'
            if '[' in text and ']' in text:
                try:
                    start = text.index('[') + 1
                    end = text.index(']')
                    module = text[start:end]
                except:
                    pass

            self.logger.add(self.level, module, text)

    def flush(self):
        """刷新"""
        self.original.flush()

    def fileno(self):
        """返回文件描述符"""
        return self.original.fileno()


# 全局日志实例
web_logger = WebLogger()


def log(level, module, message):
    """添加日志的便捷函数"""
    web_logger.add(level, module, message)
