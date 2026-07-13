from dataclasses import dataclass


@dataclass
class SystemInfo:

    hostname: str

    ip: str

    os: str

    cpu_core: int

    memory_gb: int

    web_server: str

    application: str

    node_name: str

    cluster: str