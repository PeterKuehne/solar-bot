import logging.config
import os

def setup_logging():
    """Configure logging for the application"""
    config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
            },
        },
        'handlers': {
            'default': {
                'level': 'INFO',
                'formatter': 'standard',
                'class': 'logging.StreamHandler',
                'stream': 'ext://sys.stdout',
            },
        },
        'loggers': {
            '': {  # root logger
                'handlers': ['default'],
                'level': os.getenv('LOG_LEVEL', 'INFO'),
                'propagate': True
            },
            'uvicorn': {
                'handlers': ['default'],
                'level': 'INFO',
                'propagate': False
            },
            'services': {
                'handlers': ['default'],
                'level': 'INFO',
                'propagate': False
            }
        }
    }
    
    logging.config.dictConfig(config)