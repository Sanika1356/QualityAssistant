import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# redis-py 8 speaks RESP3 by default, which needs Redis 6+. The local Windows Redis is 5.x,
# and Celery offers no setting to pass the protocol through, so pick it here (default RESP2).
REDIS_PROTOCOL = int(os.environ.get('REDIS_PROTOCOL', '2'))
if REDIS_PROTOCOL != 3:
    import redis.asyncio.connection
    import redis.connection
    import redis.utils

    for module in (redis.utils, redis.connection, redis.asyncio.connection):
        module.DEFAULT_RESP_VERSION = REDIS_PROTOCOL

app = Celery('config')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
