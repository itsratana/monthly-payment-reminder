import logging
import re


class SecretSafeFormatter(logging.Formatter):
    def __init__(self,token):
        super().__init__('%(asctime)s %(levelname)s %(name)s %(message)s')
        self.token=token
    def format(self,record):
        value=super().format(record)
        if self.token: value=value.replace(self.token,'[REDACTED]')
        return re.sub(r'bot\d+:[A-Za-z0-9_-]+','bot[REDACTED]',value)


def configure_logging(level,token):
    root=logging.getLogger();root.setLevel(level.upper())
    if not root.handlers: root.addHandler(logging.StreamHandler())
    for handler in root.handlers: handler.setFormatter(SecretSafeFormatter(token))
