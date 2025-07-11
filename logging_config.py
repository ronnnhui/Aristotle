import os
import logging.config
from datetime import datetime

# 确保logs目录存在
if not os.path.exists('logs'):
    os.makedirs('logs')

# 生成当天的日志文件名
log_filename = f"logs/aristotle_{datetime.now().strftime('%Y%m%d')}.log"

LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'detailed': {
            'format': '%(asctime)s [%(levelname)s] %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S'
        },
        'simple': {
            'format': '[%(levelname)s] %(message)s'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'INFO',
            'formatter': 'simple',
            'stream': 'ext://sys.stdout'
        },
        'file': {
            'class': 'logging.FileHandler',
            'level': 'DEBUG',
            'formatter': 'detailed',
            'filename': log_filename,
            'encoding': 'utf-8'
        }
    },
    'loggers': {
        'aristotle': {
            'level': 'DEBUG',
            'handlers': ['console', 'file'],
            'propagate': False
        }
    }
}

def setup_logging():
    """设置日志配置"""
    logging.config.dictConfig(LOGGING_CONFIG)
    return logging.getLogger('aristotle') 