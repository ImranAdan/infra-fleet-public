"""Prometheus client service for querying metrics.

Provides a clean abstraction for Prometheus API queries with proper
error handling, logging, and testability.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from load_harness.constants import PROMETHEUS_QUERY_TIMEOUT


@dataclass
class PrometheusResult:
    """Result from a Prometheus query."""

    labels: Dict[str, str]
    value: float


class PrometheusClient:
    """Client for querying Prometheus metrics API.

    Provides methods for executing PromQL queries with proper error handling
    and result parsing. Supports both scalar and vector queries.

    Attributes:
        url: Base URL of the Prometheus server
        timeout: Query timeout in seconds
    """

    def __init__(
        self,
        url: Optional[str] = None,
        timeout: int = PROMETHEUS_QUERY_TIMEOUT,
        logger: Optional[logging.Logger] = None,
    ):
        """Initialize Prometheus client.

        Args:
            url: Prometheus server URL. If not provided, uses environment config.
            timeout: Query timeout in seconds.
            logger: Optional logger instance.
        """
        self.url = url or self._get_default_url()
        self.timeout = timeout
        self._logger = logger or logging.getLogger(self.__class__.__name__)

    @staticmethod
    def _get_default_url() -> str:
        """Get the default Prometheus URL from environment.

        Priority:
        1. PROMETHEUS_URL environment variable (explicit override)
        2. In Kubernetes (ENVIRONMENT != local): Uses kube-prometheus-stack
        3. Local docker-compose: Uses 'prometheus' service name
        """
        if os.environ.get("PROMETHEUS_URL"):
            return os.environ.get("PROMETHEUS_URL")

        env = os.environ.get("ENVIRONMENT", "local")
        if env == "local":
            return "http://prometheus:9090"
        return "http://kube-prometheus-stack-prometheus.observability.svc.cluster.local:9090"

    def query_scalar(self, query: str) -> Optional[float]:
        """Execute a PromQL query and return a single scalar value.

        Args:
            query: PromQL query string

        Returns:
            The scalar result value, or None if query failed or returned no data.
        """
        try:
            response = requests.get(
                f"{self.url}/api/v1/query",
                params={"query": query},
                timeout=self.timeout,
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    result = data.get("data", {}).get("result", [])
                    if result:
                        return float(result[0].get("value", [0, 0])[1])
            return None
        except requests.exceptions.Timeout:
            self._logger.warning("Prometheus query timed out: %s", query[:50])
            return None
        except requests.exceptions.ConnectionError:
            self._logger.warning("Could not connect to Prometheus at %s", self.url)
            return None
        except (ValueError, KeyError, IndexError) as e:
            self._logger.warning("Error parsing Prometheus response: %s", e)
            return None
        except Exception as e:
            self._logger.warning("Prometheus query failed: %s", e)
            return None

    def query_vector(self, query: str) -> List[PrometheusResult]:
        """Execute a PromQL query and return all results as a vector.

        Args:
            query: PromQL query string

        Returns:
            List of PrometheusResult objects with labels and values.
        """
        try:
            response = requests.get(
                f"{self.url}/api/v1/query",
                params={"query": query},
                timeout=self.timeout,
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    results = []
                    for item in data.get("data", {}).get("result", []):
                        results.append(
                            PrometheusResult(
                                labels=item.get("metric", {}),
                                value=float(item.get("value", [0, 0])[1]),
                            )
                        )
                    return results
            return []
        except requests.exceptions.Timeout:
            self._logger.warning("Prometheus vector query timed out: %s", query[:50])
            return []
        except requests.exceptions.ConnectionError:
            self._logger.warning("Could not connect to Prometheus at %s", self.url)
            return []
        except (ValueError, KeyError, IndexError) as e:
            self._logger.warning("Error parsing Prometheus vector response: %s", e)
            return []
        except Exception as e:
            self._logger.warning("Prometheus vector query failed: %s", e)
            return []

    def is_available(self) -> bool:
        """Check if Prometheus is reachable.

        Returns:
            True if Prometheus responds to health check, False otherwise.
        """
        try:
            response = requests.get(
                f"{self.url}/-/ready",
                timeout=2,
            )
            return response.status_code == 200
        except Exception:
            return False
