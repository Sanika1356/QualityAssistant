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

# Fail fast when Redis is down, so an upload request never hangs.
app.conf.update(
    # Results live in the database; Celery's own result store is never read. Without this,
    # every .delay() spent ~100s retrying the result store when Redis was unavailable.
    task_ignore_result=True,
    task_publish_retry=False,
    broker_connection_timeout=2,
    broker_transport_options={'socket_connect_timeout': 1, 'socket_timeout': 5},
    redis_socket_connect_timeout=1,
    redis_socket_timeout=5,
)
app.autodiscover_tasks()
