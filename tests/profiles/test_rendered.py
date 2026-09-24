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
    assert one(aws, "Canary", app_name())["spec"]["provider"] == "nginx"
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
