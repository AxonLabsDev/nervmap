"""Service fingerprinting by port number and process name."""

from __future__ import annotations


# Port -> (service_type, display_name)
PORT_FINGERPRINTS: dict[int, tuple[str, str]] = {
    # Databases
    3306: ("mysql", "MySQL"),
    5432: ("postgres", "PostgreSQL"),
    5433: ("postgres", "PostgreSQL (alt)"),
    6379: ("redis", "Redis"),
    6380: ("redis", "Redis (alt)"),
    27017: ("mongodb", "MongoDB"),
    27018: ("mongodb", "MongoDB (alt)"),
    9042: ("cassandra", "Cassandra"),
    7000: ("cassandra", "Cassandra (cluster)"),
    5984: ("couchdb", "CouchDB"),
    8529: ("arangodb", "ArangoDB"),
    26257: ("cockroachdb", "CockroachDB"),
    28015: ("rethinkdb", "RethinkDB"),
    9200: ("elasticsearch", "Elasticsearch"),
    9300: ("elasticsearch", "Elasticsearch (transport)"),
    7474: ("neo4j", "Neo4j"),
    7687: ("neo4j", "Neo4j (bolt)"),
    8086: ("influxdb", "InfluxDB"),
    4317: ("otel", "OpenTelemetry (gRPC)"),
    4318: ("otel", "OpenTelemetry (HTTP)"),

    # Message queues
    5672: ("rabbitmq", "RabbitMQ"),
    15672: ("rabbitmq", "RabbitMQ (management)"),
    9092: ("kafka", "Kafka"),
    4222: ("nats", "NATS"),
    6222: ("nats", "NATS (cluster)"),
    1883: ("mqtt", "MQTT"),
    8883: ("mqtt", "MQTT (TLS)"),

    # Web / HTTP
    80: ("http", "HTTP"),
    443: ("https", "HTTPS"),
    8080: ("http", "HTTP (alt)"),
    8443: ("https", "HTTPS (alt)"),
    3000: ("http", "HTTP (dev)"),
    3001: ("http", "HTTP (dev)"),
    4000: ("http", "HTTP (dev)"),
    5000: ("http", "HTTP (dev)"),
    8000: ("http", "HTTP (dev)"),
    8888: ("http", "HTTP (dev)"),
    9090: ("prometheus", "Prometheus"),
    3100: ("loki", "Grafana Loki"),
    3200: ("grafana", "Grafana"),

    # Infrastructure
    22: ("ssh", "SSH"),
    53: ("dns", "DNS"),
    2375: ("docker", "Docker API"),
    2376: ("docker", "Docker API (TLS)"),
    8500: ("consul", "Consul"),
    2379: ("etcd", "etcd"),
    2380: ("etcd", "etcd (peer)"),
    6443: ("kubernetes", "Kubernetes API"),
    10250: ("kubelet", "Kubelet"),

    # Proxies / LB
    8001: ("proxy", "Proxy / API Gateway"),
    8081: ("proxy", "Proxy"),
    8082: ("proxy", "Proxy"),
    1080: ("socks", "SOCKS Proxy"),
    3128: ("squid", "Squid Proxy"),

    # Monitoring
    9100: ("node_exporter", "Prometheus Node Exporter"),
    9090: ("prometheus", "Prometheus"),
    9093: ("alertmanager", "Alertmanager"),
    16686: ("jaeger", "Jaeger"),
    9411: ("zipkin", "Zipkin"),

    # Misc
    11211: ("memcached", "Memcached"),
    1433: ("mssql", "MS SQL Server"),
    1521: ("oracle", "Oracle DB"),
    25: ("smtp", "SMTP"),
    587: ("smtp", "SMTP (submission)"),
    993: ("imap", "IMAP (TLS)"),
    995: ("pop3", "POP3 (TLS)"),
    8124: ("http", "HTTP (custom)"),
    5556: ("http", "HTTP (custom)"),
    5001: ("http", "HTTP (custom)"),
    5002: ("http", "HTTP (custom)"),
    7681: ("http", "HTTP (custom)"),
}


class ServiceFingerprinter:
    """Identify service type based on port and process metadata."""

    def fingerprint(self, port: int, cmdline: str = "", name: str = "") -> tuple[str, str]:
        """Return (service_type, display_name) for a port.

        Falls back to heuristics from cmdline and name if port is unknown.
        """
        if port in PORT_FINGERPRINTS:
            return PORT_FINGERPRINTS[port]

        # Heuristic from process name
        lower_name = name.lower()
        lower_cmd = cmdline.lower()

        for keyword, stype, display in [
            ("nginx", "nginx", "Nginx"),
            ("apache", "apache", "Apache"),
            ("httpd", "apache", "Apache"),
            ("caddy", "caddy", "Caddy"),
            ("traefik", "traefik", "Traefik"),
            ("haproxy", "haproxy", "HAProxy"),
            ("postgres", "postgres", "PostgreSQL"),
            ("mysql", "mysql", "MySQL"),
            ("redis", "redis", "Redis"),
            ("mongo", "mongodb", "MongoDB"),
            ("node", "node", "Node.js"),
            ("python", "python", "Python"),
            ("java", "java", "Java"),
            ("go", "go", "Go"),
            ("rust", "rust", "Rust"),
            ("ruby", "ruby", "Ruby"),
        ]:
            if keyword in lower_name or keyword in lower_cmd:
                return stype, display

        return "unknown", f"Port {port}"

    def fingerprint_service(self, svc) -> str:
        """Return a human-readable type label for a Service."""
        from nervmap.models import Service
        if not isinstance(svc, Service):
            return "unknown"

        cmdline = svc.metadata.get("cmdline", "")
        for port in svc.ports:
            stype, display = self.fingerprint(port, cmdline, svc.name)
            if stype != "unknown":
                return display
        return svc.name
