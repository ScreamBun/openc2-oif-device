"""
amqp_tools.py
Implements wrapper for kombu module to more-easily read/write from message queue.
"""
import kombu
import socket
import os

from datetime import datetime
from functools import partial
from inspect import isfunction
from multiprocessing import Event, Process
from typing import (
    Callable,
    Dict,
    List,
    Literal,
    Tuple,
    Union
)

# Type Hinting
Callback = Callable[[any, any], None]
Callbacks = Union[
    List[Callback],
    Tuple[Callback, ...]
]

Exchange_Type = Literal['direct', 'fanout', 'headers', 'topic']
Bindings = Dict[
    str,  # Queue Name
    List[Union[  # Exchange
        str,  # Exchange Name, type is direct by default
        Tuple[
            str,  # Exchange Name
            Exchange_Type,  # Exchange Type
            str  # Routing Key
        ]
    ]]
]

# Constants
AMQP_HOST = os.environ.get("QUEUE_HOST", "localhost")
AMQP_PORT = os.environ.get("QUEUE_PORT", 5672)


class Consumer(Process):
    """
    The Consumer class reads messages from message queue and determines what to do with them.
    """
    _callbacks: List[Callback]
    _conn: kombu.Connection
    _debug: bool
    _exit: Event
    _queues: List[kombu.Queue]
    _url: str

    def __init__(self, host: str = AMQP_HOST, port: int = AMQP_PORT, binding: Bindings = None, callbacks: Callbacks = None, debug: bool = False, **kwargs):
        """
        Consume message from the given bindings
        :param host: host running RabbitMQ
        :param port: port which handles AMQP (default 5672)
        :param binding: Queue/Exchange bindings to listen on
            Dict[
                str,  # Queue Name
                List[Union[  # Exchange
                    str,  # Exchange Name, type is direct
                    List[Tuple[
                        str,  # Exchange Name
                        Literal['direct', 'fanout', 'headers', 'topic']  # exchange type
                    ]]
                ]]
            ]
        :param callbacks: list of callback functions which are called upon receiving a message
        :param debug: print debugging messages
        :param **kwargs: extra args
        - Backwards compatibility:
            :param exchange: specifies where to read messages from
            :param routing_key:
        """
        super().__init__()
        self._exit = Event()

        self._url = f"amqp://{host}:{port}"
        self._debug = debug
        self._queues = []

        if isinstance(callbacks, (list, tuple)):
            self._callbacks = [f for f in callbacks if isfunction(f) or isinstance(f, partial)]
        else:
            self._callbacks = []

        # Initialize connection we are consuming from based on defaults/passed params
        self._conn = kombu.Connection(hostname=host, port=port, userid="guest", password="guest", virtual_host="/")
        if binding:
            for queue, exchanges in binding.items():
                queue_bindings = []
                for exchange in exchanges:
                    name, _type, key = (exchange, 'direct', queue) if isinstance(exchange, str) else exchange
                    queue_bindings.append(kombu.binding(exchange=kombu.Exchange(name, type=_type), routing_key=key))
                self._queues.append(kombu.Queue(name=queue, bindings=queue_bindings))

        elif 'exchange' in kwargs and 'routing_key' in kwargs:
            exchange = kombu.Exchange(kwargs['exchange'], type="direct")
            key = kwargs['routing_key']
            # At this point, consumers are reading messages regardless of queue name
            # so I am just setting it to be the same as the exchange.
            self._queues = [kombu.Queue(name=key, bindings=[kombu.binding(exchange=exchange, routing_key=key)])]

        # Start consumer as an independent process
        self.start()
        if self._debug:
            print(f"Connected to {self._url}")

    def run(self) -> None:
        """
        Runs the consumer until stopped.
        """
        with kombu.Consumer(self._conn, queues=self._queues, callbacks=[self._on_message], accept=["text/plain", "application/json"]):
            if self._debug:
                for q in self._queues:
                    binds = ','.join(f'Bind:{{{b.exchange}->{b.routing_key}}}' for b in q.bindings)
                    print(f"Connected to {self._url} on queue {q.name} with [{binds}] and waiting to consume...")

            while not self._exit.is_set():
                try:
                    self._conn.drain_events(timeout=5)
                except socket.timeout:
                    pass
                except KeyboardInterrupt:
                    self.shutdown()

    def _on_message(self, body, message) -> None:
        """
        Default option for a consumer callback, prints out message and message data.
        :param body: contains the body of the message sent
        :param message: contains meta data about the message sent (ie. delivery_info)
        """
        if self._debug:
            print(f"Message Received @ {datetime.now()}")

        message.ack()
        for func in self._callbacks:
            func(body, message)

    def get_exchanges(self) -> List[str]:
        """
        Get a list of exchange names on the queue
        :return: list of exchange names
        """
        exchanges = self._conn.get_manager().get_exchanges()
        return list(filter(None, [exc.get("name", "")for exc in exchanges]))

    def get_queues(self) -> List[str]:
        """
        Get a list of queue names on the queue
        :return: list of queue names
        """
        queues = self._conn.get_manager().get_queues()
        return list(filter(None, [que.get("name", "") for que in queues]))

    def get_binds(self, bind_queue: Union[str, List[str]] = None, bind_exchange: Union[str, List[str]] = None) -> List[Dict[str, str]]:
        """
        Get a list of exchange/topic bindings
        :return: list of exchange/topic bindings
        """
        binds = []
        manager = self._conn.get_manager()
        queues = self.get_queues()
        for queue in queues:
            if bind_queue:
                if isinstance(bind_queue, list) and queue not in bind_queue:
                    continue
                elif isinstance(bind_queue, str) and queue != bind_queue:
                    continue

            for bind in manager.get_queue_bindings(vhost="/", qname=queue):
                exchange = bind.get("source", "")
                if bind_exchange:
                    if isinstance(bind_exchange, list) and exchange not in bind_exchange:
                        continue
                    elif isinstance(bind_exchange, str) and exchange != bind_exchange:
                        continue
                binds.append({
                    "exchange": exchange,
                    "routing_key": bind.get("routing_key", "")
                })

        return binds

    def shutdown(self) -> None:
        """
        Shutdown the consumer and cleanly close the process
        """
        self._exit.set()
        print("The consumer has shutdown.")


class Producer:
    """
    The Producer class writes messages to the message queue to be consumed.
    """
    _conn: kombu.Connection
    _debug: bool
    _url: str

    def __init__(self, host: str = AMQP_HOST, port: int = AMQP_PORT, debug: bool = False):
        """
        Sets up connection to broker to write to.
        :param host: hostname for the queue server
        :param port: port for the queue server
        :param debug: print debugging messages
        """
        self._url = f"amqp://{host}:{port}"
        self._debug = debug
        self._conn = kombu.Connection(hostname=host, port=port, userid="guest", password="guest", virtual_host="/")

    def publish(self, message: Union[dict, str], headers: dict = None, exchange: str = 'transport', routing_key: str = '*', exchange_type: Exchange_Type = 'direct') -> None:
        """
        Publish a message to th AMQP Queue
        :param message: message to be published
        :param headers: header key-values to publish with the message
        :param exchange: specifies the top level specifier for message publish
        :param routing_key: determines which queue the message is published to
        :param exchange_type: Type of the exchange - ['direct', 'fanout', 'headers', 'topic']
        """
        self._conn.connect()
        producer = kombu.Producer(self._conn.channel())
        producer.publish(
            message,
            headers=headers or {},
            exchange=kombu.Exchange(exchange, type=exchange_type),
            routing_key=routing_key
        )
        producer.close()
        self._conn.release()
