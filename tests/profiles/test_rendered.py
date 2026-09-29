"""Contracts for the two effective profile renderings."""

import os
from pathlib import Path

import yaml


def app_name():
    contract = yaml.safe_load(Path("k8s/fleet-app/fleet-app.yaml").read_text())
    return contract["data"]["APP_NAME"]


def load(profile: str):
    root = Path(os.environ["FLEET_RENDER_DIR"])
    return [item for item in yaml.safe_load_all((root / profile / "resources.yaml").read_text()) if item]


def one(resources, kind, name):
    matches = [r for r in resources if r.get("kind") == kind and r.get("metadata", {}).get("name") == name]
    assert len(matches) == 1
    return matches[0]


def test_shared_workload_contract_is_preserved_in_both_profiles():
    for profile in ("local", "aws-staging"):
        resources = load(profile)
        deployment = one(resources, "Deployment", app_name())
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        assert deployment["spec"]["strategy"]["rollingUpdate"] == {"maxSurge": 1, "maxUnavailable": 0}
        assert "replicas" not in deployment["spec"]
        assert container["readinessProbe"]
        metric_names = {metric["name"] for metric in one(resources, "Canary", app_name())["spec"]["analysis"]["metrics"]}
        assert metric_names == {"workload-request-success-rate", "workload-request-duration"}
        one(resources, "ValidatingPolicy", "require-rollout-capacity")
        assert container["name"] == app_name()


def test_profiles_select_distinct_images_routing_and_registry_policies():
    local = load("local")
    aws = load("aws-staging")
    local_container = one(local, "Deployment", app_name())["spec"]["template"]["spec"]["containers"][0]
    aws_container = one(aws, "Deployment", app_name())["spec"]["template"]["spec"]["containers"][0]
    assert local_container["image"] == f"fleet-local-registry:5000/{app_name()}:git-validation"
    assert aws_container["image"].startswith("123456789012.dkr.ecr.eu-west-2.amazonaws.com/")
    assert one(local, "Canary", app_name())["spec"]["provider"] == "gatewayapi:v1"
    assert one(aws, "Canary", app_name())["spec"]["provider"] == "gatewayapi:v1"
    one(local, "ValidatingPolicy", "require-local-images")
    one(aws, "ValidatingPolicy", "require-ecr-images")
    assert not any(r.get("metadata", {}).get("name") == "require-ecr-images" for r in local)
    assert not any(r.get("metadata", {}).get("name") == "require-local-images" for r in aws)


def test_only_aws_profile_contains_aws_runtime_resources():
    local = load("local")
    aws = load("aws-staging")
    assert not any(r.get("metadata", {}).get("name") == "aws-load-balancer-controller" for r in local)
    one(aws, "HelmRelease", "aws-load-balancer-controller")
    one(local, "Gateway", "fleet")


def test_local_control_plane_is_isolated_and_least_privileged():
    resources = load("local")
    policy = one(resources, "NetworkPolicy", "control-plane")
    assert policy["metadata"]["namespace"] == "fleet-control"
    assert policy["spec"] == {
        "podSelector": {"matchLabels": {"app": "control-plane"}},
        "policyTypes": ["Ingress"],
        "ingress": [],
    }

    app_role = one(resources, "Role", "app-deployer")
    assert app_role["metadata"]["namespace"] == "applications"
    assert {resource for rule in app_role["rules"] for resource in rule["resources"]} == {
        "services",
        "deployments",
        "horizontalpodautoscalers",
        "networkpolicies",
        "canaries",
        "podmonitors",
    }
    dashboard_role = one(resources, "Role", "app-deployer-dashboards")
    assert dashboard_role["metadata"]["namespace"] == "observability"
    assert dashboard_role["rules"][0]["resources"] == ["configmaps"]


def test_both_profiles_serve_the_app_over_https_through_one_gateway():
    for profile in ("local", "aws-staging"):
        resources = load(profile)
        assert not [r for r in resources if r.get("kind") == "Ingress"], profile
        listeners = {l["name"]: l for l in one(resources, "Gateway", "fleet")["spec"]["listeners"]}
        assert set(listeners) == {"http", "https"}, profile
        https = listeners["https"]
        assert https["protocol"] == "HTTPS" and https["tls"]["mode"] == "Terminate"
        secret = https["tls"]["certificateRefs"][0]["name"]
        certificate = one(resources, "Certificate", "fleet-tls")["spec"]
        assert certificate["secretName"] == secret
        # AWS serves one public host; locally every launched app has its own
        # <app>.localhost host, so the listener takes any host the cert covers.
        host = https.get("hostname", "localhost")
        expected = [host] if profile == "aws-staging" else [host, "*.apps.localhost"]
        assert certificate["dnsNames"] == expected, profile
        assert ("hostname" in https) == (profile == "aws-staging"), profile
        one(resources, "ClusterIssuer", certificate["issuerRef"]["name"])
        # Plain HTTP only redirects; application routes may not attach to it.
        assert listeners["http"]["allowedRoutes"]["namespaces"]["from"] == "Same"
        redirect = one(resources, "HTTPRoute", "https-redirect")["spec"]
        assert redirect["parentRefs"] == [{"name": "fleet", "sectionName": "http"}]
        assert redirect["rules"] == [
            {"filters": [{"type": "RequestRedirect", "requestRedirect": {"scheme": "https", "statusCode": 301}}]}
        ]
        service = one(resources, "Canary", app_name())["spec"]["service"]
        assert service["gatewayRefs"] == [{"name": "fleet", "namespace": "envoy-gateway-system", "sectionName": "https"}]
        assert service["hosts"] == [host]
